import streamlit as st

from ui import apply_global_ui

from common import normalize_url
from v6_competitive import build_competitor_profile, compare_profiles

st.set_page_config(page_title="Competitive Intelligence", page_icon="⚔️", layout="wide")
apply_global_ui()
st.title("⚔️ Competitive Intelligence")
st.write("Compare your website with up to three supplied competitors using the same V6 SEO, AI-search, entity, authority and reputation engines.")
st.caption("Competitive scores are application-defined comparisons of observable website signals. They are not market share, Google ranking predictions, backlink-index metrics or proof that one site will outrank another.")

site_url = st.text_input("Your website", value="", placeholder="https://example.com")
competitor_text = st.text_area(
    "Competitor websites — one URL per line (1–3)",
    placeholder="https://competitor-one.com\nhttps://competitor-two.com",
    height=120,
)
page_limit = st.slider("Pages to crawl per website", min_value=3, max_value=10, value=5)

if st.button("Run Competitive Intelligence", type="primary"):
    target = normalize_url(site_url)
    competitors = []
    for line in competitor_text.splitlines():
        value = normalize_url(line.strip()) if line.strip() else ""
        if value and value not in competitors:
            competitors.append(value)

    if not target:
        st.error("Enter a valid website URL.")
        st.stop()
    if not competitors:
        st.error("Enter at least one competitor website URL.")
        st.stop()
    if len(competitors) > 3:
        st.error("Use a maximum of three competitor websites per comparison.")
        st.stop()

    competitors = [u for u in competitors if u.rstrip("/") != target.rstrip("/")]
    if not competitors:
        st.error("Competitor URLs must be different from the audited website.")
        st.stop()

    with st.spinner("Crawling your website and competitor evidence with browser rendering..."):
        target_profile = build_competitor_profile(target, crawl_limit=page_limit)
        competitor_profiles = [build_competitor_profile(u, crawl_limit=page_limit) for u in competitors]

    if target_profile.get("error"):
        st.error(f"Could not analyze your website: {target_profile['error']}")
        st.stop()

    valid_competitors = [p for p in competitor_profiles if not p.get("error")]
    failed = [p for p in competitor_profiles if p.get("error")]
    if not valid_competitors:
        st.error("None of the supplied competitor websites could be analyzed.")
        st.stop()

    result = compare_profiles(target_profile, valid_competitors)
    st.success("Competitive Intelligence analysis completed.")
    if target_profile.get("browser_used"):
        st.caption("✓ Browser-rendered comparison dataset analyzed")

    summary = result["summary"]
    c1, c2, c3, c4 = st.columns(4)
    c1.metric("Your Competitive Score", f"{summary['target_score']}/100")
    c1.caption(f"Readiness: {target_profile['readiness']}")
    c2.metric("Competitor Average", f"{summary['competitor_average']}/100")
    c3.metric("Best Competitor", f"{summary['competitor_best']}/100")
    if summary["position_vs_best"] == "Ahead":
        c4.metric("Lead vs Best Competitor", f"+{summary['lead_over_best']}")
    elif summary["position_vs_best"] == "Behind":
        c4.metric("Gap to Best Competitor", f"{summary['deficit_to_best']}")
    else:
        c4.metric("Position vs Best", "Tied")

    st.caption(
        f"Comparison context: every website in this run uses the same {page_limit}-page browser-rendered crawl limit. "
        "Scores shown here are normalized for this comparison run and can differ from a standalone module audited with a different crawl depth."
    )

    st.subheader("Cross-Site Scorecard")
    domains = [target_profile["domain"]] + [p["domain"] for p in valid_competitors]
    rows = []
    for metric in target_profile["scores"].keys():
        row = {"Metric": metric, domains[0]: target_profile["scores"][metric]}
        for p in valid_competitors:
            row[p["domain"]] = p["scores"].get(metric, 0)
        rows.append(row)
    st.dataframe(rows, use_container_width=True, hide_index=True)

    st.subheader("Evidence Comparison")
    evidence_rows = []
    for profile in [target_profile] + valid_competitors:
        e = profile["evidence"]
        evidence_rows.append({
            "Website": profile["domain"],
            "Pages": profile["pages_crawled"],
            "Avg. Words/Page": e["average_words"],
            "Schema Coverage": f"{e['schema_coverage_percent']}%",
            "Internal Destinations": e["unique_internal_destinations"],
            "Social Profiles": e["social_profiles"],
            "About Signal": "Found" if e["about_signal"] else "Not Found",
            "Contact Signal": "Found" if e["contact_signal"] else "Not Found",
        })
    st.dataframe(evidence_rows, use_container_width=True, hide_index=True)

    st.subheader("Competitive Gaps & Opportunities")
    if result["opportunities"]:
        for item in result["opportunities"]:
            st.write(f"**{item['priority']} — {item['finding']}**")
            st.caption(f"Your score: {item['target']}/100 · Best supplied competitor: {item['competitor_best']}/100 · Service Area: {item['service_area']}")
    else:
        st.success("No 10+ point competitive gaps were detected across the comparison model.")

    st.subheader("Competitive Strengths")
    if result["strengths"]:
        for item in result["strengths"]:
            st.write(f"**{item['metric']}** — advantage of {item['advantage']} points over the strongest supplied competitor.")
    else:
        st.caption("No 10+ point advantage was detected across the supplied comparison set.")

    st.subheader("Metric Gap Detail")
    st.caption("Positive gap = competitor leads; negative gap = your site leads. All rows reuse the same frozen score snapshot shown above.")
    st.dataframe([
        {
            "Metric": r["metric"],
            "Your Score": r["target"],
            "Competitor Average": r["competitor_average"],
            "Competitor Best": r["competitor_best"],
            "Gap to Best": r["gap_to_best"],
        }
        for r in result["comparison"]
    ], use_container_width=True, hide_index=True)

    if failed:
        st.warning("Some competitor URLs could not be analyzed and were excluded from scoring.")
        for item in failed:
            st.caption(f"{item.get('url')}: {item.get('error')}")

    st.info(
        "Competitive Intelligence compares only the websites you supply and only the observable signals collected during this crawl. "
        "It does not measure rankings, traffic, conversions, proprietary backlink indexes, market share or search-engine preference."
    )
