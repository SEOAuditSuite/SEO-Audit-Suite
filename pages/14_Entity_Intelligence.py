import streamlit as st

from ui import apply_global_ui
from common import crawl_site, normalize_url
from v6_intelligence import analyze_entities, V6_ENGINE_VERSION

st.set_page_config(page_title="Entity Intelligence | SEO Audit Suite Pro", page_icon="🏢", layout="wide")
apply_global_ui()
st.title("🏢 Entity Intelligence")
st.write("Evaluate whether the rendered page clearly defines the brand, organization, person or local business using both structured data and visible identity evidence.")
st.info("Entity Intelligence uses application-defined heuristics. It is not an official Knowledge Graph or AI-platform score.")
url = st.text_input("Enter URL", placeholder="https://example.com")

if st.button("Run Entity Intelligence", type="primary", use_container_width=True):
    if not url.strip():
        st.warning("Please enter a URL to begin the analysis.")
    else:
        try:
            with st.spinner("Rendering webpage and analyzing entity signals..."):
                crawl = crawl_site(normalize_url(url), limit=1, prefer_browser=True)
            if not crawl.get("pages"):
                st.error("The page could not be analyzed.")
            else:
                p = crawl["pages"][0]
                r = analyze_entities(p)
                st.success("Entity Intelligence analysis completed.")
                st.caption("✓ Browser-rendered DOM analyzed" if p.browser_rendered else "Browser rendering was unavailable; HTTP content was analyzed.")

                c1, c2, c3, c4 = st.columns(4)
                c1.metric("Entity Score", f"{r['score']}/100"); c1.caption(f"Readiness: {r['readiness']}")
                c2.metric("Schema Types", len(r["types"]))
                c3.metric("Entity Names", len(r["names"]))
                c4.metric("sameAs References", len(r["same_as"]))

                st.subheader("Identity Evidence")
                a, b, c, d = st.columns(4)
                a.metric("Contact Signal", "Found" if r["contact"] else "Not Found")
                b.metric("Address Signal", "Found" if r["address"] else "Not Found")
                c.metric("About Signal", "Found" if r["about_signal"] else "Not Found")
                d.metric("Rendered Words", p.word_count)

                if r["rendered_brand"]:
                    st.write(f"**Rendered Brand Evidence:** {r['rendered_brand']}")

                with st.expander("Detected Entity Evidence"):
                    st.write("**Types:** " + (", ".join(r["types"]) or "None"))
                    st.write("**Names:** " + (", ".join(r["names"]) or "None"))
                    st.write("**Structured Names:** " + (", ".join(r["schema_names"]) or "None"))
                    st.write("**sameAs:** " + (", ".join(r["same_as"]) or "None"))
                    st.write("**@id references:** " + (", ".join(r["ids"]) or "None"))
                    st.write(f"**Product/Service Navigation Signal:** {'Found' if r['product_service_signal'] else 'Not Found'}")

                st.subheader("Entity Opportunities")
                if not r["findings"]:
                    st.success("No major entity-clarity gaps were detected by this model.")
                for priority, finding, area in r["findings"]:
                    (st.error if priority == "HIGH" else st.warning if priority == "MEDIUM" else st.info)(f"{priority} — {finding}")
                    st.caption(f"Service Area: {area}")
                st.caption(f"Engine: {V6_ENGINE_VERSION}")
        except Exception as exc:
            st.error("Entity Intelligence could not complete the analysis.")
            st.exception(exc)
