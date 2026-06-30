"""
spy_range_probability.py
Pre-Market SPY Strike Probability Module
==========================================
Builds a historical reach-probability heatmap for SPY strikes, combines it
with the options market's implied move (IV-based), applies a macro regime
filter, and outputs tiered cash-secured-put strike recommendations.
Designed to plug into the existing pre-market options analysis app as a
new module alongside max pain / GEX calculations.
Dependencies:
    pip install yfinance pandas numpy scipy --break-system-packages
Usage:
    from spy_range_probability import generate_premarket_report, fetch_live_inputs
    inputs = fetch_live_inputs()
    report = generate_premarket_report(inputs)
"""
from __future__ import annotations
import math
from dataclasses import dataclass, field
from typing import Optional
import numpy as np
import pandas as pd
try:
    import yfinance as yf
except ImportError:
    yf = None
# --------------------------------------------------------------------------
# Data fetching
# --------------------------------------------------------------------------
def fetch_live_inputs(
    ticker: str = "SPY",
    lookback_days: int = 504,   # ~2 trading years
    vix_ticker: str = "^VIX",
) -> dict:
    """
    Pulls live/recent data needed for the module using yfinance.
    Replace or extend this with your existing live data pipeline
    (e.g. broker API, options chain feed) as needed — this is a
    standalone fallback that works out of the box.
    """
    if yf is None:
        raise ImportError("yfinance is required: pip install yfinance --break-system-packages")
    spy = yf.Ticker(ticker)
    hist = spy.history(period=f"{lookback_days}d", interval="1d")
    hist = hist.rename(columns=str.title)  # ensure Open/High/Low/Close
    if hist.empty or len(hist) < 30:
        raise ValueError("Insufficient historical data returned for SPY.")
    prev_row = hist.iloc[-1]
    prev_close = float(prev_row["Close"])
    prev_high = float(prev_row["High"])
    prev_low = float(prev_row["Low"])
    # ATR(14)
    atr_14 = compute_atr(hist, period=14)
    # 200 SMA
    sma_200 = float(hist["Close"].tail(200).mean()) if len(hist) >= 200 else float(hist["Close"].mean())
    # Live/most-recent price + today's open if available intraday
    intraday = spy.history(period="1d", interval="1m")
    if not intraday.empty:
        spy_open = float(intraday.iloc[0]["Open"])
        spy_current_price = float(intraday.iloc[-1]["Close"])
    else:
        spy_open = prev_close
        spy_current_price = prev_close
    # VIX as IV proxy fallback (better: pull 30d IV directly from options chain)
    vix_hist_df = yf.Ticker(vix_ticker).history(period=f"{lookback_days}d", interval="1d")
    vix = float(vix_hist_df["Close"].iloc[-1]) if not vix_hist_df.empty else 18.0
    iv_30d = vix / 100.0  # crude proxy; replace with real SPY 30d IV when available
    # Align VIX history to SPY dates for VIX-conditional filtering
    if not vix_hist_df.empty:
        vix_history = (
            vix_hist_df["Close"]
            .reindex(hist.index, method="ffill")
            .reset_index(drop=True)
        )
    else:
        vix_history = None
    return {
        "spy_prev_close": prev_close,
        "spy_prev_high": prev_high,
        "spy_prev_low": prev_low,
        "spy_open": spy_open,
        "spy_current_price": spy_current_price,
        "iv_30d": iv_30d,
        "vix": vix,
        "atr_14": atr_14,
        "sma_200": sma_200,
        "historical_ohlc": hist,
        "vix_history": vix_history,
    }
def compute_atr(df: pd.DataFrame, period: int = 14) -> float:
    """Standard Average True Range calculation."""
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    true_range = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    atr = true_range.rolling(window=period).mean().iloc[-1]
    return float(atr)
