import streamlit as st
from common import get_robots_sitemap, parse_sitemap, check_urls, normalize_url
st.title("🗺️ Sitemap & Robots Health")
st.caption("Checks availability, sitemap URL inventory, HTTP status, and basic robots/sitemap consistency.")
url=st.text_input("Website URL",placeholder="https://example.com")
max_check=st.slider("Maximum sitemap URLs to verify",10,300,50)
if st.button("Analyze Sitemap & Robots",type="primary"):
    base=normalize_url(url); data=get_robots_sitemap(base)
    for key,label in (("robots","/robots.txt"),("sitemap","/sitemap.xml")):
        obj=data.get(key)
        if obj and obj["status"]==200: st.success(f"{label} available — HTTP 200")
        elif obj: st.warning(f"{label} returned HTTP {obj['status']}")
        else: st.error(f"{label} could not be fetched")
    robots=data.get("robots")
    if robots: 
        with st.expander("View robots.txt"): st.code(robots["text"][:10000])
    sitemap=data.get("sitemap")
    if sitemap and sitemap["status"]==200:
        urls=parse_sitemap(sitemap["text"],base)
        st.metric("Sitemap URLs",len(urls))
        if urls:
            rows=check_urls(urls[:max_check])
            broken=[x for x in rows if isinstance(x["status"],int) and x["status"]>=400]
            st.dataframe(rows,use_container_width=True,hide_index=True)
            if broken: st.error(f"{len(broken)} sitemap URL(s) returned HTTP errors in the sampled check.")
