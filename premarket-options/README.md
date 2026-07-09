# 1DTE Put OTM Probability

One question: **what's the historical probability SPY's next close finishes above your put strike?**

Filtered by VIX band (similar vol days). No Alpaca. No max pain. No GEX.

## Install

```bash
cd premarket-options
pip install -r requirements.txt
```

## Run (terminal)

```bash
python run.py
```

## Run (dashboard)

```bash
streamlit run dashboard.py
```

## How to read it

| Column | Meaning |
|--------|---------|
| **P(OTM)** | % of similar-VIX days where next close > strike |
| **Dist** | Dollars below today's open |
| **✓** | Meets your minimum P(OTM) floor |

**Trade when:** Regime = OK, pick strikes with ✓.

**1DTE** = you sell today, expiration is **next session close**.

## Mac quick start

Double-click `START.command` (right-click → Open if blocked).

## Settings (dashboard sidebar)

- **Min P(OTM) %** — default 85% for small account 1DTE
- **VIX band** — how tight to match today's VIX (default ±4)
