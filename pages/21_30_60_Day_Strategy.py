import streamlit as st

from ui import apply_global_ui

from common import normalize_url
from v6_strategy import build_ai_search_audit, build_30_60_day_strategy

st.set_page_config(page_title="30/60-Day AI Search Strategy", page_icon="🗓️", layout="wide")
apply_global_ui()
st.title("🗓️ 30/60-Day SEO + AI Search Strategy")
st.write("Turn the V6 evidence model into a prioritized client-service roadmap for the first 30 days and days 31–60.")
st.caption("The roadmap is generated from observable audit evidence. It is intentionally framed as professional recommended actions, not guaranteed ranking outcomes or step-by-step DIY instructions.")

url = st.text_input("Website", value="", placeholder="https://example.com")
page_limit = st.slider("Pages to crawl for strategy evidence", min_value=3, max_value=15, value=10)

if st.button("Build 30/60-Day Strategy", type="primary", use_container_width=True):
    target = normalize_url(url)
    if not target:
        st.error("Enter a valid website URL.")
        st.stop()

    with st.spinner("Auditing the website and prioritizing the 30/60-day roadmap..."):
        audit = build_ai_search_audit(target, crawl_limit=page_limit)
        plan = build_30_60_day_strategy(audit)

    if audit.get("error"):
        st.error(audit["error"])
        st.stop()

    st.success("30/60-day strategy generated from the current audit evidence.")
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Starting AI Search Score", f"{plan['summary']['starting_score']}/100")
    c1.caption(f"Readiness: {plan['summary']['readiness']}")
    c2.metric("High Priority Strategy Actions", plan["summary"]["high_priority_actions"])
    c3.metric("Medium Priority Strategy Actions", plan["summary"]["medium_priority_actions"])
    c4.metric("Opportunities", plan["summary"]["opportunities"])

    st.subheader("First 30 Days — Foundation & Critical Gaps")
    for idx, item in enumerate(plan["first_30_days"], start=1):
        st.markdown(f"**{idx}. Strategy Priority: {item['priority']} — {item['service_area']}**")
        st.write(f"**Recommended SEO Action:** {item['recommended_action']}")
        st.write(f"**Why it matters:** {item['why_it_matters']}")
        st.caption(f"Success signal: {item['success_signal']}")
        st.divider()

    st.subheader("Days 31–60 — Expansion, Authority & Validation")
    for idx, item in enumerate(plan["days_31_60"], start=1):
        st.markdown(f"**{idx}. Strategy Priority: {item['priority']} — {item['service_area']}**")
        st.write(f"**Recommended SEO Action:** {item['recommended_action']}")
        st.write(f"**Why it matters:** {item['why_it_matters']}")
        st.caption(f"Success signal: {item['success_signal']}")
        st.divider()

    st.subheader("Strategy Evidence Snapshot")
    rows = []
    for name, (score, weight) in audit["components"].items():
        rows.append({"Signal": name, "Score": score, "Weight": f"{weight}%"})
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.info(plan["disclaimer"])