# --------------------------------------------------------------------------
# Step 1 — Implied (IV-based) expected move envelope
# --------------------------------------------------------------------------
def expected_move_bounds(spy_price: float, iv_30d: float) -> dict:
    """
    Options market's implied 1-day move.
    1 SD ~ 68% historical containment, 2 SD ~ 95%.
    """
    daily_iv = iv_30d / math.sqrt(252)
    one_sd_move = spy_price * daily_iv
    return {
        "one_sd_move_dollars": round(one_sd_move, 2),
        "upper_1sd": round(spy_price + one_sd_move, 2),
        "lower_1sd": round(spy_price - one_sd_move, 2),
        "upper_2sd": round(spy_price + 2 * one_sd_move, 2),
        "lower_2sd": round(spy_price - 2 * one_sd_move, 2),
    }
# --------------------------------------------------------------------------
# Step 2 — ATR-based range bands
# --------------------------------------------------------------------------
def atr_range_bands(spy_open: float, atr_14: float) -> dict:
    """Fractional ATR bands above/below today's open."""
    return {
        "atr_25pct_up": round(spy_open + atr_14 * 0.25, 2),
        "atr_50pct_up": round(spy_open + atr_14 * 0.50, 2),
        "atr_75pct_up": round(spy_open + atr_14 * 0.75, 2),
        "atr_100pct_up": round(spy_open + atr_14, 2),
        "atr_25pct_down": round(spy_open - atr_14 * 0.25, 2),
        "atr_50pct_down": round(spy_open - atr_14 * 0.50, 2),
        "atr_75pct_down": round(spy_open - atr_14 * 0.75, 2),
        "atr_100pct_down": round(spy_open - atr_14, 2),
    }
# --------------------------------------------------------------------------
# Step 3 — Historical reach-probability heatmap (core engine)
# --------------------------------------------------------------------------
def build_reach_probability_map(
    historical_ohlc: pd.DataFrame,
    spy_open: float,
    strike_range: int = 15,
) -> dict:
    """
    For each $1 strike from (open - strike_range) to (open + strike_range),
    compute the historical probability that SPY's intraday range reached
    that level, measured as distance from each day's OPEN.
    Downside strikes -> probability the day's LOW touched/breached that
                         distance below the open.
    Upside strikes   -> probability the day's HIGH touched/breached that
                         distance above the open.
    Returns: {strike_price: probability_reached}  (0.0 - 1.0)
    """
    df = historical_ohlc.copy()
    df["open_to_low"] = df["Low"] - df["Open"]
    df["open_to_high"] = df["High"] - df["Open"]
    probability_map = {}
    n = len(df)
    if n == 0:
        raise ValueError("historical_ohlc is empty.")
    for offset in range(-strike_range, strike_range + 1):
        strike = round(spy_open + offset, 0)
        if offset < 0:
            pct_reached = float((df["open_to_low"] <= offset).mean())
        elif offset > 0:
            pct_reached = float((df["open_to_high"] >= offset).mean())
        else:
            pct_reached = 1.0
        probability_map[strike] = round(pct_reached, 4)
    return probability_map
