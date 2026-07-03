"""
spy_range_probability.py  v3
Pre-Market SPY Strike Probability Module
==========================================
Builds a historical reach-probability heatmap for SPY strikes, combines it
with the options market's implied move (IV-based), applies a macro regime
filter, and outputs tiered cash-secured-put strike recommendations with a
single per-strike conviction score.

v3 refinements:
  - Conviction score (0-100) combining historical safety, technical zone
    confluence, liquidity, and gap direction
  - Prior session high/low/close anchoring in probability map
  - Gap detection + threshold adjustment
  - 0DTE mode flag (tightens safety thresholds, adjusts expected move calc)
  - Fixed fetch_live_inputs to use second-to-last bar for prev session data

Dependencies:
    pip install yfinance pandas numpy scipy
Usage:
    from spy_range_probability import generate_premarket_report, fetch_live_inputs
    inputs = fetch_live_inputs()
    report = generate_premarket_report(inputs)
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


# --------------------------------------------------------------------------
# Data fetching
# --------------------------------------------------------------------------
def fetch_live_inputs(
    ticker: str = "SPY",
    lookback_days: int = 504,
    vix_ticker: str = "^VIX",
) -> dict:
    """
    Pulls live/recent data via yfinance. Replace or extend with your
    broker API / options chain feed as needed.

    FIXED v3: uses iloc[-2] for the prior completed session so that a
    partial intraday bar doesn't corrupt prev_high/prev_low/prev_close.
    """
    if yf is None:
        raise ImportError("yfinance required: pip install yfinance")

    spy = yf.Ticker(ticker)
    hist = spy.history(period=f"{lookback_days}d", interval="1d")
    hist = hist.rename(columns=str.title)
    if hist.empty or len(hist) < 30:
        raise ValueError("Insufficient historical data for SPY.")

    # Prior completed session (second-to-last bar, not last)
    prev_idx = -2 if len(hist) >= 2 else -1
    prev_row = hist.iloc[prev_idx]
    prev_close = float(prev_row["Close"])
    prev_high = float(prev_row["High"])
    prev_low = float(prev_row["Low"])

    atr_14 = compute_atr(hist, period=14)
    sma_200 = (
        float(hist["Close"].tail(200).mean())
        if len(hist) >= 200
        else float(hist["Close"].mean())
    )

    intraday = spy.history(period="1d", interval="1m")
    if not intraday.empty:
        spy_open = float(intraday.iloc[0]["Open"])
        spy_current_price = float(intraday.iloc[-1]["Close"])
    else:
        spy_open = prev_close
        spy_current_price = prev_close

    vix_hist_df = yf.Ticker(vix_ticker).history(period=f"{lookback_days}d", interval="1d")
    vix = float(vix_hist_df["Close"].iloc[-1]) if not vix_hist_df.empty else 18.0
    iv_30d = vix / 100.0

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
    high_low = df["High"] - df["Low"]
    high_close = (df["High"] - df["Close"].shift()).abs()
    low_close = (df["Low"] - df["Close"].shift()).abs()
    tr = pd.concat([high_low, high_close, low_close], axis=1).max(axis=1)
    return float(tr.rolling(period).mean().iloc[-1])


# --------------------------------------------------------------------------
# Step 1 — Gap detection
# --------------------------------------------------------------------------
def detect_gap(spy_open: float, prev_close: float) -> dict:
    """
    Classifies today's open relative to the prior close.
    gap_pct > 0  →  gap-up   (bullish, puts safer)
    gap_pct < 0  →  gap-down (bearish, puts riskier, tighten thresholds)
    """
    gap_pct = (spy_open - prev_close) / prev_close
    if gap_pct > 0.003:
        direction = "GAP_UP"
    elif gap_pct < -0.003:
        direction = "GAP_DOWN"
    else:
        direction = "FLAT"

    threshold_adjustment = 0.0
    if direction == "GAP_DOWN":
        threshold_adjustment = min(0.05, abs(gap_pct) * 5)
    elif direction == "GAP_UP":
        threshold_adjustment = max(-0.03, -abs(gap_pct) * 3)

    return {
        "gap_pct": round(gap_pct * 100, 3),
        "direction": direction,
        "threshold_adjustment": round(threshold_adjustment, 4),
    }


# --------------------------------------------------------------------------
# Step 2 — Implied expected move
# --------------------------------------------------------------------------
def expected_move_bounds(spy_price: float, iv_30d: float, dte: int = 1) -> dict:
    """
    IV-implied move envelope.
    dte=0 (0DTE) uses a 0.8x intraday scalar for remaining time value.
    """
    if dte == 0:
        time_scalar = 0.8
    else:
        time_scalar = math.sqrt(dte)

    daily_iv = iv_30d / math.sqrt(252)
    one_sd_move = spy_price * daily_iv * time_scalar
    return {
        "one_sd_move_dollars": round(one_sd_move, 2),
        "upper_1sd": round(spy_price + one_sd_move, 2),
        "lower_1sd": round(spy_price - one_sd_move, 2),
        "upper_2sd": round(spy_price + 2 * one_sd_move, 2),
        "lower_2sd": round(spy_price - 2 * one_sd_move, 2),
        "dte": dte,
    }


# --------------------------------------------------------------------------
# Step 3 — ATR bands
# --------------------------------------------------------------------------
def atr_range_bands(spy_open: float, atr_14: float) -> dict:
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
# Step 4 — Reach-probability heatmap  (unconditional + VIX-conditional)
# --------------------------------------------------------------------------
def _compute_prob_map(df: pd.DataFrame, spy_open: float, strike_range: int) -> dict:
    df = df.copy()
    df["open_to_low"] = df["Low"] - df["Open"]
    df["open_to_high"] = df["High"] - df["Open"]
    prob_map = {}
    for offset in range(-strike_range, strike_range + 1):
        strike = round(spy_open + offset, 0)
        if offset < 0:
            pct = float((df["open_to_low"] <= offset).mean())
        elif offset > 0:
            pct = float((df["open_to_high"] >= offset).mean())
        else:
            pct = 1.0
        prob_map[strike] = round(pct, 4)
    return prob_map


def build_reach_probability_map(
    historical_ohlc: pd.DataFrame,
    spy_open: float,
    strike_range: int = 15,
) -> dict:
    if historical_ohlc.empty:
        raise ValueError("historical_ohlc is empty.")
    return _compute_prob_map(historical_ohlc, spy_open, strike_range)


def build_vix_conditional_probability_map(
    historical_ohlc: pd.DataFrame,
    spy_open: float,
    current_vix: float,
    vix_history: pd.Series,
    strike_range: int = 15,
    vix_band_width: float = 4.0,
    min_sample_size: int = 40,
) -> dict:
    if len(vix_history) != len(historical_ohlc):
        raise ValueError("vix_history must be same length as historical_ohlc.")

    df = historical_ohlc.reset_index(drop=True)
    vix_series = pd.Series(vix_history).reset_index(drop=True)
    mask = (vix_series >= current_vix - vix_band_width) & (
        vix_series <= current_vix + vix_band_width
    )
    n_matched = int(mask.sum())
    fallback = n_matched < min_sample_size
    source_df = df if fallback else df[mask.values]
    prob_map = _compute_prob_map(source_df, spy_open, strike_range)
    return {
        "probability_map": prob_map,
        "vix_band": (
            round(current_vix - vix_band_width, 1),
            round(current_vix + vix_band_width, 1),
        ),
        "matched_sample_size": n_matched,
        "total_sample_size": len(df),
        "used_fallback_to_full_history": fallback,
    }


# --------------------------------------------------------------------------
# Step 5 — Prior-session anchor levels
# --------------------------------------------------------------------------
def prior_session_anchors(
    prev_high: float,
    prev_low: float,
    prev_close: float,
    spy_open: float,
) -> dict:
    mid = round((prev_high + prev_low) / 2, 2)
    return {
        "prev_high": round(prev_high, 2),
        "prev_low": round(prev_low, 2),
        "prev_close": round(prev_close, 2),
        "prev_mid": mid,
        "gap_from_prev_close_pct": round((spy_open - prev_close) / prev_close * 100, 3),
    }


# --------------------------------------------------------------------------
# Step 6 — Regime filter
# --------------------------------------------------------------------------
def regime_check(spy_price: float, sma_200: float, vix: float) -> dict:
    bull = spy_price > sma_200
    low_vol = vix < 20
    elev_vol = 20 <= vix <= 28
    high_vol = vix > 28
    if bull and low_vol:
        return {"regime": "BULL_LOW_VOL", "csp_ok": True, "note": "Favorable — full size."}
    if bull and elev_vol:
        return {
            "regime": "BULL_ELEVATED_VOL",
            "csp_ok": True,
            "note": "Proceed — wider strikes, higher premium.",
        }
    if bull and high_vol:
        return {
            "regime": "BULL_HIGH_VOL",
            "csp_ok": False,
            "note": "Caution — tail risk elevated, reduce size.",
        }
    return {
        "regime": "BEAR_OR_BELOW_200",
        "csp_ok": False,
        "note": "Trend filter failed — no new CSP entries.",
    }


# --------------------------------------------------------------------------
# Step 7 — Technical levels (S/R zones, supply/demand, trendlines)
# --------------------------------------------------------------------------
def find_swing_points(df: pd.DataFrame, lookback: int = 5) -> dict:
    df = df.copy().reset_index(drop=True)
    highs = df["High"]
    lows = df["Low"]
    n = len(df)
    swing_highs, swing_lows = [], []
    for i in range(lookback, n - lookback):
        win_h = highs[i - lookback : i + lookback + 1]
        win_l = lows[i - lookback : i + lookback + 1]
        if highs[i] == win_h.max():
            swing_highs.append((i, float(highs[i])))
        if lows[i] == win_l.min():
            swing_lows.append((i, float(lows[i])))
    return {"swing_highs": swing_highs, "swing_lows": swing_lows}


def cluster_levels(points: list, cluster_width_pct: float = 0.003) -> list:
    if not points:
        return []
    prices = sorted([p for _, p in points])
    clusters, current = [], [prices[0]]
    for price in prices[1:]:
        if abs(price - current[-1]) / current[-1] <= cluster_width_pct:
            current.append(price)
        else:
            clusters.append(current)
            current = [price]
    clusters.append(current)
    return sorted(
        [
            {
                "level": round(sum(c) / len(c), 2),
                "touch_count": len(c),
                "range": (round(min(c), 2), round(max(c), 2)),
            }
            for c in clusters
        ],
        key=lambda z: z["touch_count"],
        reverse=True,
    )


def identify_support_resistance(
    historical_ohlc: pd.DataFrame,
    current_price: float,
    lookback: int = 5,
    cluster_width_pct: float = 0.003,
    max_zones: int = 5,
) -> dict:
    swings = find_swing_points(historical_ohlc, lookback)
    all_zones = cluster_levels(swings["swing_highs"], cluster_width_pct) + cluster_levels(
        swings["swing_lows"], cluster_width_pct
    )
    support = sorted(
        [z for z in all_zones if z["level"] < current_price],
        key=lambda z: z["level"],
        reverse=True,
    )[:max_zones]
    resistance = sorted(
        [z for z in all_zones if z["level"] > current_price],
        key=lambda z: z["level"],
    )[:max_zones]
    return {"support": support, "resistance": resistance}


def identify_supply_demand_zones(
    historical_ohlc: pd.DataFrame,
    current_price: float,
    move_threshold_pct: float = 0.015,
    max_zones: int = 5,
) -> dict:
    df = historical_ohlc.copy().reset_index(drop=True)
    zones = []
    for i in range(1, len(df) - 1):
        base_mid = (df.loc[i, "Open"] + df.loc[i, "Close"]) / 2
        move_pct = (df.loc[i + 1, "Close"] - base_mid) / base_mid
        zone_type = (
            "demand"
            if move_pct >= move_threshold_pct
            else "supply"
            if move_pct <= -move_threshold_pct
            else None
        )
        if zone_type:
            zones.append(
                {
                    "type": zone_type,
                    "zone_low": round(float(df.loc[i, "Low"]), 2),
                    "zone_high": round(float(df.loc[i, "High"]), 2),
                    "bar_index": i,
                }
            )
    demand = sorted(
        [z for z in zones if z["type"] == "demand" and z["zone_high"] < current_price],
        key=lambda z: z["zone_high"],
        reverse=True,
    )[:max_zones]
    supply = sorted(
        [z for z in zones if z["type"] == "supply" and z["zone_low"] > current_price],
        key=lambda z: z["zone_low"],
    )[:max_zones]
    return {"demand_zones": demand, "supply_zones": supply}


def fit_trendlines(
    historical_ohlc: pd.DataFrame,
    lookback_bars: int = 60,
    lookback_pivots: int = 5,
) -> dict:
    df = historical_ohlc.copy().reset_index(drop=True).tail(lookback_bars).reset_index(drop=True)
    swings = find_swing_points(df, lookback_pivots)
    last_i = len(df) - 1

    def _fit(points):
        if len(points) < 2:
            return None
        xs, ys = np.array([p[0] for p in points]), np.array([p[1] for p in points])
        slope, intercept = np.polyfit(xs, ys, 1)
        return {"slope": float(slope), "intercept": float(intercept)}

    res_line = _fit(swings["swing_highs"])
    sup_line = _fit(swings["swing_lows"])
    return {
        "resistance_trendline": res_line,
        "support_trendline": sup_line,
        "projected_resistance_today": (
            round(res_line["slope"] * (last_i + 1) + res_line["intercept"], 2) if res_line else None
        ),
        "projected_support_today": (
            round(sup_line["slope"] * (last_i + 1) + sup_line["intercept"], 2) if sup_line else None
        ),
    }


def build_technical_levels_report(df: pd.DataFrame, current_price: float) -> dict:
    return {
        "support_resistance": identify_support_resistance(df, current_price),
        "supply_demand": identify_supply_demand_zones(df, current_price),
        "trendlines": fit_trendlines(df),
    }


# --------------------------------------------------------------------------
# Step 8 — Conviction score
# --------------------------------------------------------------------------
def compute_conviction_score(
    strike: float,
    prob_safe: float,
    chain_liquidity: Optional[dict],
    technical_levels: dict,
    gap: dict,
    anchors: dict,
    em_bounds: dict,
) -> dict:
    score = 0.0
    breakdown = {}

    hist_pts = prob_safe * 35
    score += hist_pts
    breakdown["historical_safety"] = round(hist_pts, 1)

    tech_pts = 0.0
    sr_support = technical_levels["support_resistance"]["support"]
    sd_demand = technical_levels["supply_demand"]["demand_zones"]
    tl = technical_levels["trendlines"]

    for z in sr_support:
        if abs(z["level"] - strike) <= 1.0:
            tech_pts += min(12.0, z["touch_count"] * 2.0)
            break
    for z in sd_demand:
        if z["zone_low"] <= strike <= z["zone_high"] + 1.0:
            tech_pts += 8.0
            break
    proj_sup = tl.get("projected_support_today")
    if proj_sup and abs(proj_sup - strike) <= 1.5:
        tech_pts += 5.0
    score += min(25.0, tech_pts)
    breakdown["technical_confluence"] = round(min(25.0, tech_pts), 1)

    liq_pts = 0.0
    if chain_liquidity and strike in chain_liquidity:
        liq = chain_liquidity[strike]
        oi = liq.get("open_interest", 0)
        vol = liq.get("volume", 0)
        liq_pts += min(10.0, (oi / 10000) * 10)
        liq_pts += min(10.0, (vol / 1000) * 10)
    else:
        liq_pts = 5.0
    score += liq_pts
    breakdown["liquidity"] = round(liq_pts, 1)

    lower_1sd = em_bounds["lower_1sd"]
    if strike < lower_1sd:
        dist_pct = (lower_1sd - strike) / lower_1sd
        dist_pts = min(10.0, dist_pct * 200)
    else:
        dist_pts = 0.0
    score += dist_pts
    breakdown["beyond_implied_move"] = round(dist_pts, 1)

    gap_pts = 0.0
    if gap["direction"] == "GAP_UP":
        gap_pts = 5.0
    elif gap["direction"] == "FLAT":
        gap_pts = 2.5
    score += gap_pts
    breakdown["gap_alignment"] = round(gap_pts, 1)

    prev_low = anchors["prev_low"]
    if abs(strike - prev_low) <= 1.0:
        anc_pts = 5.0
    elif abs(strike - prev_low) <= 3.0:
        anc_pts = 2.5
    else:
        anc_pts = 0.0
    score += anc_pts
    breakdown["anchor_proximity"] = round(anc_pts, 1)

    final_score = round(min(100.0, score), 1)
    return {
        "score": final_score,
        "breakdown": breakdown,
        "grade": "A" if final_score >= 75 else "B" if final_score >= 55 else "C" if final_score >= 35 else "D",
    }


# --------------------------------------------------------------------------
# Step 9 — Strike recommendation engine (with conviction scores)
# --------------------------------------------------------------------------
def recommend_put_strikes(
    probability_map: dict,
    em_bounds: dict,
    spy_open: float,
    gap: dict,
    anchors: dict,
    technical_levels: dict,
    chain_liquidity: Optional[dict] = None,
    min_open_interest: int = 500,
    min_volume: int = 100,
    dte: int = 0,
) -> dict:
    tier_offsets = (0.03, 0.0, 0.0) if dte == 0 else (0.0, 0.0, 0.0)
    gap_adj = gap["threshold_adjustment"]
    t_aggressive = 0.80 + tier_offsets[0] + max(0, gap_adj)

    recs = {"A_grade": [], "B_grade": [], "C_grade": []}
    excluded_illiquid = []
    lower_1sd = em_bounds["lower_1sd"]

    for strike, prob_reached in probability_map.items():
        if strike >= spy_open:
            continue
        if strike >= lower_1sd:
            continue
        if chain_liquidity is not None:
            liq = chain_liquidity.get(strike)
            if liq is None:
                excluded_illiquid.append((strike, "no chain data"))
                continue
            if liq.get("open_interest", 0) < min_open_interest or liq.get("volume", 0) < min_volume:
                excluded_illiquid.append(
                    (strike, f"OI={liq.get('open_interest', 0)}, Vol={liq.get('volume', 0)}")
                )
                continue

        prob_safe = round(1 - prob_reached, 4)
        if prob_safe < t_aggressive:
            continue

        conviction = compute_conviction_score(
            strike, prob_safe, chain_liquidity, technical_levels, gap, anchors, em_bounds
        )
        entry = {
            "strike": strike,
            "prob_safe": prob_safe,
            "conviction": conviction,
            "open_interest": (
                chain_liquidity[strike].get("open_interest")
                if chain_liquidity and strike in chain_liquidity
                else None
            ),
            "volume": (
                chain_liquidity[strike].get("volume")
                if chain_liquidity and strike in chain_liquidity
                else None
            ),
            "bid": (
                chain_liquidity[strike].get("bid")
                if chain_liquidity and strike in chain_liquidity
                else None
            ),
            "ask": (
                chain_liquidity[strike].get("ask")
                if chain_liquidity and strike in chain_liquidity
                else None
            ),
        }
        grade = conviction["grade"]
        if grade == "A":
            recs["A_grade"].append(entry)
        elif grade == "B":
            recs["B_grade"].append(entry)
        else:
            recs["C_grade"].append(entry)

    for tier in recs:
        recs[tier].sort(key=lambda x: x["conviction"]["score"], reverse=True)
    return {"tiers": recs, "excluded_illiquid": excluded_illiquid}


# --------------------------------------------------------------------------
# Master report generator
# --------------------------------------------------------------------------
def generate_premarket_report(
    inputs: dict,
    strike_range: int = 15,
    dte: int = 0,
    use_vix_conditional: bool = True,
    vix_band_width: float = 4.0,
) -> dict:
    required = [
        "spy_open",
        "spy_current_price",
        "spy_prev_close",
        "spy_prev_high",
        "spy_prev_low",
        "iv_30d",
        "vix",
        "atr_14",
        "sma_200",
        "historical_ohlc",
    ]
    missing = [k for k in required if k not in inputs]
    if missing:
        raise KeyError(f"Missing required input(s): {missing}")

    gap = detect_gap(inputs["spy_open"], inputs["spy_prev_close"])
    anchors = prior_session_anchors(
        inputs["spy_prev_high"],
        inputs["spy_prev_low"],
        inputs["spy_prev_close"],
        inputs["spy_open"],
    )
    em = expected_move_bounds(inputs["spy_current_price"], inputs["iv_30d"], dte=dte)
    bands = atr_range_bands(inputs["spy_open"], inputs["atr_14"])

    vix_meta = None
    if use_vix_conditional and inputs.get("vix_history") is not None:
        vr = build_vix_conditional_probability_map(
            inputs["historical_ohlc"],
            inputs["spy_open"],
            inputs["vix"],
            inputs["vix_history"],
            strike_range,
            vix_band_width,
        )
        prob_map = vr["probability_map"]
        vix_meta = {
            k: vr[k]
            for k in (
                "vix_band",
                "matched_sample_size",
                "total_sample_size",
                "used_fallback_to_full_history",
            )
        }
    else:
        prob_map = build_reach_probability_map(
            inputs["historical_ohlc"], inputs["spy_open"], strike_range
        )

    regime = regime_check(inputs["spy_current_price"], inputs["sma_200"], inputs["vix"])
    technicals = build_technical_levels_report(
        inputs["historical_ohlc"], inputs["spy_current_price"]
    )
    strikes = recommend_put_strikes(
        prob_map,
        em,
        inputs["spy_open"],
        gap,
        anchors,
        technicals,
        chain_liquidity=inputs.get("chain_liquidity"),
        dte=dte,
    )

    return {
        "regime": regime,
        "gap": gap,
        "anchors": anchors,
        "implied_move": em,
        "atr_bands": bands,
        "probability_map": prob_map,
        "vix_conditional_meta": vix_meta,
        "recommendations": strikes["tiers"],
        "excluded_illiquid": strikes["excluded_illiquid"],
        "technical_levels": technicals,
        "max_pain": inputs.get("max_pain"),
        "gex_levels": inputs.get("gex_levels"),
        "meta": {
            "spy_open": inputs["spy_open"],
            "spy_current_price": inputs["spy_current_price"],
            "spy_prev_close": inputs["spy_prev_close"],
            "spy_prev_high": inputs["spy_prev_high"],
            "spy_prev_low": inputs["spy_prev_low"],
            "vix": inputs["vix"],
            "atr_14": inputs["atr_14"],
            "dte": dte,
        },
    }


# --------------------------------------------------------------------------
# Console report printer
# --------------------------------------------------------------------------
def print_report(report: dict) -> None:
    m = report["meta"]
    regime = report["regime"]
    em = report["implied_move"]
    gap = report["gap"]
    anc = report["anchors"]
    print("=" * 65)
    print("  SPY PRE-MARKET RANGE PROBABILITY REPORT  v3")
    print("=" * 65)
    print(
        f"  Open: {m['spy_open']:.2f}  |  Current: {m['spy_current_price']:.2f}  |  "
        f"VIX: {m['vix']:.2f}  |  DTE: {m['dte']}"
    )
    print(f"  Regime: {regime['regime']}  |  CSP OK: {regime['csp_ok']}")
    print(f"  {regime['note']}")
    print(
        f"  Gap: {gap['direction']}  {gap['gap_pct']:+.2f}%  |  "
        f"Threshold adj: {gap['threshold_adjustment']:+.3f}"
    )
    print(
        f"  Prev session:  High {anc['prev_high']}  |  Low {anc['prev_low']}  |  "
        f"Close {anc['prev_close']}"
    )
    if report.get("vix_conditional_meta"):
        vm = report["vix_conditional_meta"]
        flag = " [FALLBACK]" if vm["used_fallback_to_full_history"] else ""
        print(
            f"  VIX band {vm['vix_band']}: {vm['matched_sample_size']}/"
            f"{vm['total_sample_size']} matched days{flag}"
        )
    print("-" * 65)
    print(f"  Implied 1SD: ±${em['one_sd_move_dollars']}  [{em['lower_1sd']} – {em['upper_1sd']}]")
    print(f"  Implied 2SD:             [{em['lower_2sd']} – {em['upper_2sd']}]")
    print("-" * 65)
    print("  PUT STRIKE RECOMMENDATIONS  (sorted by conviction score)")
    any_found = False
    for tier_label in ["A_grade", "B_grade", "C_grade"]:
        entries = report["recommendations"][tier_label]
        if not entries:
            continue
        any_found = True
        print(f"\n  ── Grade {tier_label[0]} ──")
        for e in entries[:6]:
            cv = e["conviction"]
            liq = (
                f"  OI:{e['open_interest']}  Vol:{e['volume']}  Bid:{e['bid']}"
                if e["open_interest"] is not None
                else ""
            )
            print(
                f"    Strike {e['strike']:.0f}  |  Score: {cv['score']}/100  |  "
                f"Safety: {e['prob_safe']*100:.1f}%{liq}"
            )
            bd = cv["breakdown"]
            print(
                f"      Hist:{bd['historical_safety']}  Tech:{bd['technical_confluence']}  "
                f"Liq:{bd['liquidity']}  EM:{bd['beyond_implied_move']}  "
                f"Gap:{bd['gap_alignment']}  Anc:{bd['anchor_proximity']}"
            )
    if not any_found:
        print("\n  No strikes passed all filters today.")
    if report.get("excluded_illiquid"):
        print(f"\n  Excluded {len(report['excluded_illiquid'])} illiquid strike(s).")
    tech = report.get("technical_levels")
    if tech:
        print("-" * 65)
        print("  TECHNICAL LEVELS")
        print("  Support zones:")
        for z in tech["support_resistance"]["support"][:4]:
            print(f"    {z['level']}  ({z['touch_count']}x touches)")
        print("  Resistance zones:")
        for z in tech["support_resistance"]["resistance"][:4]:
            print(f"    {z['level']}  ({z['touch_count']}x touches)")
        tl = tech["trendlines"]
        print(f"  Trendline support projected today:    {tl['projected_support_today']}")
        print(f"  Trendline resistance projected today: {tl['projected_resistance_today']}")
    print("=" * 65)


if __name__ == "__main__":
    print("Fetching live SPY data...")
    live_inputs = fetch_live_inputs()
    report = generate_premarket_report(live_inputs, dte=0)
    print_report(report)
