"""Alpaca-backed market data for SPY pre-market analysis."""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Optional

import pandas as pd

from config import get_alpaca_config
from spy_range_probability import compute_atr

try:
    from alpaca.data.historical import OptionHistoricalDataClient, StockHistoricalDataClient
    from alpaca.data.requests import OptionChainRequest, StockBarsRequest, StockLatestQuoteRequest
    from alpaca.data.timeframe import TimeFrame
    from alpaca.trading.client import TradingClient
    from alpaca.trading.enums import ContractType
    from alpaca.trading.requests import GetOptionContractsRequest
except ImportError as exc:
    raise ImportError("alpaca-py is required: pip install alpaca-py") from exc

try:
    import yfinance as yf
except ImportError:
    yf = None


def _stock_client() -> StockHistoricalDataClient:
    cfg = get_alpaca_config()
    return StockHistoricalDataClient(cfg.api_key, cfg.secret_key)


def _option_data_client() -> OptionHistoricalDataClient:
    cfg = get_alpaca_config()
    return OptionHistoricalDataClient(cfg.api_key, cfg.secret_key)


def _trading_client() -> TradingClient:
    cfg = get_alpaca_config()
    return TradingClient(cfg.api_key, cfg.secret_key, paper=cfg.paper)


def _bars_to_ohlc(bars_df: pd.DataFrame, symbol: str) -> pd.DataFrame:
    if bars_df.empty:
        return pd.DataFrame(columns=["Open", "High", "Low", "Close", "Volume"])
    if isinstance(bars_df.index, pd.MultiIndex):
        df = bars_df.xs(symbol, level="symbol").copy()
    else:
        df = bars_df.copy()
    df.index = pd.to_datetime(df.index)
    if df.index.tz is not None:
        df.index = df.index.tz_localize(None)
    return df.rename(
        columns={
            "open": "Open",
            "high": "High",
            "low": "Low",
            "close": "Close",
            "volume": "Volume",
        }
    )


def _fetch_vix_series(lookback_days: int, spy_index: pd.DatetimeIndex) -> tuple[float, Optional[pd.Series]]:
    """VIX is not on Alpaca; use yfinance as a fallback IV/regime proxy."""
    if yf is None:
        return 18.0, None
    vix_hist_df = yf.Ticker("^VIX").history(period=f"{lookback_days}d", interval="1d")
    if vix_hist_df.empty:
        return 18.0, None
    vix = float(vix_hist_df["Close"].iloc[-1])
    vix_history = (
        vix_hist_df["Close"]
        .reindex(spy_index, method="ffill")
        .reset_index(drop=True)
    )
    return vix, vix_history


def fetch_live_inputs_alpaca(
    ticker: str = "SPY",
    lookback_days: int = 504,
) -> dict:
    """
    Pull SPY historical OHLC, live quote, and derived metrics via Alpaca.
    VIX history still comes from yfinance (Alpaca does not carry the index).
    """
    end = datetime.now(timezone.utc)
    start = end - timedelta(days=int(lookback_days * 1.5))
    stock = _stock_client()

    daily_req = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Day,
        start=start,
        end=end,
        limit=lookback_days + 50,
    )
    daily_bars = stock.get_stock_bars(daily_req)
    hist = _bars_to_ohlc(daily_bars.df, ticker).tail(lookback_days)
    if hist.empty or len(hist) < 30:
        raise ValueError(f"Insufficient Alpaca historical data returned for {ticker}.")

    prev_idx = -2 if len(hist) >= 2 else -1
    prev_row = hist.iloc[prev_idx]
    atr_14 = compute_atr(hist, period=14)
    sma_200 = float(hist["Close"].tail(200).mean()) if len(hist) >= 200 else float(hist["Close"].mean())

    today_start = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    intraday_req = StockBarsRequest(
        symbol_or_symbols=ticker,
        timeframe=TimeFrame.Minute,
        start=today_start,
        end=end,
        limit=10000,
    )
    intraday_bars = stock.get_stock_bars(intraday_req)
    intraday = _bars_to_ohlc(intraday_bars.df, ticker) if not intraday_bars.df.empty else pd.DataFrame()

    quote = stock.get_stock_latest_quote(StockLatestQuoteRequest(symbol_or_symbols=ticker))
    q = quote[ticker]
    spy_current_price = float((q.ask_price + q.bid_price) / 2)

    if not intraday.empty:
        spy_open = float(intraday.iloc[0]["Open"])
    else:
        spy_open = float(prev_row["Open"])

    vix, vix_history = _fetch_vix_series(lookback_days, hist.index)

    return {
        "spy_prev_close": float(prev_row["Close"]),
        "spy_prev_high": float(prev_row["High"]),
        "spy_prev_low": float(prev_row["Low"]),
        "spy_open": spy_open,
        "spy_current_price": spy_current_price,
        "iv_30d": vix / 100.0,
        "vix": vix,
        "atr_14": atr_14,
        "sma_200": sma_200,
        "historical_ohlc": hist,
        "vix_history": vix_history,
        "data_source": "alpaca",
    }