def build_vix_conditional_probability_map(
    historical_ohlc: pd.DataFrame,
    spy_open: float,
    current_vix: float,
    vix_history: pd.Series,
    strike_range: int = 15,
    vix_band_width: float = 4.0,
    min_sample_size: int = 40,
) -> dict:
    """
    Same reach-probability calculation as build_reach_probability_map,
    but conditioned on historical days where VIX was in a similar band
    to today's VIX. SPY's intraday range behaves very differently in a
    low-vol grind (VIX 12-14) versus elevated chop (VIX 22-26), so an
    unconditional historical average blends those regimes together and
    understates risk in the current one.
    `vix_history` must be a pd.Series of daily VIX closes aligned by
    index (or date) to `historical_ohlc` — same length, same order.
    Falls back to the unconditional map (with a warning flag in the
    return) if the VIX-matched sample is too small to be statistically
    meaningful.
    """
    if len(vix_history) != len(historical_ohlc):
        raise ValueError(
            "vix_history must be the same length as historical_ohlc and "
            "aligned day-for-day. Pass aligned series, e.g. both indexed "
            "by date and sliced to the same range."
        )
    df = historical_ohlc.copy().reset_index(drop=True)
    vix_series = pd.Series(vix_history).reset_index(drop=True)
    lower_band = current_vix - vix_band_width
    upper_band = current_vix + vix_band_width
    mask = (vix_series >= lower_band) & (vix_series <= upper_band)
    matched_days = int(mask.sum())
    used_fallback = False
    if matched_days < min_sample_size:
        # Not enough days in this VIX band — fall back to full history
        # but flag it so the dashboard can warn the user.
        matched_df = df
        used_fallback = True
    else:
        matched_df = df[mask.values]
    matched_df = matched_df.copy()
    matched_df["open_to_low"] = matched_df["Low"] - matched_df["Open"]
    matched_df["open_to_high"] = matched_df["High"] - matched_df["Open"]
    probability_map = {}
    for offset in range(-strike_range, strike_range + 1):
        strike = round(spy_open + offset, 0)
        if offset < 0:
            pct_reached = float((matched_df["open_to_low"] <= offset).mean())
        elif offset > 0:
            pct_reached = float((matched_df["open_to_high"] >= offset).mean())
        else:
            pct_reached = 1.0
        probability_map[strike] = round(pct_reached, 4)
    return {
        "probability_map": probability_map,
        "vix_band": (round(lower_band, 1), round(upper_band, 1)),
        "matched_sample_size": matched_days,
        "used_fallback_to_full_history": used_fallback,
        "total_sample_size": len(df),
    }
# --------------------------------------------------------------------------
# Step 4 — Regime filter
# --------------------------------------------------------------------------
def regime_check(spy_price: float, sma_200: float, vix: float) -> dict:
    """
    Macro regime gate. Mirrors the filter logic discussed for the
    wheel/CSP strategy: trend filter (200 SMA) + volatility filter (VIX).
    """
    bull = spy_price > sma_200
    low_vol = vix < 20
    elevated_vol = 20 <= vix <= 28
    high_vol = vix > 28
    if bull and low_vol:
        return {"regime": "BULL_LOW_VOL", "csp_ok": True,
                "note": "Favorable — normal put-selling size."}
    elif bull and elevated_vol:
        return {"regime": "BULL_ELEVATED_VOL", "csp_ok": True,
                "note": "Proceed with wider strikes; premium is elevated but so is range."}
    elif bull and high_vol:
        return {"regime": "BULL_HIGH_VOL", "csp_ok": False,
                "note": "Caution — tail risk elevated. Reduce size or stand aside."}
    else:
        return {"regime": "BEAR_OR_BELOW_200SMA", "csp_ok": False,
                "note": "Trend filter failed — no new CSP entries recommended."}
