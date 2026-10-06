import streamlit as st

from ui import apply_global_ui

from common import normalize_url
from v6_strategy import build_ai_search_audit, STRATEGY_ENGINE_VERSION

st.set_page_config(page_title="AI Search Audit", page_icon="🧭", layout="wide")
apply_global_ui()
st.title("🧭 AI Search Audit")
st.write("Run one consolidated audit of the observable signals that support answer-engine and generative-search readiness.")
st.caption("This audit reuses the shared V6 AEO, Entity, AI Crawler, Authority and Reputation engines rather than creating separate duplicate scores.")

url = st.text_input("Website", value="", placeholder="https://example.com")
page_limit = st.slider("Pages to crawl", min_value=3, max_value=15, value=10)

if st.button("Run AI Search Audit", type="primary", use_container_width=True):
    target = normalize_url(url)
    if not target:
        st.error("Enter a valid website URL.")
        st.stop()

    with st.spinner("Rendering the website and building the AI-search evidence model..."):
        audit = build_ai_search_audit(target, crawl_limit=page_limit)

    if audit.get("error"):
        st.error(audit["error"])
        st.stop()

    st.success("AI Search Audit completed.")
    if audit.get("browser_used"):
        st.caption("✓ Browser-rendered multi-page crawl analyzed")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("AI Search Audit Score", f"{audit['score']}/100")
    c1.caption(f"Readiness: {audit['readiness']}")
    c2.metric("Pages Crawled", audit["pages_crawled"])
    c3.metric("Schema Coverage", f"{audit['evidence']['schema_coverage_percent']}%")
    c4.metric("Internal Destinations", audit["evidence"]["unique_internal_destinations"])

    st.subheader("AI Search Signal Breakdown")
    for name, (score, weight) in audit["components"].items():
        st.write(f"**{name}** — {score}/100 · Weight {weight}%")
        st.progress(score / 100)

    st.subheader("Cross-Module Evidence")
    raw = audit["raw"]
    e1, e2, e3, e4 = st.columns(4)
    e1.metric("AEO", f"{raw['aeo']['score']}/100")
    e2.metric("GEO", f"{raw['geo']['score']}/100")
    e3.metric("Entity", f"{raw['entity']['score']}/100")
    e4.metric("Crawler Access", f"{raw['crawler']['score']}/100")
    e5, e6, e7, e8 = st.columns(4)
    e5.metric("Authority", f"{raw['authority']['score']}/100")
    e6.metric("Reputation", f"{raw['reputation']['score']}/100")
    e7.metric("Avg. Words/Page", audit["evidence"]["average_words"])
    e8.metric("Social Profiles", len(audit["evidence"].get("social_profiles", [])))

    st.subheader("Prioritized AI Search Findings")
    if not audit["findings"]:
        st.success("No major weak components were detected by this model.")
    else:
        for item in audit["findings"]:
            if item["priority"] == "HIGH":
                st.error(f"{item['priority']} — {item['finding']}")
            elif item["priority"] == "MEDIUM":
                st.warning(f"{item['priority']} — {item['finding']}")
            else:
                st.info(f"{item['priority']} — {item['finding']}")
            st.caption(f"Weight: {item['weight']}% · Service Area: {item['service_area']}")

    with st.expander("Audit Evidence"):
        st.write(f"**Schema pages:** {audit['evidence']['schema_pages']}/{audit['pages_crawled']}")
        st.write(f"**Schema types:** {', '.join(audit['evidence']['schema_types']) if audit['evidence']['schema_types'] else 'None'}")
        st.write(f"**About signal:** {'Found' if audit['evidence']['about_signal'] else 'Not Found'}")
        st.write(f"**Contact signal:** {'Found' if audit['evidence']['contact_signal'] else 'Not Found'}")
        st.write(f"**Crawl errors:** {audit['crawl_errors']}")
        st.caption(f"Engine: {STRATEGY_ENGINE_VERSION}")

    st.info(audit["disclaimer"])
