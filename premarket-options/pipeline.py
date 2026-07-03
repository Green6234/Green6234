"""End-to-end pre-market report pipeline."""
from __future__ import annotations

from datetime import date
from typing import Literal, Optional

from alpaca_data import apply_chain_to_inputs, fetch_live_inputs_alpaca, fetch_options_chain
from gex import calculate_gex
from max_pain import calculate_max_pain
from spy_range_probability import fetch_live_inputs, generate_premarket_report


def build_premarket_analysis(
    ticker: str = "SPY",
    data_source: Literal["alpaca", "yfinance"] = "alpaca",
    expiration: Optional[date] = None,
    strike_window: int = 25,
    strike_range: int = 15,
    dte: int = 0,
    use_vix_conditional: bool = True,
) -> dict:
    """
    Fetch data, compute max pain / GEX, and generate the full probability report.
    """
    if data_source == "alpaca":
        inputs = fetch_live_inputs_alpaca(ticker=ticker)
        chain = fetch_options_chain(
            underlying=ticker,
            spot_price=inputs["spy_current_price"],
            strike_window=strike_window,
            expiration=expiration,
        )
        inputs = apply_chain_to_inputs(inputs, chain)
    else:
        inputs = fetch_live_inputs(ticker=ticker)
        chain = None

    max_pain_result = calculate_max_pain(chain) if chain else None
    gex_result = calculate_gex(chain, inputs["spy_current_price"]) if chain else None

    if max_pain_result:
        inputs["max_pain"] = max_pain_result["max_pain_strike"]
    if gex_result:
        inputs["gex_levels"] = gex_result

    report = generate_premarket_report(
        inputs,
        strike_range=strike_range,
        dte=dte,
        use_vix_conditional=use_vix_conditional,
    )

    return {
        "report": report,
        "inputs": inputs,
        "chain": chain,
        "max_pain": max_pain_result,
        "gex": gex_result,
        "data_source": data_source,
    }
