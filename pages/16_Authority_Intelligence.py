import streamlit as st

from ui import apply_global_ui

from common import crawl_site, normalize_url
from v6_trust import analyze_authority

st.set_page_config(page_title="Authority Intelligence", page_icon="🏆", layout="wide")
apply_global_ui()
st.title("🏆 Authority Intelligence")
st.write("Audit observable on-site authority foundations across a rendered multi-page crawl.")
st.caption("This module does not estimate proprietary domain authority, PageRank, DR/DA or backlink power. External evidence is verified separately in External Mentions.")

url = st.text_input("Website URL", value="", placeholder="https://example.com")
limit = st.slider("Pages to crawl", min_value=3, max_value=15, value=10)

if st.button("Run Authority Intelligence", type="primary"):
    target = normalize_url(url)
    if not target:
        st.error("Enter a valid website URL.")
        st.stop()

    with st.spinner("Crawling authority and trust signals..."):
        crawl = crawl_site(target, limit=limit, prefer_browser=True)

    pages = crawl.get("pages", [])
    if not pages:
        st.error("No crawlable pages were available for authority analysis.")
        if crawl.get("browser_error"):
            st.caption(crawl["browser_error"])
        st.stop()

    result = analyze_authority(pages)
    st.success("Authority Intelligence analysis completed.")
    if crawl.get("browser_used"):
        st.caption("✓ Browser-rendered multi-page crawl analyzed")

    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Authority Score", f"{result['score']}/100")
    c1.caption(f"Readiness: {result['readiness']}")
    c2.metric("Pages Crawled", result["evidence"]["pages_crawled"])
    c3.metric("Avg. Words/Page", result["evidence"]["average_words"])
    c4.metric("Schema Coverage", f"{result['evidence']['schema_coverage_percent']}%")

    st.subheader("Authority Signal Breakdown")
    for name, (score, maximum) in result["components"].items():
        st.write(f"**{name}** — {score}/{maximum}")

    st.subheader("Authority Evidence")
    e = result["evidence"]
    a, b, c, d = st.columns(4)
    a.metric("About Signal", "Found" if e["about_signal"] else "Not Found")
    b.metric("Contact Signal", "Found" if e["contact_signal"] else "Not Found")
    c.metric("Identity Schema", "Found" if e["identity_schema"] else "Not Found")
    d.metric("Author Signal", "Found" if e["author_signal"] else "Not Found")
    st.write(f"**External citation domains detected:** {len(e['citation_domains'])}")
    if e["citation_domains"]:
        st.write(", ".join(e["citation_domains"][:20]))

    st.subheader("Authority Opportunities")
    if result["findings"]:
        for priority, finding, service in result["findings"]:
            st.write(f"**{priority} — {finding}**")
            st.caption(f"Service Area: {service}")
    else:
        st.success("No major on-site authority-foundation gaps were detected by this model.")

    st.info(result["disclaimer"])
