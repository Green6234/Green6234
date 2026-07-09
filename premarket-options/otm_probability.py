"""
1DTE put OTM probability engine.

Core question: P(next session close > strike | VIX band)
Used to pick put strikes that historically expired out of the money.
"""
from __future__ import annotations

import math
from typing import Optional

import numpy as np
import pandas as pd

try:
    import yfinance as yf
except ImportError:
    yf = None


def fetch_market_data(
    ticker: str = "SPY",
    lookback_days: int = 504,
    vix_ticker: str = "^VIX",
) -> dict:
    """Pull SPY + VIX history via yfinance."""
    if yf is None:
        raise ImportError("yfinance required: pip install yfinance")

    hist = yf.Ticker(ticker).history(period=f"{lookback_days}d", interval="1d")
    hist = hist.rename(columns=str.title)
    if hist.empty or len(hist) < 60:
        raise ValueError(f"Insufficient history for {ticker}")

    prev_idx = -2 if len(hist) >= 2 else -1
    prev = hist.iloc[prev_idx]

    intraday = yf.Ticker(ticker).history(period="1d", interval="1m")
    if not intraday.empty:
        spy_open = float(intraday.iloc[0]["Open"])
        spy_current = float(intraday.iloc[-1]["Close"])
    else:
        spy_open = float(prev["Open"])
        spy_current = float(prev["Close"])

    sma_200 = float(hist["Close"].tail(200).mean()) if len(hist) >= 200 else float(hist["Close"].mean())

    vix_df = yf.Ticker(vix_ticker).history(period=f"{lookback_days}d", interval="1d")
    vix = float(vix_df["Close"].iloc[-1]) if not vix_df.empty else 18.0
    vix_history = (
        vix_df["Close"].reindex(hist.index, method="ffill").reset_index(drop=True)
        if not vix_df.empty
        else None
    )

    return {
        "ticker": ticker,
        "spy_open": spy_open,
        "spy_current": spy_current,
        "spy_prev_close": float(prev["Close"]),
        "spy_prev_high": float(prev["High"]),
        "spy_prev_low": float(prev["Low"]),
        "vix": vix,
        "sma_200": sma_200,
        "historical_ohlc": hist,
        "vix_history": vix_history,
    }


def detect_gap(spy_open: float, prev_close: float) -> dict:
    gap_pct = (spy_open - prev_close) / prev_close
    if gap_pct > 0.003:
        direction = "GAP_UP"
    elif gap_pct < -0.003:
        direction = "GAP_DOWN"
    else:
        direction = "FLAT"

    min_prob_adjust = 0.0
    if direction == "GAP_DOWN":
        min_prob_adjust = min(0.05, abs(gap_pct) * 5)
    elif direction == "GAP_UP":
        min_prob_adjust = max(-0.02, -abs(gap_pct) * 2)

    return {
        "gap_pct": round(gap_pct * 100, 3),
        "direction": direction,
        "min_prob_adjust": round(min_prob_adjust, 4),
    }


def regime_check(spy_price: float, sma_200: float, vix: float) -> dict:
    bull = spy_price > sma_200
    if bull and vix < 20:
        return {"regime": "BULL_LOW_VOL", "trade_ok": True, "note": "Favorable for 1DTE puts."}
    if bull and vix <= 28:
        return {"regime": "BULL_ELEVATED_VOL", "trade_ok": True, "note": "OK — use higher P(OTM) floor."}
    if bull and vix > 28:
        return {"regime": "BULL_HIGH_VOL", "trade_ok": False, "note": "Elevated tail risk — skip."}
    return {"regime": "BEAR_OR_BELOW_200", "trade_ok": False, "note": "Below 200 SMA — skip new puts."}


def build_otm_probability_table(
    historical_ohlc: pd.DataFrame,
    vix_history: pd.Series,
    current_vix: float,
    spy_open: float,
    dte: int = 1,
    strike_range: int = 15,
    vix_band_width: float = 4.0,
    min_sample_size: int = 40,
) -> dict:
    """
    For each $1 put strike below open, compute historical P(expire OTM).

    1DTE: close on the next trading session > strike.
    """
    if dte != 1:
        raise ValueError("v1 supports dte=1 only")

    df = historical_ohlc.reset_index(drop=True)
    vix = pd.Series(vix_history).reset_index(drop=True)
    if len(vix) != len(df):
        raise ValueError("vix_history must align with historical_ohlc")

    lower = current_vix - vix_band_width
    upper = current_vix + vix_band_width

    rows = []
    for i in range(len(df) - dte):
        rows.append(
            {
                "open": float(df.loc[i, "Open"]),
                "expire_close": float(df.loc[i + dte, "Close"]),
                "vix": float(vix.iloc[i]),
            }
        )
    sample = pd.DataFrame(rows)
    mask = (sample["vix"] >= lower) & (sample["vix"] <= upper)
    matched = sample[mask]
    used_fallback = len(matched) < min_sample_size
    if used_fallback:
        matched = sample

    probabilities: dict[float, dict] = {}
    for offset in range(-strike_range, strike_range + 1):
        strike = round(spy_open + offset, 0)
        if strike >= spy_open:
            continue
        distance = spy_open - strike
        # Same dollars below each day's open — not absolute strike (SPY was ~400 years ago)
        historical_strikes = matched["open"] - distance
        otm_rate = float((matched["expire_close"] > historical_strikes).mean()) if len(matched) else 0.0
        probabilities[strike] = {
            "p_otm": round(otm_rate, 4),
            "p_itm": round(1 - otm_rate, 4),
            "distance_from_open": round(distance, 2),
        }

    return {
        "probabilities": probabilities,
        "vix_band": (round(lower, 1), round(upper, 1)),
        "matched_sample_size": int(mask.sum()),
        "used_sample_size": len(matched),
        "total_sample_size": len(sample),
        "used_fallback": used_fallback,
        "dte": dte,
    }