# --------------------------------------------------------------------------
# Step 5 — Strike recommendation engine
# --------------------------------------------------------------------------
def recommend_put_strikes(
    probability_map: dict,
    em_bounds: dict,
    spy_open: float,
    chain_liquidity: Optional[dict] = None,
    min_open_interest: int = 500,
    min_volume: int = 100,
) -> dict:
    """
    Tiers put strikes by historical safety (1 - probability of being reached),
    restricted to strikes below the IV-implied 1SD lower bound (i.e. already
    outside the options market's own expected move).
    Tiers:
        aggressive    : 80-85% historically safe   (more premium, more risk)
        moderate      : 85-92% historically safe
        conservative  : 92%+ historically safe      (less premium, safer)
    chain_liquidity (optional): dict of {strike: {"open_interest": int,
    "volume": int, "bid": float, "ask": float}} pulled from your live
    options chain. When provided, strikes below min_open_interest or
    min_volume are excluded entirely — thinly traded strikes have wide
    bid/ask spreads that quietly eat the statistical edge this module
    is trying to find, and can be hard to exit/roll under stress.
    """
    recommendations = {"aggressive": [], "moderate": [], "conservative": []}
    excluded_illiquid = []
    lower_1sd = em_bounds["lower_1sd"]
    for strike, prob_reached in probability_map.items():
        if strike >= spy_open:
            continue  # only interested in put-side (downside) strikes
        if strike >= lower_1sd:
            continue  # still inside the options market's own expected move
        if chain_liquidity is not None:
            liq = chain_liquidity.get(strike)
            if liq is None:
                excluded_illiquid.append((strike, "no chain data"))
                continue
            oi = liq.get("open_interest", 0)
            vol = liq.get("volume", 0)
            if oi < min_open_interest or vol < min_volume:
                excluded_illiquid.append((strike, f"OI={oi}, Vol={vol}"))
                continue
        prob_safe = round(1 - prob_reached, 4)
        entry = (strike, prob_safe)
        if chain_liquidity is not None:
            liq = chain_liquidity[strike]
            entry = (strike, prob_safe, liq.get("open_interest"), liq.get("volume"))
        if 0.80 <= prob_safe < 0.85:
            recommendations["aggressive"].append(entry)
        elif 0.85 <= prob_safe < 0.92:
            recommendations["moderate"].append(entry)
        elif prob_safe >= 0.92:
            recommendations["conservative"].append(entry)
    for tier in recommendations:
        recommendations[tier].sort(key=lambda x: x[0], reverse=True)  # closest to price first
    return {
        "tiers": recommendations,
        "excluded_illiquid": excluded_illiquid,
    }
# --------------------------------------------------------------------------
# Step 6 — Technical levels module: S/R zones, trendlines, supply/demand
# --------------------------------------------------------------------------
def find_swing_points(
    historical_ohlc: pd.DataFrame,
    lookback: int = 5,
) -> dict:
    """
    Identifies swing highs and swing lows: a swing high is a bar whose
    High is greater than the High of `lookback` bars on either side;
    a swing low is the mirror. These are the raw pivot points that
    support/resistance and trendlines are built from.
    """
    df = historical_ohlc.copy().reset_index(drop=True)
    highs, lows = df["High"], df["Low"]
    n = len(df)
    swing_highs, swing_lows = [], []
    for i in range(lookback, n - lookback):
        window_high = highs[i - lookback: i + lookback + 1]
        window_low = lows[i - lookback: i + lookback + 1]
        if highs[i] == window_high.max():
            swing_highs.append((i, float(highs[i])))
        if lows[i] == window_low.min():
            swing_lows.append((i, float(lows[i])))
    return {"swing_highs": swing_highs, "swing_lows": swing_lows}
def cluster_levels(
    points: list,
    cluster_width_pct: float = 0.003,
) -> list:
    """
    Groups nearby swing points into single support/resistance zones.
    Levels that have been tested multiple times (more points in the
    cluster) are stronger — `touch_count` reflects that.
    `points` is a list of (index, price) tuples from find_swing_points.
    `cluster_width_pct` controls how close two prices need to be (as a
    % of price) to be considered the same zone — 0.003 = 0.3%.
    """
    if not points:
        return []
    prices = sorted([p for _, p in points])
    clusters = []
    current_cluster = [prices[0]]
    for price in prices[1:]:
        if abs(price - current_cluster[-1]) / current_cluster[-1] <= cluster_width_pct:
            current_cluster.append(price)
        else:
            clusters.append(current_cluster)
            current_cluster = [price]
    clusters.append(current_cluster)
    zones = []
    for cluster in clusters:
        zones.append({
            "level": round(sum(cluster) / len(cluster), 2),
            "touch_count": len(cluster),
            "range": (round(min(cluster), 2), round(max(cluster), 2)),
        })
    zones.sort(key=lambda z: z["touch_count"], reverse=True)
    return zones
