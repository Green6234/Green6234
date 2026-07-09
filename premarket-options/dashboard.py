"""Simple 1DTE put OTM probability dashboard."""
from __future__ import annotations

import pandas as pd
import plotly.express as px
import streamlit as st

from otm_probability import generate_report

st.set_page_config(page_title="1DTE Put OTM", layout="wide")
st.title("1DTE Put — P(Expire OTM)")
st.caption("Historical probability next close finishes above your put strike")

with st.sidebar:
    strike_range = st.slider("Strike range ($ below open)", 5, 25, 15)
    min_p_otm = st.slider("Min P(OTM) %", 75, 95, 85) / 100
    vix_band = st.slider("VIX band width", 2.0, 8.0, 4.0)
    refresh = st.button("Refresh", type="primary")

if refresh or "report" not in st.session_state:
    with st.spinner("Loading..."):
        try:
            st.session_state["report"] = generate_report(
                dte=1,
                strike_range=strike_range,
                min_p_otm=min_p_otm,
                vix_band_width=vix_band,
            )
            st.session_state["err"] = None
        except Exception as e:
            st.session_state["err"] = str(e)

if st.session_state.get("err"):
    st.error(st.session_state["err"])
    st.stop()

r = st.session_state["report"]
m = r["meta"]
gap = r["gap"]
regime = r["regime"]
pt = r["probability_table"]

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Open", f"${m['spy_open']:.2f}")
c2.metric("Current", f"${m['spy_current']:.2f}")
c3.metric("VIX", f"{m['vix']:.1f}")
c4.metric("Trade OK", "Yes" if regime["trade_ok"] else "No")
c5.metric("P(OTM) floor", f"{m['min_p_otm_floor']*100:.0f}%")

st.write(f"**{regime['note']}** · Gap: {gap['direction']} ({gap['gap_pct']:+.2f}%)")
st.caption(
    f"VIX band {pt['vix_band']} · {pt['used_sample_size']} historical days"
    + (" · fallback sample" if pt["used_fallback"] else "")
)

tab_table, tab_chart, tab_recs = st.tabs(["Table", "Chart", "Recommendations"])

rows = [
    {
        "strike": s,
        "p_otm_pct": stats["p_otm"] * 100,
        "distance": stats["distance_from_open"],
        "pass": stats["p_otm"] >= m["min_p_otm_floor"],
    }
    for s, stats in sorted(pt["probabilities"].items(), reverse=True)
]
df = pd.DataFrame(rows)

with tab_table:
    st.dataframe(df, use_container_width=True)

with tab_chart:
    fig = px.bar(df, x="strike", y="p_otm_pct", title="P(expire OTM) by strike")
    fig.add_hline(y=m["min_p_otm_floor"] * 100, line_dash="dash", annotation_text="Floor")
    fig.add_vline(x=m["spy_open"], line_dash="dot", annotation_text="Open")
    st.plotly_chart(fig, use_container_width=True)

with tab_recs:
    if not regime["trade_ok"]:
        st.warning("Regime filter says skip new puts today.")
    recs = r["recommendations"]
    if recs:
        st.dataframe(pd.DataFrame(recs), use_container_width=True)
    else:
        st.info("No strikes meet your P(OTM) floor today.")
