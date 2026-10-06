import streamlit as st

from ui import apply_global_ui
from common import crawl_site, normalize_url
from v6_intelligence import (
    V6_ENGINE_VERSION,
    build_aeo_v2_for_page,
    analyze_entities,
    analyze_ai_crawlers,
    calculate_geo,
)

st.set_page_config(page_title="GEO Intelligence | SEO Audit Suite Pro", page_icon="🌐", layout="wide")
apply_global_ui()
st.title("🌐 GEO Intelligence")
st.write("Combine AEO readiness, entity clarity, technical accessibility, content, structured data and internal linking into a transparent GEO readiness view.")
st.info("GEO Score is an application-defined readiness model. It is not an official score from Google, OpenAI, Bing, Perplexity or another AI platform.")
url = st.text_input("Enter URL", placeholder="https://example.com")

if st.button("Run GEO Intelligence", type="primary", use_container_width=True):
    if not url.strip():
        st.warning("Please enter a URL to begin the analysis.")
    else:
        try:
            target = normalize_url(url)
            with st.spinner("Rendering webpage and calculating GEO readiness..."):
                crawl = crawl_site(target, limit=1, prefer_browser=True)
            if not crawl.get("pages"):
                st.error("The page could not be analyzed.")
            else:
                p = crawl["pages"][0]
                aeo = build_aeo_v2_for_page(p)
                entity = analyze_entities(p)
                crawler = analyze_ai_crawlers(p, target)
                geo = calculate_geo(aeo, entity, crawler, p)

                st.success("GEO Intelligence analysis completed.")
                c1, c2, c3, c4 = st.columns(4)
                c1.metric("GEO Score", f"{geo['score']}/100"); c1.caption(f"Readiness: {geo['readiness']}")
                c2.metric("AEO", f"{aeo['score']}/100")
                c3.metric("Entity", f"{entity['score']}/100")
                c4.metric("Crawler Access", f"{crawler['score']}/100")

                st.caption("GEO now reuses the same AEO 2.0, Entity and AI Crawler engines used by the standalone V6 modules.")
                st.subheader("GEO Signal Breakdown")
                for name, (score, weight) in geo["components"].items():
                    st.write(f"**{name}** — {score}/100 · Weight {weight}%")
                    st.progress(score / 100)

                st.subheader("GEO Opportunities")
                if not geo["opportunities"]:
                    st.success("No major weak GEO components were detected by this model.")
                for priority, finding, area in geo["opportunities"]:
                    (st.error if priority == "HIGH" else st.warning)(f"{priority} — {finding}")
                    st.caption(f"Service Area: {area}")

                with st.expander("Technical Context"):
                    st.write(f"**Rendered DOM:** {'Yes' if p.browser_rendered else 'No'}")
                    st.write(f"**Schema Types:** {', '.join(p.schema_types) if p.schema_types else 'None'}")
                    st.write(f"**Internal Links:** {len(p.internal_links or [])}")
                    st.write(f"**Rendered Words:** {p.word_count}")
                    st.caption(f"Engine: {V6_ENGINE_VERSION}")
        except Exception as exc:
            st.error("GEO Intelligence could not complete the analysis.")
            st.exception(exc)