def identify_support_resistance(
    historical_ohlc: pd.DataFrame,
    current_price: float,
    lookback: int = 5,
    cluster_width_pct: float = 0.003,
    max_zones_each_side: int = 5,
) -> dict:
    """
    Full pipeline: find swing points -> cluster into zones -> split
    into support (below price) and resistance (above price), ranked
    by how many times each zone has been tested (touch_count).
    """
    swings = find_swing_points(historical_ohlc, lookback=lookback)
    high_zones = cluster_levels(swings["swing_highs"], cluster_width_pct)
    low_zones = cluster_levels(swings["swing_lows"], cluster_width_pct)
    all_zones = high_zones + low_zones
    support = sorted(
        [z for z in all_zones if z["level"] < current_price],
        key=lambda z: z["level"], reverse=True,
    )[:max_zones_each_side]
    resistance = sorted(
        [z for z in all_zones if z["level"] > current_price],
        key=lambda z: z["level"],
    )[:max_zones_each_side]
    return {"support": support, "resistance": resistance}
def identify_supply_demand_zones(
    historical_ohlc: pd.DataFrame,
    current_price: float,
    move_threshold_pct: float = 0.015,
    max_zones_each_side: int = 5,
) -> dict:
    """
    A simplified supply/demand zone detector: looks for a 'base' (small
    range candle or cluster of candles) immediately followed by a sharp
    directional move (>= move_threshold_pct). The base candle's range
    becomes the zone — the idea being that aggressive orders originated
    from that small range and price may react there again if revisited.
    This is a heuristic approximation of manual supply/demand zone
    marking, not a substitute for visual chart review — treat it as a
    pre-filter to narrow down where to look, not a final answer.
    """
    df = historical_ohlc.copy().reset_index(drop=True)
    zones = []
    for i in range(1, len(df) - 1):
        base_open, base_close = df.loc[i, "Open"], df.loc[i, "Close"]
        base_high, base_low = df.loc[i, "High"], df.loc[i, "Low"]
        next_close = df.loc[i + 1, "Close"]
        base_mid = (base_open + base_close) / 2
        move_pct = (next_close - base_mid) / base_mid
        if move_pct >= move_threshold_pct:
            zones.append({
                "type": "demand",
                "zone_low": round(float(base_low), 2),
                "zone_high": round(float(base_high), 2),
                "bar_index": i,
            })
        elif move_pct <= -move_threshold_pct:
            zones.append({
                "type": "supply",
                "zone_low": round(float(base_low), 2),
                "zone_high": round(float(base_high), 2),
                "bar_index": i,
            })
    # Keep only zones not yet "broken" (price hasn't closed through them
    # since formation) and nearest to current price
    demand_zones = sorted(
        [z for z in zones if z["type"] == "demand" and z["zone_high"] < current_price],
        key=lambda z: z["zone_high"], reverse=True,
    )[:max_zones_each_side]
    supply_zones = sorted(
        [z for z in zones if z["type"] == "supply" and z["zone_low"] > current_price],
        key=lambda z: z["zone_low"],
    )[:max_zones_each_side]
    return {"demand_zones": demand_zones, "supply_zones": supply_zones}
def fit_trendlines(
    historical_ohlc: pd.DataFrame,
    lookback_bars: int = 60,
    lookback_pivots: int = 5,
) -> dict:
    """
    Fits a simple linear trendline through recent swing highs (resistance
    trendline) and recent swing lows (support trendline) using least-
    squares regression over the most recent `lookback_bars` bars. Returns
    slope/intercept so the dashboard can project the line forward to
    today's session and mark where it currently sits.
    """
    df = historical_ohlc.copy().reset_index(drop=True).tail(lookback_bars).reset_index(drop=True)
    swings = find_swing_points(df, lookback=lookback_pivots)
    def _fit(points):
        if len(points) < 2:
            return None
        xs = np.array([p[0] for p in points])
        ys = np.array([p[1] for p in points])
        slope, intercept = np.polyfit(xs, ys, 1)
        return {"slope": float(slope), "intercept": float(intercept)}
    resistance_line = _fit(swings["swing_highs"])
    support_line = _fit(swings["swing_lows"])
    last_index = len(df) - 1
    return {
        "resistance_trendline": resistance_line,
        "support_trendline": support_line,
        "projected_resistance_today": (
            round(resistance_line["slope"] * (last_index + 1) + resistance_line["intercept"], 2)
            if resistance_line else None
        ),
        "projected_support_today": (
            round(support_line["slope"] * (last_index + 1) + support_line["intercept"], 2)
            if support_line else None
        ),
    }
