import json
import streamlit as st
from common import crawl_site
st.title("🧩 Schema Markup Inspector Pro")
st.caption("Inspects rendered JSON-LD blocks and reports detected Schema.org types. Full Schema.org validation is outside this lightweight inspector.")
url=st.text_input("Website URL",placeholder="https://example.com")
if st.button("Inspect",type="primary"):
    crawl=crawl_site(url,limit=1,prefer_browser=True)
    if not crawl["pages"]: st.error("Could not render the page."); st.stop()
    p=crawl["pages"][0]
    if not p.schema_blocks: st.warning("No JSON-LD structured data found in the rendered DOM.")
    else:
        st.success(f"Detected {len(p.schema_blocks)} JSON-LD block(s).")
        st.write("**Detected @type values:**", ", ".join(p.schema_types) if p.schema_types else "No @type values found")
        for i,block in enumerate(p.schema_blocks,1):
            st.subheader(f"JSON-LD block {i}"); st.json(block)
