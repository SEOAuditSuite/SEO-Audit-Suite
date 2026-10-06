import streamlit as st

from ui import apply_global_ui

st.set_page_config(page_title="SEO Audit Suite V6", page_icon="◈", layout="wide")
apply_global_ui()

st.markdown(
    """
    <section class="v6-hero">
        <div class="v6-eyebrow">SEO Audit Suite V6 · AI Search Intelligence Platform</div>
        <h1>Audit modern search visibility from one evidence layer.</h1>
        <p>Browser-rendered technical SEO, AEO, GEO, entity, crawler accessibility, authority, reputation, competitive intelligence, strategy and client reporting — built as one connected audit workflow.</p>
        <span class="v6-pill">JavaScript rendering</span>
        <span class="v6-pill">Multi-page crawl</span>
        <span class="v6-pill">AEO + GEO</span>
        <span class="v6-pill">Authority + reputation</span>
        <span class="v6-pill">Competitive intelligence</span>
        <span class="v6-pill">Client PDF reports</span>
    </section>
    """,
    unsafe_allow_html=True,
)

st.markdown('<span class="v6-status"><span class="v6-dot"></span>V6 core engines integrated and validated</span>', unsafe_allow_html=True)

st.markdown('<div class="v6-section-label">Platform overview</div>', unsafe_allow_html=True)
st.markdown(
    """
    <div class="v6-grid">
      <div class="v6-card"><div class="icon">⌁</div><h3>Traditional SEO</h3><p>Complete Audit, broken links, sitemap/robots, PageSpeed, headings, metadata, image SEO, schema, redirects and internal linking.</p></div>
      <div class="v6-card"><div class="icon">✦</div><h3>AI Search Intelligence</h3><p>AEO 2.0, GEO, entity clarity and named AI crawler accessibility using the same shared evidence model.</p></div>
      <div class="v6-card"><div class="icon">◎</div><h3>Authority & Trust</h3><p>Authority foundations, reputation signals and supplied external mention/backlink evidence with transparent scoring.</p></div>
      <div class="v6-card"><div class="icon">⇄</div><h3>Competitive Intelligence</h3><p>Compare your site with supplied competitors using a frozen normalized crawl snapshot and metric-level gaps.</p></div>
      <div class="v6-card"><div class="icon">↗</div><h3>Strategy</h3><p>AI Search Audit plus a prioritized 30/60-day roadmap derived from current observable website evidence.</p></div>
      <div class="v6-card"><div class="icon">▤</div><h3>Client Deliverables</h3><p>Professional client-facing PDF and HTML reports with executive summary, findings, evidence and roadmap.</p></div>
    </div>
    """,
    unsafe_allow_html=True,
)

st.markdown('<div class="v6-section-label">Recommended workflow</div>', unsafe_allow_html=True)
c1, c2, c3, c4 = st.columns(4)
with c1:
    st.markdown("### 01 · Diagnose")
    st.write("Start with **Complete Audit** for the broad browser-rendered SEO baseline.")
with c2:
    st.markdown("### 02 · Expand")
    st.write("Run **AI Search**, **Authority & Trust**, and external evidence modules where relevant.")
with c3:
    st.markdown("### 03 · Compare")
    st.write("Use **Competitive Intelligence** with the same crawl depth across supplied websites.")
with c4:
    st.markdown("### 04 · Deliver")
    st.write("Generate the **30/60-Day Strategy** and professional **Client Report & PDF**.")

st.info("Scores are application-defined readiness and audit models, not official Google/OpenAI ranking scores. Validate external performance, rankings, backlinks and review data in the relevant platforms.")
