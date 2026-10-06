import re

import streamlit as st

from ui import apply_global_ui

from common import normalize_url
from v6_strategy import build_ai_search_audit, build_30_60_day_strategy
from v6_reporting import (
    REPORT_ENGINE_VERSION,
    build_client_report_model,
    build_client_report_pdf,
    build_client_report_html,
)

st.set_page_config(page_title="Client Report & PDF", page_icon="📄", layout="wide")
apply_global_ui()
st.title("📄 Client Report & PDF")
st.write("Turn the V6 audit evidence and 30/60-day roadmap into a professional client-facing report.")
st.caption("The report uses the same shared V6 audit engines. It does not invent rankings, backlink metrics, traffic or AI citations that were not observed in the audit.")

url = st.text_input("Website", value="", placeholder="https://example.com")
client_name = st.text_input("Client name (optional)", value="")
prepared_by = st.text_input("Prepared by", value="SEO Audit Suite Pro")
report_title = st.text_input("Report title", value="SEO + AI Search Audit Report")
page_limit = st.slider("Pages to crawl for report evidence", min_value=3, max_value=15, value=10)

if st.button("Generate Client Report", type="primary", use_container_width=True):
    target = normalize_url(url)
    if not target:
        st.error("Enter a valid website URL.")
        st.stop()

    with st.spinner("Running the V6 audit, building the strategy and generating the client report..."):
        audit = build_ai_search_audit(target, crawl_limit=page_limit)
        if audit.get("error"):
            st.error(audit["error"])
            st.stop()
        plan = build_30_60_day_strategy(audit)
        model = build_client_report_model(
            audit,
            plan,
            client_name=client_name,
            prepared_by=prepared_by,
            report_title=report_title,
        )
        pdf_bytes = build_client_report_pdf(model)
        html_text = build_client_report_html(model)

    st.success("Client report generated from the current browser-rendered audit evidence.")
    if audit.get("browser_used"):
        st.caption("✓ Browser-rendered multi-page crawl analyzed")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AI Search Score", f"{audit['score']}/100")
    c1.caption(f"Readiness: {audit['readiness']}")
    c2.metric("Pages Crawled", audit["pages_crawled"])
    c3.metric("High Priority Audit Findings", sum(1 for x in model["findings"] if x["priority"] == "HIGH"))
    c4.metric("Strategy Actions", len(model["first_30_days"]) + len(model["days_31_60"]))

    st.subheader("Report Preview")
    st.write(f"**Website:** {model['website']}")
    if model.get("client_name"):
        st.write(f"**Client:** {model['client_name']}")
    st.write(f"**Prepared by:** {model['prepared_by']}")

    st.markdown("#### Executive Summary")
    for point in model["executive_points"]:
        st.write(f"- {point}")

    st.info("Report labeling note: **AEO Intelligence 2.0** is the dedicated AI-search readiness model. **Legacy AEO Checklist** is the older Complete Audit heuristic; the two scores measure different checklists and are intentionally labeled separately in the exported report.")

    st.markdown("#### Prioritized Audit Findings")
    if not model["findings"]:
        st.success("No major weak components were detected by the current model.")
    else:
        for item in model["findings"]:
            st.markdown(f"**{item['priority']} — {item['service_area']}**")
            st.write(f"**Finding:** {item['finding']}")
            st.write(f"**Why it matters:** {item['why_it_matters']}")
            st.write(f"**Recommended SEO Action:** {item['recommended_action']}")
            st.caption(f"Evidence: {item['score']}/100 · Weight {item['weight']}%")
            st.divider()

    safe_domain = re.sub(r"[^a-zA-Z0-9_-]+", "-", model.get("domain", "client")).strip("-") or "client"
    st.subheader("Downloads")
    d1, d2 = st.columns(2)
    d1.download_button(
        "Download Client PDF",
        data=pdf_bytes,
        file_name=f"{safe_domain}-seo-ai-search-audit.pdf",
        mime="application/pdf",
        use_container_width=True,
    )
    d2.download_button(
        "Download HTML Report",
        data=html_text.encode("utf-8"),
        file_name=f"{safe_domain}-seo-ai-search-audit.html",
        mime="text/html",
        use_container_width=True,
    )

    with st.expander("Report Scope & Methodology"):
        st.write(audit["disclaimer"])
        st.write(plan["disclaimer"])
        st.caption(f"Report engine: {REPORT_ENGINE_VERSION}")
