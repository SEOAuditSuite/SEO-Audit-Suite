import streamlit as st
from ui import apply_global_ui
from common import crawl_site, check_urls
from link_diagnostics import analyze_links, crawl_status_cache, coverage_note
from client_workflow import csv_bytes

st.title("🔗 Broken Link & Status Auditor Pro")
st.caption("HTTP status and redirect evidence tied to referring source pages. 404/410 are observed broken responses; other failures need review.")
url = st.text_input("Website URL", placeholder="https://example.com")
limit = st.slider("Pages to crawl", 1, 50, 10)
max_links = st.slider("Maximum unique links to verify", 10, 500, 100)
if st.button("Check Links", type="primary"):
    try:
        crawl = crawl_site(url, limit=limit, prefer_browser=True)
        links = list(dict.fromkeys(i['url'] for p in crawl['pages'] for i in p.internal_links + p.external_links))
        with st.spinner("Checking links; reusing observed crawl responses…"):
            rows = check_urls(links[:max_links], cached=crawl_status_cache(crawl))
        report = analyze_links(crawl, checks=rows, include_external=True)
        st.info(coverage_note(crawl))
        st.caption(f"Status-check selection: {len(rows)} targets of {len(links)} observed URLs; others retain any crawl evidence or remain not checked.")
        cols = st.columns(4)
        for col, label in zip(cols, ['working', 'review', 'broken', 'error']):
            col.metric(label.title(), sum(r['classification'] == label for r in rows))
        st.subheader("Target status inventory")
        st.dataframe(rows, use_container_width=True, hide_index=True)
        st.subheader("Referring source → target evidence")
        st.dataframe(report['edges'][:500], use_container_width=True, hide_index=True)
        st.download_button("Download all source-to-target evidence", csv_bytes(report['edges']), 'link-status-evidence.csv', 'text/csv')
        if crawl['errors']:
            st.write("Crawl errors", crawl['errors'])
    except Exception as exc:
        st.error(f"Could not check links: {type(exc).__name__}. Check URL, access and limits.")
