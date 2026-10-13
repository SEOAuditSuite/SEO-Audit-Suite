import streamlit as st

from ui import apply_global_ui
from common import crawl_site
st.title("🖼️ Image SEO Pro")
st.caption("Audits first-page image elements, non-empty ALT coverage, loading hints and intrinsic dimensions where available.")
url=st.text_input("Website URL",placeholder="https://example.com")
if st.button("Audit Images",type="primary"):
    crawl=crawl_site(url,limit=1,prefer_browser=True)
    if not crawl["pages"]: st.error("Could not render the page."); st.stop()
    st.caption("Mode: " + ("Browser-rendered DOM" if crawl["browser_used"] else "HTTP HTML fallback") + "; first inspected page: " + crawl["pages"][0].final_url)
    st.caption("Includes repeated and hidden image elements. Non-empty ALT coverage does not assess text quality; empty ALT may be appropriate for decorative images.")
    imgs=crawl["pages"][0].images; total=len(imgs); alt=sum(bool(x.get("alt","").strip()) for x in imgs); empty=sum("alt" in x and not x.get("alt","").strip() for x in imgs)
    c=st.columns(5); c[0].metric("First-page image elements",total); c[1].metric("Non-empty ALT",alt); c[2].metric("ALT missing/empty",max(total-alt,0)); c[3].metric("First-page ALT coverage",f"{round(alt/total*100)}%" if total else "N/A"); c[4].metric("Lazy-loaded",sum(x.get("loading")=="lazy" for x in imgs))
    if imgs: st.dataframe(imgs,use_container_width=True,hide_index=True)
    else: st.info("No <img> elements were observed in this first-page snapshot.")
