"""Gamma exposure (GEX) levels from an options chain."""
from __future__ import annotations

from typing import Optional


def calculate_gex(chain: dict, spot_price: Optional[float] = None) -> dict:
    """
    Compute dealer-style gamma exposure by strike.

    Convention (SpotGamma-style):
      - Calls:  +gamma * OI * 100 * spot
      - Puts:   -gamma * OI * 100 * spot

    Positive net GEX tends to dampen moves (dealers hedge against price);
    negative net GEX can amplify moves.
    """
    spot = float(spot_price or chain.get("spot_price") or 0.0)
    if spot <= 0:
        raise ValueError("Valid spot_price is required for GEX calculation.")

    by_strike: dict[float, dict] = {}
    total_gex = 0.0

    for strike, row in chain.get("calls", {}).items():
        oi = row.get("open_interest", 0)
        gamma = row.get("gamma", 0.0) or 0.0
        gex = gamma * oi * 100 * spot
        total_gex += gex
        by_strike.setdefault(strike, {"call_gex": 0.0, "put_gex": 0.0, "net_gex": 0.0})
        by_strike[strike]["call_gex"] += gex
        by_strike[strike]["net_gex"] += gex

    for strike, row in chain.get("puts", {}).items():
        oi = row.get("open_interest", 0)
        gamma = row.get("gamma", 0.0) or 0.0
        gex = -gamma * oi * 100 * spot
        total_gex += gex
        by_strike.setdefault(strike, {"call_gex": 0.0, "put_gex": 0.0, "net_gex": 0.0})
        by_strike[strike]["put_gex"] += gex
        by_strike[strike]["net_gex"] += gex

    sorted_strikes = sorted(by_strike.keys())
    cumulative = 0.0
    cumulative_curve = []
    zero_gamma_level = None
    for strike in sorted_strikes:
        cumulative += by_strike[strike]["net_gex"]
        cumulative_curve.append({"strike": strike, "cumulative_gex": cumulative})
        if zero_gamma_level is None and len(cumulative_curve) > 1:
            prev = cumulative_curve[-2]
            if prev["cumulative_gex"] == 0:
                zero_gamma_level = prev["strike"]
            elif (prev["cumulative_gex"] < 0 < cumulative) or (prev["cumulative_gex"] > 0 > cumulative):
                zero_gamma_level = strike

    major_levels = sorted(
        [{"strike": s, **by_strike[s]} for s in sorted_strikes],
        key=lambda x: abs(x["net_gex"]),
        reverse=True,
    )[:5]

    return {
        "total_gex": round(total_gex, 2),
        "by_strike": {k: {kk: round(vv, 2) for kk, vv in v.items()} for k, v in by_strike.items()},
        "zero_gamma_level": zero_gamma_level,
        "major_levels": major_levels,
        "cumulative_curve": cumulative_curve,
        "spot_price": spot,
        "expiration": chain.get("expiration"),
    }


def summarize_gex(gex: dict) -> str:
    total = gex.get("total_gex", 0.0)
    regime = "positive (vol suppressive)" if total > 0 else "negative (vol amplifying)"
    zgl = gex.get("zero_gamma_level")
    zgl_text = f", zero-gamma ~{zgl:.0f}" if zgl else ""
    return f"Net GEX {total:,.0f} — {regime}{zgl_text}"