def recommend_puts(
    probabilities: dict[float, dict],
    min_p_otm: float = 0.85,
    gap_adjust: float = 0.0,
) -> list[dict]:
    """Return strikes meeting minimum P(OTM), sorted closest to open first."""
    floor = min(0.98, max(0.70, min_p_otm + max(0, gap_adjust)))
    recs = []
    for strike, stats in sorted(probabilities.items(), reverse=True):
        p = stats["p_otm"]
        if p >= floor:
            recs.append(
                {
                    "strike": strike,
                    "p_otm": p,
                    "p_otm_pct": round(p * 100, 1),
                    "distance": stats["distance_from_open"],
                    "verdict": "✓" if p >= 0.88 else "~",
                }
            )
    return recs


def generate_report(
    data: Optional[dict] = None,
    dte: int = 1,
    strike_range: int = 15,
    min_p_otm: float = 0.85,
    vix_band_width: float = 4.0,
) -> dict:
    """Full report from live data."""
    data = data or fetch_market_data()
    gap = detect_gap(data["spy_open"], data["spy_prev_close"])
    regime = regime_check(data["spy_current"], data["sma_200"], data["vix"])

    prob_table = build_otm_probability_table(
        data["historical_ohlc"],
        data["vix_history"],
        data["vix"],
        data["spy_open"],
        dte=dte,
        strike_range=strike_range,
        vix_band_width=vix_band_width,
    )

    recommendations = recommend_puts(
        prob_table["probabilities"],
        min_p_otm=min_p_otm,
        gap_adjust=gap["min_prob_adjust"],
    )

    effective_floor = min(0.98, max(0.70, min_p_otm + max(0, gap["min_prob_adjust"])))

    return {
        "meta": {
            "ticker": data["ticker"],
            "spy_open": data["spy_open"],
            "spy_current": data["spy_current"],
            "spy_prev_close": data["spy_prev_close"],
            "vix": data["vix"],
            "dte": dte,
            "min_p_otm_floor": round(effective_floor, 4),
        },
        "gap": gap,
        "regime": regime,
        "probability_table": prob_table,
        "recommendations": recommendations,
    }


def format_report(report: dict) -> str:
    m = report["meta"]
    gap = report["gap"]
    regime = report["regime"]
    pt = report["probability_table"]
    lines = [
        "=" * 60,
        "  1DTE PUT — P(EXPIRE OTM) REPORT",
        "=" * 60,
        f"  {m['ticker']} open: {m['spy_open']:.2f}  |  current: {m['spy_current']:.2f}  |  VIX: {m['vix']:.2f}",
        f"  DTE: {m['dte']}  |  Regime: {regime['regime']}  |  Trade: {'YES' if regime['trade_ok'] else 'NO'}",
        f"  {regime['note']}",
        f"  Gap: {gap['direction']} {gap['gap_pct']:+.2f}%",
        f"  VIX band {pt['vix_band']}: {pt['used_sample_size']} days"
        + (" [fallback]" if pt["used_fallback"] else ""),
        f"  Min P(OTM) floor: {m['min_p_otm_floor']*100:.1f}%",
        "-" * 60,
        f"  {'Strike':>6}  {'P(OTM)':>7}  {'Dist':>5}  {'':>3}",
    ]

    for strike, stats in sorted(pt["probabilities"].items(), reverse=True):
        p = stats["p_otm"]
        mark = "✓" if p >= m["min_p_otm_floor"] else "✗" if p < m["min_p_otm_floor"] - 0.03 else "~"
        lines.append(
            f"  {strike:>6.0f}  {p*100:>6.1f}%  ${stats['distance_from_open']:>4.0f}  {mark}"
        )

    lines.append("-" * 60)
    lines.append("  RECOMMENDED (meet floor)")
    if report["recommendations"]:
        for r in report["recommendations"][:8]:
            lines.append(f"    {r['strike']:.0f}  P(OTM)={r['p_otm_pct']}%  ${r['distance']} below open  {r['verdict']}")
    else:
        lines.append("    None today — widen range or skip.")
    lines.append("=" * 60)
    return "\n".join(lines)
