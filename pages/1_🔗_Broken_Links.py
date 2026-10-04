import streamlit as st
from common import crawl_site, check_urls
st.title("🔗 Broken Link & Status Auditor Pro")
st.caption("Rendered links are checked and 4xx responses are classified conservatively because external platforms may reject automated requests.")
url=st.text_input("Website URL",placeholder="https://example.com")
limit=st.slider("Pages to crawl",1,50,10); max_links=st.slider("Maximum unique links to verify",10,500,100)
if st.button("Check Links",type="primary"):
    crawl=crawl_site(url,limit=limit,prefer_browser=True); pages=crawl["pages"]
    links=[]
    for p in pages: links.extend(i["url"] for i in p.internal_links+p.external_links)
    links=list(dict.fromkeys(links))[:max_links]
    with st.spinner(f"Checking {len(links)} links…"): rows=check_urls(links)
    working=[x for x in rows if x["classification"]=="working"]; review=[x for x in rows if x["classification"]=="review"]; broken=[x for x in rows if x["classification"]=="broken"]; errors=[x for x in rows if x["classification"]=="error"]
    c=st.columns(5); c[0].metric("Checked",len(rows)); c[1].metric("Working",len(working)); c[2].metric("Review",len(review)); c[3].metric("Confirmed broken",len(broken)); c[4].metric("Errors",len(errors))
    if broken: st.subheader("🚨 Confirmed broken"); st.dataframe(broken,use_container_width=True,hide_index=True)
    if review: st.subheader("⚠️ Verification required"); st.dataframe(review,use_container_width=True,hide_index=True)
    if errors: st.subheader("⚠️ Request errors"); st.dataframe(errors,use_container_width=True,hide_index=True)
