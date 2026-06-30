"""Streamlit dashboard for SPY pre-market options analysis."""
from __future__ import annotations

import os

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

from gex import summarize_gex
from max_pain import summarize_max_pain
from pipeline import build_premarket_analysis

st.set_page_config(
    page_title="SPY Pre-Market Options",
    page_icon="📊",
    layout="wide",
)

st.title("SPY Pre-Market Options Dashboard")
st.caption("Reach probability v3 · conviction scores · max pain · GEX · CSP recommendations")

with st.sidebar:
    st.header("Settings")
    data_source = st.selectbox("Data source", ["alpaca", "yfinance"], index=0)
    dte = st.selectbox("Expiry mode", [0, 1], index=0, format_func=lambda x: "0DTE" if x == 0 else "1 DTE")
    strike_range = st.slider("Probability strike range ($)", 5, 30, 15)
    strike_window = st.slider("Options chain window ($)", 10, 40, 25)
    use_vix_filter = st.checkbox("VIX-conditional probabilities", value=True)
    refresh = st.button("Refresh report", type="primary")

    st.divider()
    st.markdown("**Alpaca credentials**")
    st.markdown(
        "Create `premarket-options/.env` with:\n\n"
        "`ALPACA_API_KEY=...`\n\n"
        "`ALPACA_SECRET_KEY=...`"
    )
    if os.getenv("ALPACA_API_KEY") and os.getenv("ALPACA_SECRET_KEY"):
        st.success("Credentials detected")
    else:
        st.warning("No credentials in environment")

if refresh or (
    os.getenv("ALPACA_API_KEY")
    and os.getenv("ALPACA_SECRET_KEY")
    and "analysis" not in st.session_state
):
    with st.spinner("Fetching market data and building report..."):
        try:
            st.session_state["analysis"] = build_premarket_analysis(
                data_source=data_source,
                strike_range=strike_range,
                strike_window=strike_window,
                dte=dte,
                use_vix_conditional=use_vix_filter,
            )
            st.session_state["error"] = None
        except Exception as exc:
            st.session_state["error"] = str(exc)

if st.session_state.get("error"):
    st.error(st.session_state["error"])
    if data_source == "alpaca":
        st.info(
            "Alpaca requires **both** API Key ID and Secret Key in `.env`. "
            "Copy both from your [Alpaca dashboard](https://app.alpaca.markets/paper/dashboard/overview)."
        )
    st.stop()

analysis = st.session_state.get("analysis")
if not analysis:
    st.info("Click **Refresh report** in the sidebar to load data.")
    st.code(
        "cd premarket-options\n"
        "cp .env.example .env   # add your keys\n"
        "pip install -r requirements.txt\n"
        "streamlit run dashboard.py",
        language="bash",
    )
    st.stop()

report = analysis["report"]
meta = report["meta"]
regime = report["regime"]
gap = report.get("gap", {})
anchors = report.get("anchors", {})
chain = analysis.get("chain")
max_pain = analysis.get("max_pain")
gex = analysis.get("gex")

c1, c2, c3, c4, c5, c6, c7 = st.columns(7)
c1.metric("SPY Open", f"${meta['spy_open']:.2f}")
c2.metric("SPY Current", f"${meta['spy_current_price']:.2f}")
c3.metric("VIX", f"{meta['vix']:.2f}")
c4.metric("DTE", meta.get("dte", 0))
c5.metric("Gap", gap.get("direction", "—"), f"{gap.get('gap_pct', 0):+.2f}%")
c6.metric("CSP OK", "Yes" if regime["csp_ok"] else "No")
if max_pain:
    c7.metric("Max Pain", f"${max_pain['max_pain_strike']:.0f}")
else:
    c7.metric("Max Pain", "N/A")

st.write(regime["note"])
col_a, col_b = st.columns(2)
with col_a:
    st.caption(
        f"Prev session — High **{anchors.get('prev_high')}** · "
        f"Low **{anchors.get('prev_low')}** · Close **{anchors.get('prev_close')}**"
    )
with col_b:
    if max_pain:
        st.caption(summarize_max_pain(max_pain))
    if gex:
        st.caption(summarize_gex(gex))

tab_overview, tab_prob, tab_strikes, tab_maxpain, tab_gex, tab_technical = st.tabs(
    ["Overview", "Probability Map", "CSP Strikes", "Max Pain", "GEX", "Technical Levels"]
)

with tab_overview:
    em = report["implied_move"]
    bands = report["atr_bands"]
    o1, o2 = st.columns(2)
    with o1:
        st.subheader("Implied Move (IV)")
        st.write(
            f"1SD: ±${em['one_sd_move_dollars']} → "
            f"[{em['lower_1sd']} – {em['upper_1sd']}]"
        )
        st.write(f"2SD: [{em['lower_2sd']} – {em['upper_2sd']}]")
        if chain and chain.get("atm_iv"):
            st.write(f"ATM IV (Alpaca chain): {chain['atm_iv'] * 100:.1f}%")
    with o2:
        st.subheader("Gap & anchors")
        st.json({"gap": gap, "anchors": anchors})
        st.subheader("ATR Bands (from open)")
        st.json(bands)

    if report.get("vix_conditional_meta"):
        vm = report["vix_conditional_meta"]
        flag = " ⚠️ fallback to full history" if vm["used_fallback_to_full_history"] else ""
        st.info(
            f"VIX-conditional sample: {vm['matched_sample_size']}/{vm['total_sample_size']} days "
            f"in band {vm['vix_band']}{flag}"
        )

    if chain:
        st.subheader("Options chain snapshot")
        st.write(f"Expiration: **{chain['expiration']}** | Source: **{analysis['data_source']}**")