def _pick_nearest_expiration(contracts) -> date:
    today = date.today()
    expirations = sorted({c.expiration_date for c in contracts if c.expiration_date >= today})
    if not expirations:
        expirations = sorted({c.expiration_date for c in contracts})
    if not expirations:
        raise ValueError("No option expirations found for underlying.")
    return expirations[0]


def _fetch_contracts_for_expiration(underlying: str, expiration: date):
    trading = _trading_client()
    contracts = []
    page_token = None
    while True:
        req = GetOptionContractsRequest(
            underlying_symbols=[underlying],
            expiration_date=expiration.isoformat(),
            limit=10000,
            page_token=page_token,
        )
        resp = trading.get_option_contracts(req)
        contracts.extend(resp.option_contracts)
        page_token = resp.next_page_token
        if not page_token:
            break
    return contracts


def fetch_options_chain(
    underlying: str = "SPY",
    spot_price: Optional[float] = None,
    strike_window: int = 25,
    expiration: Optional[date] = None,
) -> dict:
    """
    Fetch merged options chain: OI from Trading API, greeks/quotes from Market Data API.
    Returns a normalized chain dict consumed by max_pain, gex, and strike liquidity filters.
    """
    trading = _trading_client()
    option_data = _option_data_client()

    probe = GetOptionContractsRequest(
        underlying_symbols=[underlying],
        expiration_date_gte=date.today().isoformat(),
        limit=100,
    )
    probe_resp = trading.get_option_contracts(probe)
    if not probe_resp.option_contracts:
        raise ValueError(f"No active option contracts found for {underlying}.")

    exp = expiration or _pick_nearest_expiration(probe_resp.option_contracts)
    contracts = _fetch_contracts_for_expiration(underlying, exp)

    if spot_price is None:
        spot_price = fetch_live_inputs_alpaca(underlying)["spy_current_price"]

    strike_lo = max(1.0, spot_price - strike_window)
    strike_hi = spot_price + strike_window
    chain_req = OptionChainRequest(
        underlying_symbol=underlying,
        expiration_date=exp.isoformat(),
        strike_price_gte=strike_lo,
        strike_price_lte=strike_hi,
    )
    snapshots = option_data.get_option_chain(chain_req)

    contract_by_symbol = {c.symbol: c for c in contracts}
    calls: dict[float, dict] = {}
    puts: dict[float, dict] = {}

    for symbol, snap in snapshots.items():
        contract = contract_by_symbol.get(symbol)
        if contract is None:
            continue
        strike = float(contract.strike_price)
        oi = int(contract.open_interest or 0)
        bid = float(snap.latest_quote.bid_price) if snap.latest_quote else 0.0
        ask = float(snap.latest_quote.ask_price) if snap.latest_quote else 0.0
        volume = int(snap.latest_trade.size) if snap.latest_trade else 0
        gamma = float(snap.greeks.gamma) if snap.greeks else 0.0
        delta = float(snap.greeks.delta) if snap.greeks else 0.0
        iv = float(snap.implied_volatility or 0.0)

        row = {
            "symbol": symbol,
            "strike": strike,
            "open_interest": oi,
            "volume": volume,
            "bid": bid,
            "ask": ask,
            "gamma": gamma,
            "delta": delta,
            "iv": iv,
        }
        if contract.type == ContractType.CALL:
            calls[strike] = row
        else:
            puts[strike] = row

    atm_ivs = []
    for side in (calls, puts):
        if not side:
            continue
        nearest = min(side.keys(), key=lambda k: abs(k - spot_price))
        iv_val = side[nearest].get("iv", 0.0)
        if iv_val > 0:
            atm_ivs.append(iv_val)
    atm_iv = sum(atm_ivs) / len(atm_ivs) if atm_ivs else None

    return {
        "underlying": underlying,
        "expiration": exp.isoformat(),
        "spot_price": spot_price,
        "calls": calls,
        "puts": puts,
        "atm_iv": atm_iv,
    }


def build_chain_liquidity(chain: dict) -> dict:
    """Map put strike -> liquidity stats for recommend_put_strikes()."""
    liquidity: dict[float, dict] = {}
    for strike, row in chain.get("puts", {}).items():
        liquidity[strike] = {
            "open_interest": row.get("open_interest", 0),
            "volume": row.get("volume", 0),
            "bid": row.get("bid", 0.0),
            "ask": row.get("ask", 0.0),
        }
    return liquidity


def apply_chain_to_inputs(inputs: dict, chain: dict) -> dict:
    """Merge Alpaca chain data into the probability module input dict."""
    merged = dict(inputs)
    merged["chain_liquidity"] = build_chain_liquidity(chain)
    if chain.get("atm_iv"):
        merged["iv_30d"] = float(chain["atm_iv"])
    return merged
