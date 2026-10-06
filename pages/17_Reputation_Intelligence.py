import streamlit as st

from ui import apply_global_ui

from common import crawl_site, normalize_url
from v6_trust import analyze_reputation

st.set_page_config(page_title="Reputation Intelligence", page_icon="⭐", layout="wide")
apply_global_ui()
st.title("⭐ Reputation Intelligence")
st.write("Audit observable trust, social-proof and reputation signals across the rendered site.")
st.caption("This module scores website-visible signals only. External reviews and web-wide sentiment require supplied evidence or connected data sources.")

url = st.text_input("Website URL", value="", placeholder="https://example.com")
limit = st.slider("Pages to crawl", min_value=3, max_value=15, value=10)

if st.button("Run Reputation Intelligence", type="primary"):
    target = normalize_url(url)
    if not target:
        st.error("Enter a valid website URL.")
        st.stop()

    with st.spinner("Crawling reputation and trust signals..."):
        crawl = crawl_site(target, limit=limit, prefer_browser=True)

    pages = crawl.get("pages", [])
    if not pages:
        st.error("No crawlable pages were available for reputation analysis.")
        st.stop()

    result = analyze_reputation(pages)
    st.success("Reputation Intelligence analysis completed.")
    if crawl.get("browser_used"):
        st.caption("✓ Browser-rendered multi-page crawl analyzed")

    e = result["evidence"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Reputation Score", f"{result['score']}/100")
    c1.caption(f"Readiness: {result['readiness']}")
    c2.metric("Social Profiles", len(e["social_profiles"]))
    c3.metric("Review Schema", "Found" if e["review_schema"] else "Not Found")
    c4.metric("Review Content", "Found" if e["review_text_signal"] else "Not Found")

    st.subheader("Reputation Signal Breakdown")
    for name, (score, maximum) in result["components"].items():
        st.write(f"**{name}** — {score}/{maximum}")

    st.subheader("Identity & Trust Evidence")
    a, b, c, d = st.columns(4)
    a.metric("Brand", e["brand"] or "Not detected")
    b.metric("Contact", "Found" if e["contact_signal"] else "Not Found")
    c.metric("Address", "Found" if e["address_signal"] else "Not Found")
    d.metric("About", "Found" if e["about_signal"] else "Not Found")

    if e["social_profiles"]:
        st.write("**Detected social profile URLs**")
        for profile in e["social_profiles"]:
            st.write(f"- {profile}")

    st.subheader("Reputation Opportunities")
    if result["findings"]:
        for priority, finding, service in result["findings"]:
            st.write(f"**{priority} — {finding}**")
            st.caption(f"Service Area: {service}")
    else:
        st.success("No major website-visible reputation gaps were detected by this model.")

    st.info(result["disclaimer"])
