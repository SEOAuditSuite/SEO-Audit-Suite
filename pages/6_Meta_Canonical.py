import streamlit as st

from ui import apply_global_ui
from common import crawl_site
st.title("🏷️ Meta, Canonical & Social Metadata")
st.caption("Rendered metadata audit with practical checks for titles, descriptions, canonicals and social tags.")
url=st.text_input("Website URL",placeholder="https://example.com")
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
