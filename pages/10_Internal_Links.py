import streamlit as st

from ui import apply_global_ui
from collections import Counter, defaultdict
from common import crawl_site, canonical_url
st.title("🔗 Internal Link & Anchor Text Auditor Pro")
st.caption("Rendered internal links are classified by destination and anchor quality; query/utility URLs remain visible for review.")
url=st.text_input("Website URL",placeholder="https://example.com")
limit=st.slider("Pages to crawl",1,50,10)
if st.button("Analyze",type="primary"):
    crawl=crawl_site(url,limit=limit,prefer_browser=True); pages=crawl["pages"]
    anchors=Counter(); dests=Counter(); incoming=Counter(); empty=0; source_rows=[]
    crawled={canonical_url(p.final_url) for p in pages}
    for p in pages:
        for item in p.internal_links:
            anchors[item["anchor"]]+=1; dest=canonical_url(item["url"]); dests[dest]+=1; incoming[dest]+=1; empty += item["anchor"]=="(empty anchor)"
            source_rows.append({"Source":p.url,"Anchor":item["anchor"],"Destination":item["url"],"Utility/query":("?" in item["url"] or "/wp-login" in item["url"])})
    orphan=[p.url for p in pages if incoming[canonical_url(p.final_url)]==0 and canonical_url(p.final_url)!=canonical_url(pages[0].final_url)]
    c=st.columns(4); c[0].metric("Internal links",len(source_rows)); c[1].metric("Unique destinations",len(dests)); c[2].metric("Empty anchors",empty); c[3].metric("Possible orphans",len(orphan))
    st.subheader("Anchor text"); st.dataframe([{"Anchor":k,"Count":v} for k,v in anchors.most_common(50)],use_container_width=True,hide_index=True)
    st.subheader("Destination inventory"); st.dataframe([{"URL":k,"Incoming links":v,"Crawled":k in crawled} for k,v in dests.most_common(100)],use_container_width=True,hide_index=True)
    if orphan: st.subheader("Possible orphan pages"); st.dataframe([{"URL":x} for x in orphan],use_container_width=True,hide_index=True)
    st.subheader("Source → destination evidence"); st.dataframe(source_rows[:300],use_container_width=True,hide_index=True)
