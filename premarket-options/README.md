# Pre-Market Options Analysis

SPY strike probability, max pain, GEX, and cash-secured put recommendations — with a Streamlit dashboard.

## Install

```bash
cd premarket-options
pip install -r requirements.txt
```

## Alpaca setup

Alpaca works for **SPY historical bars, live quotes, and options chain data** (greeks, quotes, open interest). VIX is still pulled from yfinance because Alpaca does not carry the VIX index.

1. Copy `.env.example` to `.env`
2. Add your Alpaca **API Key ID** and **Secret Key** from the [Alpaca dashboard](https://app.alpaca.markets/paper/dashboard/overview)
3. Paper endpoint (default): `https://paper-api.alpaca.markets/v2`

```bash
cp .env.example .env
# Edit .env — you need BOTH keys, not just the Key ID
```

**Never commit `.env` or paste keys into chat.** If a key was exposed, regenerate it in Alpaca.

## Run the dashboard

```bash
streamlit run dashboard.py
```

## CLI (probability module only)

```bash
python spy_range_probability.py          # yfinance fallback
python -c "from pipeline import build_premarket_analysis; ..."  # full pipeline
```

## Architecture

| Module | Role |
|--------|------|
| `spy_range_probability.py` | Reach-probability heatmap, IV/ATR bands, regime filter, CSP tiers, technical levels |
| `alpaca_data.py` | Alpaca SPY bars/quotes + options chain (OI + greeks) |
| `max_pain.py` | Max pain strike from chain OI |
| `gex.py` | Gamma exposure by strike + zero-gamma level |
| `pipeline.py` | Wires all modules into one report |
| `dashboard.py` | Streamlit UI |

## Data flow

```
Alpaca (SPY bars, quotes, options chain)
    + yfinance (VIX only)
        → pipeline.build_premarket_analysis()
            → max_pain + gex + generate_premarket_report()
                → Streamlit dashboard
```

## Options data notes

- **Open interest** comes from Alpaca's contract endpoint (1-day OCC lag — industry standard)
- **Greeks / IV / quotes** come from the option chain snapshot endpoint
- Requires an Alpaca account with **options market data** access for full chain snapshots

## yfinance fallback

Set data source to `yfinance` in the dashboard sidebar to run probability + technical analysis without Alpaca options data (no max pain / GEX).
