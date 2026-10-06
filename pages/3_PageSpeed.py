import os
import requests
import streamlit as st

from ui import apply_global_ui
st.title("⚡ PageSpeed & Core Web Vitals")
st.caption("Google PageSpeed Insights integration. API access is optional and requires a Google PageSpeed API key.")
url=st.text_input("Website URL",placeholder="https://example.com")
key=st.text_input("Google PageSpeed API key",type="password",value=os.getenv("PAGESPEED_API_KEY", ""))
strategy=st.selectbox("Device",["mobile","desktop"])
if st.button("Run PageSpeed",type="primary"):
    if not url or not key: st.error("Enter a URL and PageSpeed API key."); st.stop()
    try:
        r=requests.get("https://www.googleapis.com/pagespeedonline/v5/runPagespeed",params={"url":url,"key":key,"strategy":strategy,"category":["performance","accessibility","best-practices","seo"]},timeout=90)
        if not r.ok: st.error(f"PageSpeed API request failed: HTTP {r.status_code}"); st.code(r.text[:3000]); st.stop()
        data=r.json(); cats=data.get("lighthouseResult",{}).get("categories",{}); audits=data.get("lighthouseResult",{}).get("audits",{})
        cols=st.columns(4)
        for col,name in zip(cols,["performance","accessibility","best-practices","seo"]):
            s=cats.get(name,{}).get("score"); col.metric(name.title(),f"{round(s*100)}/100" if s is not None else "N/A")
        st.subheader("Core Web Vitals / lab metrics")
        keys=[("LCP","largest-contentful-paint","ms"),("CLS","cumulative-layout-shift",""),("INP","interaction-to-next-paint","ms"),("FCP","first-contentful-paint","ms"),("TTFB","server-response-time","ms")]
        cols=st.columns(5)
        for col,(label,aid,suffix) in zip(cols,keys):
            a=audits.get(aid,{})
            col.metric(label,a.get("displayValue","N/A"))
        st.subheader("Opportunities & diagnostics")
        rows=[]
        for aid,a in audits.items():
            if a.get("scoreDisplayMode") not in ("notApplicable","informative") and a.get("details") and a.get("title"):
                score=a.get("score")
                if score is not None and score < 0.9: rows.append({"Audit":a.get("title"),"Score":round(score*100),"Display":a.get("displayValue","")})
        st.dataframe(rows[:40],use_container_width=True,hide_index=True)
    except Exception as e: st.error(f"Could not run PageSpeed: {e}")
