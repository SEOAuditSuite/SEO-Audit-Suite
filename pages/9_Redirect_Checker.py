import streamlit as st

from ui import apply_global_ui
from common import fetch, normalize_url
st.title("↪️ Redirect Chain & URL Status")
st.caption("Checks status, final destination and redirect hops for one or more URLs.")
urls=st.text_area("One URL per line",placeholder="https://example.com/\nhttps://example.com/old-page")
if st.button("Check URLs",type="primary"):
    rows=[]
    for raw in urls.splitlines():
        if raw.strip():
            try:
                r=fetch(normalize_url(raw)); rows.append({"Status":r.status_code,"Original":raw.strip(),"Final URL":r.url,"Redirect hops":len(r.history),"Chain":" → ".join([x.url for x in r.history]+[r.url])})
            except Exception as e: rows.append({"Status":"Error","Original":raw.strip(),"Final URL":"","Redirect hops":0,"Chain":str(e)})
    if rows: st.dataframe(rows,use_container_width=True,hide_index=True)