with tab_prob:
    prob_map = report["probability_map"]
    prob_df = pd.DataFrame(
        [{"strike": k, "reach_prob": v, "safety": 1 - v} for k, v in sorted(prob_map.items())]
    )
    fig = px.bar(
        prob_df,
        x="strike",
        y="reach_prob",
        title="Historical reach probability by strike (from open)",
        labels={"reach_prob": "P(reached)", "strike": "Strike ($)"},
    )
    fig.add_vline(x=meta["spy_open"], line_dash="dash", line_color="green", annotation_text="Open")
    if anchors.get("prev_low"):
        fig.add_vline(
            x=anchors["prev_low"],
            line_dash="dot",
            line_color="blue",
            annotation_text="Prev low",
        )
    if anchors.get("prev_high"):
        fig.add_vline(
            x=anchors["prev_high"],
            line_dash="dot",
            line_color="purple",
            annotation_text="Prev high",
        )
    if max_pain:
        fig.add_vline(
            x=max_pain["max_pain_strike"],
            line_dash="dot",
            line_color="orange",
            annotation_text="Max pain",
        )
    st.plotly_chart(fig, use_container_width=True)

with tab_strikes:
    st.subheader("Cash-secured put recommendations (conviction scored)")
    grade_labels = {"A_grade": "Grade A (≥75)", "B_grade": "Grade B (≥55)", "C_grade": "Grade C (≥35)"}
    for tier, label in grade_labels.items():
        entries = report["recommendations"].get(tier, [])
        st.markdown(f"**{label}**")
        if not entries:
            st.write("None passed filters")
            continue
        rows = []
        for e in entries:
            cv = e["conviction"]
            bd = cv["breakdown"]
            rows.append(
                {
                    "strike": e["strike"],
                    "conviction": cv["score"],
                    "grade": cv["grade"],
                    "safety_pct": round(e["prob_safe"] * 100, 1),
                    "historical": bd["historical_safety"],
                    "technical": bd["technical_confluence"],
                    "liquidity": bd["liquidity"],
                    "implied_move": bd["beyond_implied_move"],
                    "gap": bd["gap_alignment"],
                    "anchor": bd["anchor_proximity"],
                    "open_interest": e.get("open_interest"),
                    "volume": e.get("volume"),
                    "bid": e.get("bid"),
                    "ask": e.get("ask"),
                }
            )
        st.dataframe(pd.DataFrame(rows), use_container_width=True)

    excluded = report.get("excluded_illiquid") or []
    if excluded:
        st.warning(f"Excluded {len(excluded)} strikes for low liquidity.")

with tab_maxpain:
    if not max_pain:
        st.warning("Max pain requires Alpaca options chain data.")
    else:
        pain_df = pd.DataFrame(
            [{"strike": k, "total_pain": v} for k, v in sorted(max_pain["pain_by_strike"].items())]
        )
        fig_mp = px.line(
            pain_df,
            x="strike",
            y="total_pain",
            title=f"Max pain curve — expiration {max_pain['expiration']}",
        )
        fig_mp.add_vline(
            x=max_pain["max_pain_strike"],
            line_color="red",
            annotation_text=f"Max pain {max_pain['max_pain_strike']:.0f}",
        )
        fig_mp.add_vline(x=meta["spy_current_price"], line_dash="dash", annotation_text="Spot")
        if anchors.get("prev_low"):
            fig_mp.add_vline(x=anchors["prev_low"], line_dash="dot", annotation_text="Prev low")
        st.plotly_chart(fig_mp, use_container_width=True)
        st.write(
            f"Total call OI: **{max_pain['total_call_oi']:,}** | "
            f"Total put OI: **{max_pain['total_put_oi']:,}**"
        )

with tab_gex:
    if not gex:
        st.warning("GEX requires Alpaca options chain data.")
    else:
        gex_rows = [{"strike": s, **vals} for s, vals in sorted(gex["by_strike"].items())]
        gex_df = pd.DataFrame(gex_rows)
        fig_gex = go.Figure()
        fig_gex.add_bar(x=gex_df["strike"], y=gex_df["call_gex"], name="Call GEX", marker_color="green")
        fig_gex.add_bar(x=gex_df["strike"], y=gex_df["put_gex"], name="Put GEX", marker_color="red")
        fig_gex.update_layout(
            barmode="relative",
            title=f"Gamma exposure by strike (net: {gex['total_gex']:,.0f})",
            xaxis_title="Strike",
            yaxis_title="GEX",
        )
        if gex.get("zero_gamma_level"):
            fig_gex.add_vline(
                x=gex["zero_gamma_level"],
                line_dash="dot",
                annotation_text="Zero gamma",
            )
        st.plotly_chart(fig_gex, use_container_width=True)
        st.subheader("Major GEX levels")
        st.dataframe(pd.DataFrame(gex["major_levels"]), use_container_width=True)

with tab_technical:
    tech = report.get("technical_levels", {})
    sr = tech.get("support_resistance", {})
    sd = tech.get("supply_demand", {})
    tl = tech.get("trendlines", {})
    t1, t2 = st.columns(2)
    with t1:
        st.subheader("Support / Resistance")
        st.write("Support", sr.get("support", []))
        st.write("Resistance", sr.get("resistance", []))
    with t2:
        st.subheader("Supply / Demand")
        st.write("Demand zones", sd.get("demand_zones", []))
        st.write("Supply zones", sd.get("supply_zones", []))
    st.write(
        f"Trendline support today: **{tl.get('projected_support_today')}** | "
        f"Resistance: **{tl.get('projected_resistance_today')}**"
    )
