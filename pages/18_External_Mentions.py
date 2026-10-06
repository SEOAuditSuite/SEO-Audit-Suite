import io

import pandas as pd
import streamlit as st

from ui import apply_global_ui

from common import crawl_site, normalize_url
from v6_intelligence import analyze_entities
from v6_trust import verify_external_mention, summarize_external_mentions

st.set_page_config(page_title="External Mentions", page_icon="🌍", layout="wide")
apply_global_ui()
st.title("🌍 External Mentions & Backlink Evidence")
st.write("Verify supplied external URLs for brand mentions and backlinks to the audited website.")
st.caption("This verifier checks only the evidence URLs you provide. It is not a web-wide backlink index and does not estimate proprietary DA/DR/PageRank metrics.")

target_url = st.text_input("Audited website", value="", placeholder="https://example.com")
brand_name = st.text_input("Brand name (optional — auto-detected when blank)", value="")

st.write("**External evidence URLs** — one URL per line")
url_text = st.text_area("Paste mention/backlink URLs", height=160, placeholder="https://example.com/article-about-your-brand\nhttps://another-site.com/review")

uploaded = st.file_uploader("Or upload a CSV containing a URL column", type=["csv"])

if st.button("Verify External Mentions", type="primary"):
    target = normalize_url(target_url)
    if not target:
        st.error("Enter a valid audited website URL.")
        st.stop()

    brand = brand_name.strip()
    if not brand:
        with st.spinner("Detecting the rendered brand name..."):
            crawl = crawl_site(target, limit=1, prefer_browser=True)
        if crawl.get("pages"):
            entity = analyze_entities(crawl["pages"][0])
            brand = entity.get("rendered_brand") or (entity.get("names") or [""])[0]

    urls = [line.strip() for line in url_text.splitlines() if line.strip()]

    if uploaded is not None:
        try:
            data = pd.read_csv(io.BytesIO(uploaded.getvalue()))
            candidates = [c for c in data.columns if str(c).strip().lower() in ("url", "mention_url", "source_url", "link")]
            if candidates:
                urls.extend(str(v).strip() for v in data[candidates[0]].dropna().tolist() if str(v).strip())
            else:
                st.warning("CSV uploaded, but no URL / mention_url / source_url / link column was found.")
        except Exception as exc:
            st.error(f"Could not read CSV: {exc}")
            st.stop()

    urls = list(dict.fromkeys(urls))
    if not urls:
        st.info("Add at least one external evidence URL or upload a CSV before running verification.")
        st.stop()

    st.write(f"**Brand used for verification:** {brand or 'Not detected'}")
    progress = st.progress(0)
    rows = []
    for i, url in enumerate(urls, start=1):
        rows.append(verify_external_mention(target, brand, url))
        progress.progress(i / len(urls))

    result = summarize_external_mentions(rows)
    st.success("External mention verification completed.")

    e = result["evidence"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Evidence Score", f"{result['score']}/100")
    c1.caption(f"Readiness: {result['readiness']}")
    c2.metric("Brand Mentions", e.get("brand_mentions", 0))
    c3.metric("Backlinks", e.get("backlinks", 0))
    c4.metric("Verified Referring Domains", e.get("referring_domains", 0))

    q1, q2, q3 = st.columns(3)
    q1.metric("URLs Supplied", e.get("urls_checked", 0))
    q2.metric("URLs Fetchable", e.get("reachable", 0))
    q3.metric("Fetched External Domains", e.get("fetched_domains", 0))

    st.subheader("Evidence Score Breakdown")
    for name, (score, maximum) in result.get("components", {}).items():
        st.write(f"**{name}** — {score}/{maximum}")

    st.caption(
        "HTTP reachability is shown as verification context only and does not add authority points. "
        "Referring Domains counts domains with a verified backlink, not merely fetchable URLs."
    )

    st.subheader("Verified Evidence")
    table_rows = []
    for row in rows:
        table_rows.append({
            "Domain": row.get("domain"),
            "HTTP": row.get("status"),
            "Brand Mention": "Yes" if row.get("brand_mentioned") else "No",
            "Backlink": "Yes" if row.get("backlink_found") else "No",
            "Followed": "Yes" if row.get("followed_backlink") else "No",
            "Rel": row.get("link_rel"),
            "URL": row.get("url"),
            "Error": row.get("error"),
        })
    st.dataframe(pd.DataFrame(table_rows), use_container_width=True, hide_index=True)

    st.subheader("External Authority Opportunities")
    if result["findings"]:
        for priority, finding, service in result["findings"]:
            st.write(f"**{priority} — {finding}**")
            st.caption(f"Service Area: {service}")
    else:
        st.success("The supplied evidence set contains strong verified mention/backlink coverage.")

    st.info(result["disclaimer"])
