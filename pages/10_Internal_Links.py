import streamlit as st
from ui import apply_global_ui
from common import crawl_site
from link_diagnostics import analyze_links
from client_workflow import csv_bytes

st.title("🔗 Internal Link & Anchor Text Auditor Pro")
st.caption("Observed links and distinct referring pages in a bounded crawl sample.")
url = st.text_input("Website URL", placeholder="https://example.com")
limit = st.slider("Pages to crawl", 1, 50, 10)
if st.button("Analyze", type="primary"):
    try:
        crawl = crawl_site(url, limit=limit, prefer_browser=True)
        report = analyze_links(crawl)
        st.info(report['coverage_note'])
        st.caption(report['definitions'])
        if not crawl['pages']:
            st.warning("No pages inspected. Review crawl errors below.")
        cols = st.columns(3)
        cols[0].metric("Observed internal link occurrences", sum(r['Occurrences'] or 0 for r in report['edges']))
        cols[1].metric("Observed target URLs", len({r['Target'] for r in report['edges']}))
        cols[2].metric("Inspected pages with no observed referring page (excluding seed)", len(report['no_observed_inlinks']))
        st.subheader("Destination inventory")
        st.dataframe(report['inventory'], use_container_width=True, hide_index=True)
        st.subheader("Source → target evidence")
        st.caption("Status uses existing crawl responses only. Unfetched targets remain 'not checked'.")
        st.dataframe(report['edges'][:300], use_container_width=True, hide_index=True)
        st.download_button("Download all link evidence", csv_bytes(report['edges']), 'internal-link-evidence.csv', 'text/csv')
        if crawl['errors']:
            st.write("Crawl errors", crawl['errors'])
    except Exception as exc:
        st.error(f"Could not inspect links: {type(exc).__name__}. Check URL, access and limits.")
