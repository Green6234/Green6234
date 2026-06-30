# Pre-Market Options Analysis

SPY strike probability and cash-secured put recommendation engine for pre-market options analysis.

## Module: `spy_range_probability.py`

Builds a historical reach-probability heatmap for SPY strikes, combines it with the options market's implied move (IV-based), applies a macro regime filter, and outputs tiered CSP strike recommendations.

Designed to plug into a broader pre-market options dashboard alongside max pain / GEX calculations.

## Install

```bash
cd premarket-options
pip install -r requirements.txt
```

## Usage

```python
from spy_range_probability import generate_premarket_report, fetch_live_inputs

inputs = fetch_live_inputs()
report = generate_premarket_report(inputs)
```

Standalone CLI test:

```bash
python spy_range_probability.py
```

## Report outputs

- **Regime filter** — 200 SMA + VIX macro gate for CSP eligibility
- **Implied move** — IV-based 1SD/2SD expected range
- **ATR bands** — Fractional ATR levels from today's open
- **Probability map** — Historical reach probability per $1 strike (VIX-conditional by default)
- **Strike recommendations** — Aggressive / moderate / conservative CSP tiers
- **Technical levels** — S/R zones, supply/demand zones, trendline projections

## Optional inputs

Pass these into the `inputs` dict for richer filtering:

| Key | Description |
|-----|-------------|
| `chain_liquidity` | Live options chain OI/volume for illiquid-strike filter |
| `max_pain` | Max pain strike from options chain module |
| `gex_levels` | Gamma exposure levels from GEX module |
