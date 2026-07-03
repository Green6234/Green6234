"""Max pain calculation from an options chain with open interest."""
from __future__ import annotations

from typing import Optional


def calculate_max_pain(
    chain: dict,
    strike_step: float = 1.0,
) -> dict:
    """
    Compute the max-pain strike for the given expiration.

    Max pain is the strike price that minimizes total intrinsic value paid
    to all option holders at expiration (standard OCC end-of-day OI method).
    """
    calls = chain.get("calls", {})
    puts = chain.get("puts", {})
    if not calls and not puts:
        raise ValueError("Options chain is empty; cannot compute max pain.")

    all_strikes = sorted(set(calls.keys()) | set(puts.keys()))
    lo, hi = min(all_strikes), max(all_strikes)
    candidates = []
    price = lo
    while price <= hi + strike_step:
        candidates.append(round(price, 2))
        price += strike_step

    best_strike = None
    best_pain = None
    pain_by_strike: dict[float, float] = {}

    for candidate in candidates:
        total_pain = 0.0
        for strike, row in calls.items():
            oi = row.get("open_interest", 0)
            if candidate > strike:
                total_pain += (candidate - strike) * oi * 100
        for strike, row in puts.items():
            oi = row.get("open_interest", 0)
            if candidate < strike:
                total_pain += (strike - candidate) * oi * 100
        pain_by_strike[candidate] = total_pain
        if best_pain is None or total_pain < best_pain:
            best_pain = total_pain
            best_strike = candidate

    spot = chain.get("spot_price")
    distance = round(spot - best_strike, 2) if spot is not None and best_strike is not None else None

    return {
        "max_pain_strike": best_strike,
        "max_pain_value": best_pain,
        "spot_price": spot,
        "distance_from_spot": distance,
        "expiration": chain.get("expiration"),
        "pain_by_strike": pain_by_strike,
        "total_call_oi": sum(r.get("open_interest", 0) for r in calls.values()),
        "total_put_oi": sum(r.get("open_interest", 0) for r in puts.values()),
    }


def summarize_max_pain(max_pain: dict) -> str:
    strike = max_pain.get("max_pain_strike")
    dist = max_pain.get("distance_from_spot")
    if strike is None:
        return "Max pain unavailable"
    direction = "above" if dist and dist > 0 else "below" if dist and dist < 0 else "at"
    return f"Max pain {strike:.0f} ({abs(dist or 0):.2f} {direction} spot)"
