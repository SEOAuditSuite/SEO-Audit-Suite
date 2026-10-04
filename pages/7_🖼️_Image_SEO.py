import streamlit as st
from common import crawl_site
st.title("🖼️ Image SEO Pro")
st.caption("Audits rendered image elements, ALT coverage, loading hints and intrinsic dimensions where available.")
url=st.text_input("Website URL",placeholder="https://example.com")
if st.button("Audit Images",type="primary"):
    crawl=crawl_site(url,limit=1,prefer_browser=True)
    if not crawl["pages"]: st.error("Could not render the page."); st.stop()
    imgs=crawl["pages"][0].images; total=len(imgs); alt=sum(bool(x.get("alt","").strip()) for x in imgs); empty=sum("alt" in x and not x.get("alt","").strip() for x in imgs)
    c=st.columns(5); c[0].metric("Rendered images",total); c[1].metric("ALT present",alt); c[2].metric("ALT missing/empty",max(total-alt,0)); c[3].metric("ALT coverage",f"{round(alt/total*100)}%" if total else "N/A"); c[4].metric("Lazy-loaded",sum(x.get("loading")=="lazy" for x in imgs))
    if imgs: st.dataframe(imgs,use_container_width=True,hide_index=True)
    else: st.info("No rendered <img> elements were detected by the browser crawler.")
