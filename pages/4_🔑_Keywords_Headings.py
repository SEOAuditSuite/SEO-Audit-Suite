from collections import Counter
import re
import streamlit as st
from common import crawl_site, clean_text
st.title("🔑 Keywords, Headings & Content")
st.caption("Analyzes rendered page content. Keyword density is descriptive, not a ranking recommendation.")
url=st.text_input("Website URL",placeholder="https://example.com")
if st.button("Analyze",type="primary"):
    crawl=crawl_site(url,limit=1,prefer_browser=True); 
    if not crawl["pages"]: st.error("Could not render the page."); st.stop()
    p=crawl["pages"][0]
    text=" ".join(p.h1+p.h2+p.h3+[p.title,p.description])
    # Use body text from a browser-rendered page by reconstructing visible headings + metadata plus a lightweight request fallback.
    from common import parse_html, fetch
    try: body=clean_text(parse_html(fetch(p.final_url).text).get_text(" ",strip=True))
    except Exception: body=text
    words=re.findall(r"[A-Za-z][A-Za-z0-9'’-]{2,}",body.lower())
    stop=set("the and for are but not you your with this that from have has was were into about can will our their they http https www com page home more here where what when which who how".split())
    c=Counter(w for w in words if w not in stop); total=sum(c.values())
    st.write("**Title:**",p.title or "Missing"); st.write("**H1:**",p.h1 or "Missing"); st.write("**H2:**",p.h2 or "None"); st.write("**H3:**",p.h3 or "None")
    st.metric("Analyzed words",len(words))
    st.dataframe([{"Keyword":k,"Count":v,"Approx. density":f"{v/total*100:.2f}%" if total else "N/A"} for k,v in c.most_common(30)],use_container_width=True,hide_index=True)
