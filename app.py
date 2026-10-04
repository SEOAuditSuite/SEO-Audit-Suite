import streamlit as st

st.set_page_config(page_title="SEO Audit Suite Pro", page_icon="🔎", layout="wide")
st.markdown("""
<style>
.block-container{max-width:1400px;padding-top:2rem}
.hero{padding:28px 30px;border:1px solid #dfe4ea;border-radius:18px;background:linear-gradient(135deg,#f7f9fc,#ffffff);margin-bottom:24px}
.hero h1{font-size:42px;margin-bottom:8px}.tag{display:inline-block;padding:6px 10px;border-radius:999px;background:#eef2f7;margin-right:6px;font-size:13px}
</style>
""", unsafe_allow_html=True)
st.markdown("<div class='hero'><h1>🔎 SEO Audit Suite Pro</h1><p>Browser-rendered technical, on-page, AEO and performance auditing for modern websites.</p><span class='tag'>JavaScript Rendering</span><span class='tag'>Multi-page Crawl</span><span class='tag'>Client Reports</span></div>", unsafe_allow_html=True)

st.subheader("Professional SEO auditing workflow")
cols = st.columns(4)
for col, title, desc in zip(cols,
    ["🧾 Complete Audit", "🕷️ Modern Crawler", "🧩 Technical SEO", "📄 Client Reporting"],
    ["Run a multi-page audit with evidence and recommendations.", "Render JavaScript with Chromium when available.", "Inspect links, metadata, images, schema, sitemap and more.", "Export a clean HTML report for client delivery."]):
    col.markdown(f"**{title}**\n\n{desc}")

st.info("Start with **Complete Audit** in the sidebar. The new **Google Search Performance** page accepts a Search Console CSV export. Version 5 uses browser rendering for modern JavaScript sites; if Chromium is not installed yet, the app will explain how to enable it.")
st.caption("The audit score is an internal checklist, not an official Google ranking score. Automated findings should be validated with Search Console, PageSpeed Insights and human review.")
