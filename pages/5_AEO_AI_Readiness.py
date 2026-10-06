import streamlit as st

from ui import apply_global_ui
from common import crawl_site, aeo_score
st.title("🤖 AEO / AI Search Readiness")
st.caption("Heuristic readiness signals only — not a Google, ChatGPT, or AI-search ranking score.")
url=st.text_input("Website URL",placeholder="https://example.com")
if st.button("Scan",type="primary"):
    crawl=crawl_site(url,limit=1,prefer_browser=True)
    if not crawl["pages"]: st.error("Could not render the page."); st.stop()
    p=crawl["pages"][0]
    (score,passed,review),checks=aeo_score(p)
    st.metric("AEO Readiness",f"{score}/100")
    st.caption(f"{passed} of {len(checks)} defined signals passed. This is an internal heuristic, not a ranking measurement.")
    for label,ok,rec in checks:
        with st.container(border=True):
            (st.success if ok else st.warning)(f"{'PASS' if ok else 'REVIEW'} — {label}")
            if not ok: st.write(f"Recommended action: {rec}")
    st.subheader("Evidence")
    st.write(f"H1: {len(p.h1)} · H2: {len(p.h2)} · H3: {len(p.h3)} · Lists: {p.lists} · Tables: {p.tables} · Words: {p.word_count}")
    st.write("Schema types: " + (", ".join(p.schema_types) if p.schema_types else "None detected on this page"))
