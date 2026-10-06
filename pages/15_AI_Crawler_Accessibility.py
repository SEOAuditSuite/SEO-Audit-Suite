import streamlit as st

from ui import apply_global_ui
from common import crawl_site, normalize_url
from v6_intelligence import analyze_ai_crawlers
st.set_page_config(page_title="AI Crawler Accessibility | SEO Audit Suite Pro",page_icon="🤖",layout="wide")
apply_global_ui()
st.title("🤖 AI Crawler Accessibility")
st.write("Check technical signals that can affect discovery and access for search and named AI crawlers.")
st.info("Crawler rules indicate technical access signals only; they do not guarantee indexing, training, citation or visibility in an AI product.")
url=st.text_input("Enter URL",placeholder="https://example.com")
if st.button("Run AI Crawler Audit",type="primary",use_container_width=True):
    if not url.strip(): st.warning("Please enter a URL to begin the analysis.")
    else:
        try:
            target=normalize_url(url)
            with st.spinner("Rendering page and checking crawler-access signals..."): crawl=crawl_site(target,limit=1,prefer_browser=True)
            if not crawl.get("pages"): st.error("The page could not be analyzed.")
            else:
                p=crawl["pages"][0]; r=analyze_ai_crawlers(p,target); st.success("AI Crawler Accessibility audit completed.")
                c1,c2,c3,c4=st.columns(4); c1.metric("Accessibility Score",f"{r['score']}/100"); c1.caption(f"Readiness: {r['readiness']}"); c2.metric("robots.txt",r['robots_status'] or "Error"); c3.metric("sitemap.xml",r['sitemap_status'] or "Error"); c4.metric("Indexable","Yes" if r['indexable'] else "No")
                st.subheader("Technical Access Signals")
                a,b,c=st.columns(3); a.metric("Canonical Consistency","Pass" if r['canonical_ok'] else "Review"); b.metric("Rendered DOM","Yes" if r['rendered'] else "No"); c.metric("Substantial Content","Yes" if r['content_ok'] else "Review")
                st.subheader("Named Crawler Rules")
                for item in r['bots']:
                    mark="⛔" if item['blocked_all'] else "✓"; explicit="explicit robots rule detected" if item['explicit_rule'] else "no explicit bot-specific rule detected"
                    st.write(f"{mark} **{item['crawler']}** — {item['status']} ({explicit})")
                st.subheader("Accessibility Opportunities")
                if not r['findings']: st.success("No major crawler-access gaps were detected by this model.")
                for priority,finding,area in r['findings']:
                    (st.error if priority=="HIGH" else st.warning)(f"{priority} — {finding}"); st.caption(f"Service Area: {area}")
        except Exception as exc: st.error("AI Crawler Accessibility could not complete the analysis."); st.exception(exc)