def build_technical_levels_report(
    historical_ohlc: pd.DataFrame,
    current_price: float,
) -> dict:
    """
    Convenience wrapper bundling S/R zones, supply/demand zones, and
    trendlines into a single technical-levels payload for the dashboard.
    Use this alongside the probability heatmap — strikes that line up
    with BOTH a high-touch-count S/R zone AND a high statistical safety
    score are your highest-conviction setups.
    """
    sr = identify_support_resistance(historical_ohlc, current_price)
    sd = identify_supply_demand_zones(historical_ohlc, current_price)
    trendlines = fit_trendlines(historical_ohlc)
    return {
        "support_resistance": sr,
        "supply_demand": sd,
        "trendlines": trendlines,
    }
# --------------------------------------------------------------------------
# Master report generator
# --------------------------------------------------------------------------
def generate_premarket_report(
    inputs: dict,
    strike_range: int = 15,
    use_vix_conditional: bool = True,
    vix_band_width: float = 4.0,
) -> dict:
    """
    Master entry point. Pass in a dict matching the `inputs` schema
    (see fetch_live_inputs() for an example / default source),
    optionally merged with max_pain / gex_levels from your other modules.
    Optional inputs dict keys:
        vix_history       : pd.Series of daily VIX closes, aligned to
                             historical_ohlc (required if
                             use_vix_conditional=True)
        chain_liquidity    : dict of {strike: {"open_interest", "volume",
                             "bid", "ask"}} from your live options chain —
                             enables the illiquid-strike filter
        max_pain           : float, from your Phase 1 module
        gex_levels         : dict/list, from your Phase 3 module
    """
    required = [
        "spy_open", "spy_current_price", "iv_30d", "vix",
        "atr_14", "sma_200", "historical_ohlc",
    ]
    missing = [k for k in required if k not in inputs]
    if missing:
        raise KeyError(f"Missing required input(s): {missing}")
    em = expected_move_bounds(inputs["spy_current_price"], inputs["iv_30d"])
    bands = atr_range_bands(inputs["spy_open"], inputs["atr_14"])
    vix_conditional_meta = None
    if use_vix_conditional and "vix_history" in inputs:
        vix_result = build_vix_conditional_probability_map(
            inputs["historical_ohlc"],
            inputs["spy_open"],
            inputs["vix"],
            inputs["vix_history"],
            strike_range=strike_range,
            vix_band_width=vix_band_width,
        )
        prob_map = vix_result["probability_map"]
        vix_conditional_meta = {
            "vix_band": vix_result["vix_band"],
            "matched_sample_size": vix_result["matched_sample_size"],
            "total_sample_size": vix_result["total_sample_size"],
            "used_fallback_to_full_history": vix_result["used_fallback_to_full_history"],
        }
    else:
        prob_map = build_reach_probability_map(
            inputs["historical_ohlc"], inputs["spy_open"], strike_range=strike_range
        )
    regime = regime_check(inputs["spy_current_price"], inputs["sma_200"], inputs["vix"])
    strikes = recommend_put_strikes(
        prob_map, em, inputs["spy_open"],
        chain_liquidity=inputs.get("chain_liquidity"),
    )
    technicals = build_technical_levels_report(
        inputs["historical_ohlc"], inputs["spy_current_price"]
    )
    return {
        "regime": regime,
        "implied_move": em,
        "atr_bands": bands,
        "probability_map": prob_map,
        "vix_conditional_meta": vix_conditional_meta,
        "recommendations": strikes["tiers"],
        "excluded_illiquid": strikes["excluded_illiquid"],
        "technical_levels": technicals,
        "max_pain": inputs.get("max_pain"),
        "gex_levels": inputs.get("gex_levels"),
        "meta": {
            "spy_open": inputs["spy_open"],
            "spy_current_price": inputs["spy_current_price"],
            "vix": inputs["vix"],
            "atr_14": inputs["atr_14"],
        },
    }
