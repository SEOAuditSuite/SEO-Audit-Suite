from urllib.parse import urlsplit
import streamlit as st
from ui import apply_global_ui
from common import get_robots_sitemap, check_urls, normalize_url, crawl_site
from link_diagnostics import crawl_status_cache
from sitemap_diagnostics import discover_sitemap_inventory, analyze_sitemap_candidates, sitemap_scope_validator
from client_workflow import csv_bytes

st.title("🗺️ Sitemap & Robots Health")
st.caption("Bounded XML inventory and optional comparison with a separate navigation crawl. Candidates are not proven orphans.")
url = st.text_input("Website URL", placeholder="https://example.com")
sitemap_url = st.text_input("Optional explicit sitemap URL")
compare = st.checkbox("Compare with navigation crawl", value=False)
crawl_limit = st.slider("Maximum navigation pages", 1, 50, 10)
verify = st.checkbox("Run existing sitemap page status check (additional requests)", value=False)
max_check = st.slider("Maximum sitemap URLs to verify", 10, 300, 50)
if st.button("Analyze Sitemap & Robots", type="primary"):
    try:
        base = normalize_url(url)
        crawl = crawl_site(base, limit=crawl_limit, prefer_browser=True) if compare else None
        effective = crawl['pages'][0].final_url if crawl and crawl.get('pages') else base
        data = get_robots_sitemap(effective, url_validator=sitemap_scope_validator(effective))
        robots = data.get('robots')
        if robots:
            with st.expander("View robots.txt"):
                st.code(robots['text'][:10000])
        for error in data.get('errors', []):
            st.warning(str(error))
        inventory = discover_sitemap_inventory(effective, data, sitemap_url)
        st.metric("Inventoried sitemap page URLs", len(inventory['inventory']))
        st.caption('Sitemap discovery completed within configured limits.' if inventory['complete'] else 'Sitemap discovery incomplete; review coverage warnings.')
        for warning in inventory['warnings']:
            st.warning(warning)
        st.dataframe(inventory['documents'], use_container_width=True, hide_index=True)
        if crawl is not None:
            result = analyze_sitemap_candidates(crawl, inventory)
            st.info(result['scope_note'])
            st.metric("Potential orphan candidates (limited evidence)", result['candidate_count'] if result['comparison_available'] else 'Not assessed')
            st.dataframe(result['rows'], use_container_width=True, hide_index=True)
            st.download_button('Download sitemap candidate evidence', csv_bytes(result['rows']), 'sitemap-candidate-evidence.csv', 'text/csv')
        else:
            st.dataframe(inventory['inventory'], use_container_width=True, hide_index=True)
        if verify:
            # Existing health check only: never contributes links or seeds to the graph.
            urls = [r['URL'] for r in inventory['inventory'] if urlsplit(r['URL']).hostname == inventory['audit_hostname']]
            st.dataframe(check_urls(urls[:max_check], cached=crawl_status_cache(crawl) if crawl else None), use_container_width=True, hide_index=True)
    except Exception as exc:
        st.error(f"Sitemap analysis could not be completed: {exc}")
