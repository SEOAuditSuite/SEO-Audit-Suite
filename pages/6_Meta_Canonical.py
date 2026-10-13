import streamlit as st

from ui import apply_global_ui
from common import crawl_site
st.title("🏷️ Meta, Canonical & Social Metadata")
st.caption("Rendered metadata audit with practical checks for titles, descriptions, canonicals and social tags.")
url=st.text_input("Website URL",placeholder="https://example.com")
with st.expander("Optional raw HTML / rendered DOM comparison"):
    from rendering_diagnostics import compare_url, NOTE
    from common import normalize_url
    st.caption(NOTE)
    if st.button("Compare one page", key="rendering_compare"):
        with st.spinner("Collecting a bounded comparison (up to 45 seconds)..."):
            st.session_state['rendering_comparison'] = compare_url(normalize_url(url))
    if 'rendering_comparison' in st.session_state:
        result = st.session_state['rendering_comparison']
        st.write(result['requested_url'])
        st.info(result['status'])
        for warning in result['warnings']:
            st.warning(warning)
        from comparison_view import show_comparison
        show_comparison(result)
        st.json({k: result[k] for k in ('final_url', 'browser_url', 'network', 'limits')})
if st.button("Audit",type="primary"):
    crawl=crawl_site(url,limit=1,prefer_browser=True)
    if not crawl["pages"]: st.error("Could not render the page."); st.stop()
    p=crawl["pages"][0]
    c=st.columns(4); c[0].metric("Title",f"{len(p.title)} chars" if p.title else "Missing"); c[1].metric("Description",f"{len(p.description)} chars" if p.description else "Missing"); c[2].metric("Canonical", "Found" if p.canonical else "Missing"); c[3].metric("OG tags",len(p.og))
    st.write("**Title:**",p.title or "Missing"); st.write("**Description:**",p.description or "Missing"); st.write("**Canonical:**",p.canonical or "Missing")
    st.subheader("Social metadata")
    st.json({"Open Graph":p.og,"Twitter":p.twitter})
    if len(p.title)<30 or len(p.title)>65: st.warning("Review title length and SERP clarity.")
    if len(p.description)<70 or len(p.description)>170: st.warning("Review description length and potential truncation.")