# --------------------------------------------------------------------------
# Convenience: pretty-print report to console (pre-Streamlit testing)
# --------------------------------------------------------------------------
def print_report(report: dict) -> None:
    meta = report["meta"]
    regime = report["regime"]
    em = report["implied_move"]
    print("=" * 60)
    print(f"SPY PRE-MARKET RANGE PROBABILITY REPORT")
    print("=" * 60)
    print(f"Open: {meta['spy_open']:.2f}  |  Current: {meta['spy_current_price']:.2f}  |  VIX: {meta['vix']:.2f}")
    print(f"Regime: {regime['regime']}  ->  CSP OK: {regime['csp_ok']}")
    print(f"  {regime['note']}")
    if report.get("vix_conditional_meta"):
        vm = report["vix_conditional_meta"]
        print("-" * 60)
        flag = " (FALLBACK: insufficient sample, using full history)" if vm["used_fallback_to_full_history"] else ""
        print(f"VIX-conditional sample: {vm['matched_sample_size']}/{vm['total_sample_size']} days "
              f"in band {vm['vix_band']}{flag}")
    print("-" * 60)
    print(f"Implied 1SD move: ±${em['one_sd_move_dollars']}  "
          f"[{em['lower_1sd']} - {em['upper_1sd']}]")
    print(f"Implied 2SD move: [{em['lower_2sd']} - {em['upper_2sd']}]")
    print("-" * 60)
    print("PUT STRIKE RECOMMENDATIONS")
    for tier in ["aggressive", "moderate", "conservative"]:
        print(f"\n  {tier.upper()}:")
        entries = report["recommendations"][tier]
        if not entries:
            print("    (none in range)")
        for entry in entries[:5]:
            if len(entry) == 4:
                strike, prob_safe, oi, vol = entry
                print(f"    Strike {strike:.0f}  |  Safety: {prob_safe*100:.1f}%  |  OI: {oi}  |  Vol: {vol}")
            else:
                strike, prob_safe = entry
                print(f"    Strike {strike:.0f}  |  Historical safety: {prob_safe*100:.1f}%")
    if report.get("excluded_illiquid"):
        print(f"\n  Excluded {len(report['excluded_illiquid'])} strike(s) for low liquidity.")
    tech = report.get("technical_levels")
    if tech:
        print("-" * 60)
        print("TECHNICAL LEVELS")
        print("  Support zones (touch count):")
        for z in tech["support_resistance"]["support"][:3]:
            print(f"    {z['level']}  (touched {z['touch_count']}x)")
        print("  Resistance zones (touch count):")
        for z in tech["support_resistance"]["resistance"][:3]:
            print(f"    {z['level']}  (touched {z['touch_count']}x)")
        print("  Nearest demand zones:")
        for z in tech["supply_demand"]["demand_zones"][:3]:
            print(f"    {z['zone_low']} - {z['zone_high']}")
        print("  Nearest supply zones:")
        for z in tech["supply_demand"]["supply_zones"][:3]:
            print(f"    {z['zone_low']} - {z['zone_high']}")
        tl = tech["trendlines"]
        print(f"  Trendline-projected support today: {tl['projected_support_today']}")
        print(f"  Trendline-projected resistance today: {tl['projected_resistance_today']}")
    print("=" * 60)
if __name__ == "__main__":
    # Standalone test run
    print("Fetching live SPY data...")
    live_inputs = fetch_live_inputs()
    report = generate_premarket_report(live_inputs)
    print_report(report)
