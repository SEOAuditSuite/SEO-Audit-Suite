import streamlit as st

from ui import apply_global_ui
from common import crawl_site, get_robots_sitemap, overall_scores, html_report, parse_sitemap, check_urls, aeo_score

st.title("🧾 Complete SEO Audit Pro V5")
st.caption("One shared browser crawl powers the dashboard, page table and scoring. Scores are SEO Audit Suite measurements — not Google ranking scores.")

url=st.text_input("Website URL",placeholder="https://example.com")
limit=st.slider("Maximum same-domain pages",1,50,10)
render=st.checkbox("Use JavaScript/browser rendering (recommended)",value=True)

if st.button("🚀 Run Professional Audit",type="primary"):
    if not url.strip(): st.error("Please enter a website URL."); st.stop()
    with st.spinner("Rendering pages and building one shared audit dataset…"):
        crawl=crawl_site(url,limit=limit,prefer_browser=render)
    pages=crawl["pages"]
    if not pages:
        st.error("No pages could be audited.")
        if crawl["browser_error"]: st.code(crawl["browser_error"])
        st.stop()

    scores=overall_scores(pages)
    rs=get_robots_sitemap(pages[0].final_url)
    total_schema=sum(bool(p.schema_blocks) for p in pages)
    total_links=sum(len(p.internal_links) for p in pages)
    empty_anchors=sum(sum(i["anchor"]=="(empty anchor)" for i in p.internal_links) for p in pages)
    unique_imgs=len({i.get("src") for p in pages for i in p.images if i.get("src")})
    unique_schema=sorted({t for p in pages for t in p.schema_types})

    cols=st.columns(4)
    cols[0].metric("Overall SEO Health",f"{scores['Overall SEO Health']}/100")
    cols[1].metric("Pages",len(pages)); cols[2].metric("Crawl errors",len(crawl["errors"])); cols[3].metric("Internal links",total_links)

    st.subheader("📊 SEO scorecard")
    score_cols=st.columns(4)
    items=[("Technical SEO",scores["Technical SEO"]),("On-Page SEO",scores["On-Page SEO"]),("Schema",scores["Schema"]),("Image SEO",scores["Image SEO"]),("Social Metadata",scores["Social Metadata"]),("Performance",scores["Performance"]),("AEO Readiness",scores["AEO Readiness"])]
    for idx,(name,val) in enumerate(items):
        score_cols[idx%4].metric(name,f"{val}/100")

    st.info("**Score definitions:** Overall/category scores are calculated from the audit rules in this app. They are not official Google scores. AEO Readiness is a heuristic checklist, not a Google, ChatGPT or AI-search ranking score. Performance here is based on crawl response time; use PageSpeed Insights for Core Web Vitals/Lighthouse data.")
    if crawl["browser_used"]: st.success("Browser rendering active — JavaScript-rendered DOM was audited.")
    else: st.warning("Browser rendering was unavailable; HTML fallback was used.")

    st.subheader("🔎 Site-wide findings")
    findings=[]
    p=pages[0]
    checks=[
      (bool(p.title),"Title tag",f"{len(p.title)} characters" if p.title else "Missing",
       "A clear, unique title helps define the page topic and search intent.",
       "Review the title for uniqueness, relevance and search-intent alignment.","On-Page SEO / Metadata"),
      (bool(p.description),"Meta description",f"{len(p.description)} characters" if p.description else "Missing",
       "A useful description can help users understand the page before visiting from search results.",
       "Review the description for relevance, clarity and whether the most important message appears early enough if truncated.","On-Page SEO / Metadata"),
      (len(p.h1)==1,"Primary H1",f"{len(p.h1)} H1 tag(s)",
       "A clear primary heading helps communicate the main topic and page hierarchy.",
       "Review and optimize the heading hierarchy so the page has one clear primary H1 aligned with its main topic and search intent.","On-Page SEO / Content Optimization"),
      (bool(p.h2),"H2 structure",f"{len(p.h2)} found",
       "Useful subheadings make long content easier to understand and scan.",
       "Review the page structure and add or refine descriptive subheadings where they improve content organization.","On-Page SEO / Content Optimization"),
      (p.word_count>=300,"Content depth",f"Approx. {p.word_count} words",
       "Content should adequately address the page's purpose and search intent; word count alone is not a quality score.",
       "Review search intent, topical coverage and usefulness rather than targeting a fixed word count.","Content SEO / On-Page SEO"),
      (not p.images or all(bool(i.get('alt','').strip()) for i in p.images),"Image ALT coverage",f"{sum(bool(i.get('alt','').strip()) for i in p.images)}/{len(p.images)}",
       "Descriptive ALT text improves accessibility and gives search engines useful context for informative images.",
       "Review image ALT text and add concise, descriptive text to informative images where appropriate.","Image SEO / Accessibility"),
      (bool(p.schema_blocks),"Homepage structured data",f"{', '.join(p.schema_types) or 'No JSON-LD on first page'}",
       "Relevant structured data can help search engines understand eligible page entities and content types.",
       "Audit the homepage for relevant Schema.org opportunities and align any markup with the page's actual content and eligibility.","Technical SEO / Structured Data"),
      (bool(p.og.get('og:title')),"Open Graph", "og:title found" if p.og.get('og:title') else "og:title missing",
       "Open Graph metadata helps control how pages are represented when shared on supported social platforms.",
       "Review social metadata for consistency, accuracy and an appropriate sharing image where relevant.","Social Metadata"),
      (bool(p.twitter.get('twitter:card')),"Twitter/X Card", "twitter:card found" if p.twitter.get('twitter:card') else "twitter:card missing",
       "Card metadata can improve how shared pages are presented on supported X/Twitter surfaces.",
       "Review the X/Twitter card configuration and align title, description and image with the page's social metadata.","Social Metadata"),
      (total_links>0,"Internal linking",f"{total_links} rendered links across {len(pages)} pages",
       "Relevant internal links help users and crawlers discover related content and understand site structure.",
       "Review internal-link coverage and strengthen contextual connections between related pages where useful.","Internal Linking / Technical SEO"),
      (empty_anchors==0,"Empty anchor text",str(empty_anchors),
       "Empty anchors can reduce link context and may create accessibility or navigation concerns when they represent important links.",
       "Review empty-anchor instances and ensure important navigation or content links have meaningful accessible labels.","Technical SEO / Accessibility"),
      (bool(rs.get('robots') and rs['robots']['status']==200),"robots.txt","HTTP 200" if rs.get('robots') else "Unavailable",
       "A reachable robots.txt file helps communicate crawl directives to search-engine crawlers.",
       "Review robots directives for accuracy, unintended blocks and alignment with the site's crawl strategy.","Technical SEO / Crawlability"),
      (bool(rs.get('sitemap') and rs['sitemap']['status']==200),"sitemap.xml","HTTP 200" if rs.get('sitemap') else "Unavailable",
       "An accessible XML sitemap gives search engines a structured list of URLs the site wants discovered.",
       "Review sitemap coverage, freshness and consistency with the site's preferred canonical URLs.","Technical SEO / Indexation"),
    ]
    passes=sum(x[0] for x in checks); reviews=len(checks)-passes
    st.caption(f"{passes} checks passed · {reviews} require review")
    def priority_for(label):
        high={"Primary H1","robots.txt","sitemap.xml"}
        low={"Meta description","Content depth","H2 structure"}
        if label in high: return "HIGH"
        if label in low: return "OPPORTUNITY"
        return "MEDIUM"

    for ok,label,detail,why,action,service in checks:
        with st.container(border=True):
            (st.success if ok else st.warning)(f"{'PASS' if ok else 'REVIEW'} — **{label}** — {detail}")
            if not ok:
                priority=priority_for(label)
                badge={"HIGH":"🔴 HIGH","MEDIUM":"🟠 MEDIUM","OPPORTUNITY":"🟢 OPPORTUNITY"}[priority]
                st.markdown(f"**Priority:** {badge}")
                st.markdown(f"**Why it matters:** {why}")
                st.markdown(f"**Recommended SEO Action:** {action}")
                st.caption(f"Service area: {service}")

    # Business-facing service summary: translate audit findings into service areas without giving away DIY implementation steps.
    service_map = {
        "Primary H1": ("On-Page SEO / Content Optimization", "Review and optimize the homepage heading hierarchy and search-intent alignment."),
        "Meta description": ("On-Page SEO / Metadata", "Review messaging, relevance and SERP presentation of the meta description."),
        "H2 structure": ("On-Page SEO / Content Optimization", "Review subheading structure and content organization for users and search intent."),
        "Content depth": ("Content SEO / On-Page SEO", "Review topical coverage, search intent and usefulness rather than targeting a fixed word count."),
        "Image ALT coverage": ("Image SEO / Accessibility", "Audit informative image ALT text and related image optimization opportunities."),
        "Homepage structured data": ("Technical SEO / Structured Data", "Audit relevant Schema.org opportunities and validate markup against page content."),
        "Open Graph": ("Social Metadata", "Review Open Graph consistency, sharing image and social presentation."),
        "Twitter/X Card": ("Social Metadata", "Review X/Twitter card metadata and consistency with social assets."),
        "Internal linking": ("Internal Linking / Technical SEO", "Review contextual internal-link coverage and opportunities between related pages."),
        "Empty anchor text": ("Internal Linking / Accessibility", "Review empty anchors and improve accessible labels for important links."),
        "robots.txt": ("Technical SEO / Crawlability", "Audit crawl directives for unintended blocks and alignment with the crawl strategy."),
        "sitemap.xml": ("Technical SEO / Indexation", "Audit sitemap coverage, freshness and consistency with preferred canonical URLs."),
    }
    recommended_services=[]
    for item in checks:
        if not item[0]:
            label=item[1]
            svc, _ = service_map.get(label, (item[5], item[4]))
            if svc not in recommended_services:
                recommended_services.append(svc)
    if recommended_services:
        st.subheader("💼 Recommended SEO Services")
        st.caption("These service areas are derived from the audit findings. They are professional service recommendations, not step-by-step DIY instructions.")
        service_cols=st.columns(min(3, max(1,len(recommended_services))))
        for idx, svc in enumerate(recommended_services):
            service_cols[idx % len(service_cols)].markdown(f"**{idx+1}. {svc}**")
    else:
        st.subheader("💼 Recommended SEO Services")
        st.success("No major review findings were generated. Consider a broader SEO strategy, content and growth review based on business goals.")

    st.subheader("🧩 Schema coverage")
    st.write(f"Pages with JSON-LD: **{total_schema}/{len(pages)}**")
    st.write("Detected types: " + (", ".join(unique_schema) if unique_schema else "None in the crawled pages"))
    st.caption("Schema is reported page-by-page. A homepage without JSON-LD does not mean the entire site has no structured data.")

    st.subheader("🔗 Internal-link quality")
    st.write(f"**{empty_anchors}** empty-anchor instances detected. Utility/query URLs are kept visible rather than silently treated as content links.")

    st.subheader("🖼️ Image coverage")
    st.write(f"Rendered image elements: **{sum(len(p.images) for p in pages)}** · unique image URLs: **{unique_imgs}**")

    st.subheader("📄 Crawled pages")
    st.dataframe([{"URL":p.url,"Status":p.status,"Words":p.word_count,"H1":len(p.h1),"H2":len(p.h2),"Images":len(p.images),"Internal links":len(p.internal_links),"Schema":", ".join(p.schema_types) or "None"} for p in pages],use_container_width=True,hide_index=True)
    if crawl["errors"]:
        st.subheader("🚨 Crawl errors"); st.dataframe([{"URL":u,"Status":s,"Details":d} for u,s,d in crawl["errors"]],use_container_width=True,hide_index=True)

    report=html_report(pages[0].final_url,crawl,[x for x in checks if not x[0]],scores)
    st.download_button("📥 Download HTML Client Report",report,file_name="seo-audit-suite-v5-report.html",mime="text/html")
