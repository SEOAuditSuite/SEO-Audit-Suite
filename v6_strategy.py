from urllib.parse import urlparse

from common import crawl_site, normalize_url, overall_scores, canonical_url
from v6_intelligence import (
    build_aeo_v2_for_page,
    analyze_entities,
    analyze_ai_crawlers,
    calculate_geo,
)
from v6_trust import analyze_authority, analyze_reputation

STRATEGY_ENGINE_VERSION = "6.3-phase4-ai-search-strategy"


def _readiness(score):
    if score >= 80:
        return "Strong"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Developing"
    return "Weak"


def _content_score(avg_words):
    if avg_words >= 500:
        return 100
    if avg_words >= 300:
        return 80
    if avg_words >= 150:
        return 60
    if avg_words >= 50:
        return 30
    return 10 if avg_words else 0


def _schema_score(percent):
    if percent >= 80:
        return 100
    if percent >= 60:
        return 85
    if percent >= 40:
        return 70
    if percent >= 20:
        return 50
    if percent > 0:
        return 25
    return 0


def _internal_score(unique_destinations):
    if unique_destinations >= 40:
        return 100
    if unique_destinations >= 25:
        return 80
    if unique_destinations >= 15:
        return 65
    if unique_destinations >= 8:
        return 45
    if unique_destinations >= 3:
        return 25
    return 10 if unique_destinations else 0


def _priority(score):
    if score < 35:
        return "HIGH"
    if score < 60:
        return "MEDIUM"
    if score < 80:
        return "OPPORTUNITY"
    return "STRONG"


def build_ai_search_audit(url, crawl_limit=10):
    target = normalize_url(url)
    crawl = crawl_site(target, limit=crawl_limit, prefer_browser=True)
    pages = crawl.get("pages", [])
    if not pages:
        return {
            "url": target,
            "error": "No crawlable pages were available.",
            "crawl": crawl,
        }

    home = pages[0]
    seo = overall_scores(pages)
    aeo = build_aeo_v2_for_page(home)
    entity = analyze_entities(home)
    crawler = analyze_ai_crawlers(home, home.final_url or target)
    geo = calculate_geo(aeo, entity, crawler, home)
    authority = analyze_authority(pages)
    reputation = analyze_reputation(pages)

    avg_words = round(sum(p.word_count for p in pages) / len(pages)) if pages else 0
    schema_pages = sum(1 for p in pages if p.schema_blocks)
    schema_coverage = round(schema_pages / len(pages) * 100) if pages else 0
    unique_internal = len({
        canonical_url(item.get("url", ""))
        for p in pages
        for item in (p.internal_links or [])
        if isinstance(item, dict) and item.get("url")
    })

    content_depth = _content_score(avg_words)
    structured_data = _schema_score(schema_coverage)
    internal_architecture = _internal_score(unique_internal)

    components = {
        "AEO readiness": (aeo.get("score", 0), 25),
        "Entity clarity": (entity.get("score", 0), 15),
        "AI crawler accessibility": (crawler.get("score", 0), 15),
        "Structured data coverage": (structured_data, 10),
        "Content depth": (content_depth, 10),
        "Internal architecture": (internal_architecture, 10),
        "Authority foundations": (authority.get("score", 0), 10),
        "Reputation foundations": (reputation.get("score", 0), 5),
    }

    weighted = sum(score * weight / 100 for score, weight in components.values())
    ai_search_score = round(weighted)

    findings = []
    service_map = {
        "AEO readiness": "AEO / Answer Optimization",
        "Entity clarity": "Entity SEO / Structured Identity",
        "AI crawler accessibility": "AI Crawler Accessibility",
        "Structured data coverage": "Structured Data",
        "Content depth": "Content Strategy",
        "Internal architecture": "Internal Linking / Information Architecture",
        "Authority foundations": "Authority / Trust Foundations",
        "Reputation foundations": "Reputation / Social Proof",
    }
    for name, (score, weight) in components.items():
        p = _priority(score)
        if p == "STRONG":
            continue
        findings.append({
            "priority": p,
            "signal": name,
            "score": score,
            "weight": weight,
            "finding": f"{name} is currently {score}/100 in the AI Search Audit model.",
            "service_area": service_map[name],
        })

    order = {"HIGH": 0, "MEDIUM": 1, "OPPORTUNITY": 2}
    findings.sort(key=lambda x: (order.get(x["priority"], 9), x["score"]))

    return {
        "url": target,
        "domain": urlparse(home.final_url or target).netloc.lower().removeprefix("www."),
        "error": "",
        "score": ai_search_score,
        "readiness": _readiness(ai_search_score),
        "components": components,
        "findings": findings,
        "pages_crawled": len(pages),
        "crawl_errors": len(crawl.get("errors", [])),
        "browser_used": bool(crawl.get("browser_used")),
        "evidence": {
            "average_words": avg_words,
            "schema_pages": schema_pages,
            "schema_coverage_percent": schema_coverage,
            "unique_internal_destinations": unique_internal,
            "schema_types": sorted({t for p in pages for t in (p.schema_types or [])}),
            "about_signal": authority.get("evidence", {}).get("about_signal", False),
            "contact_signal": authority.get("evidence", {}).get("contact_signal", False),
            "social_profiles": reputation.get("evidence", {}).get("social_profiles", []),
        },
        "raw": {
            "seo": seo,
            "aeo": aeo,
            "geo": geo,
            "entity": entity,
            "crawler": crawler,
            "authority": authority,
            "reputation": reputation,
        },
        "crawl": crawl,
        "disclaimer": (
            "AI Search Audit Score is an application-defined synthesis of observable website signals. "
            "It is not an official score from Google, OpenAI, Bing, Perplexity or another AI/search platform, "
            "and it does not predict rankings, citations or traffic."
        ),
    }


def build_30_60_day_strategy(audit):
    """Build a prioritized service roadmap from one AI Search Audit result."""
    if not audit or audit.get("error"):
        return {"first_30_days": [], "days_31_60": [], "summary": {}}

    components = audit.get("components", {})
    scores = {name: value[0] for name, value in components.items()}

    first = []
    second = []

    def add(bucket, priority, area, action, reason, success_signal):
        bucket.append({
            "priority": priority,
            "service_area": area,
            "recommended_action": action,
            "why_it_matters": reason,
            "success_signal": success_signal,
        })

    if scores.get("AI crawler accessibility", 100) < 80:
        add(first, "HIGH", "AI Crawler Accessibility",
            "Resolve crawler-access, robots, canonical or indexability barriers affecting important pages.",
            "AI/search systems cannot reliably evaluate content they cannot access or index.",
            "Important audited pages are crawlable, indexable and technically consistent.")

    if scores.get("Entity clarity", 100) < 60:
        add(first, "HIGH", "Entity SEO / Structured Identity",
            "Strengthen business/entity definition with consistent identity signals and appropriate structured data.",
            "Clear entity identity helps systems connect the brand, organization, location and site content.",
            "Entity score improves and structured identity evidence is consistently detected.")

    if scores.get("Structured data coverage", 100) < 60:
        add(first, "HIGH", "Structured Data",
            "Expand valid page-appropriate Schema.org coverage across priority templates and content types.",
            "Structured data provides machine-readable context for entities and eligible content.",
            "A larger share of priority pages contains valid relevant structured data.")

    if scores.get("AEO readiness", 100) < 60:
        add(first, "HIGH", "AEO / Answer Optimization",
            "Create and refine question-led sections with concise answer-first responses on priority pages.",
            "Direct, self-contained answers improve answer-engine readability and content usefulness.",
            "More meaningful questions have verified nearby direct answers and stronger answer-quality scores.")

    if scores.get("Internal architecture", 100) < 60:
        add(first, "MEDIUM", "Internal Linking / Information Architecture",
            "Improve contextual internal linking between important categories, services, products and supporting content.",
            "Clear internal relationships help discovery, context and topical navigation.",
            "Priority destinations receive stronger contextual internal-link coverage.")

    if scores.get("Content depth", 100) < 60:
        add(first, "MEDIUM", "Content Strategy",
            "Strengthen thin priority pages with useful intent-matched information rather than filler text.",
            "Substantive page content gives search and AI systems more evidence to interpret and answer from.",
            "Priority pages show stronger useful-content depth and clearer intent coverage.")

    if scores.get("Authority foundations", 100) < 80:
        add(second, "MEDIUM", "Authority / Trust Foundations",
            "Strengthen About, editorial ownership, source/citation and trust-policy signals across the site.",
            "Authority foundations help users and machines understand who is responsible for the content and business.",
            "More authority evidence is detected consistently across crawled pages.")

    if scores.get("Reputation foundations", 100) < 80:
        add(second, "MEDIUM", "Reputation / Social Proof",
            "Strengthen verifiable review, testimonial, profile and reputation evidence where appropriate.",
            "Independent and on-site reputation signals can reinforce trust and brand credibility.",
            "Audit detects stronger social-proof and reputation evidence without relying on unsupported claims.")

    if scores.get("AEO readiness", 100) < 80:
        add(second, "OPPORTUNITY", "AEO Content Expansion",
            "Expand high-value question coverage around commercial, informational and support intents.",
            "Broader answer coverage can improve the site's usefulness for answer-oriented discovery.",
            "Question coverage and direct-answer completeness improve across priority content.")

    add(second, "OPPORTUNITY", "Measurement & Validation",
        "Re-run SEO, AEO, GEO, entity, crawler, authority and reputation audits after implementation and compare evidence changes.",
        "A repeatable evidence baseline is needed to distinguish implementation progress from assumptions.",
        "Updated audits show documented signal improvements; rankings or AI citations are tracked separately in external platforms.")

    if not first:
        add(first, "OPPORTUNITY", "Foundation Maintenance",
            "Preserve current technical and AI-search foundations while validating priority templates for consistency.",
            "Strong baseline signals still require maintenance as templates and content change.",
            "Core audit scores remain stable or improve across repeat crawls.")

    return {
        "first_30_days": first,
        "days_31_60": second,
        "summary": {
            "starting_score": audit.get("score", 0),
            "readiness": audit.get("readiness", "Weak"),
            "high_priority_actions": sum(1 for x in first + second if x["priority"] == "HIGH"),
            "medium_priority_actions": sum(1 for x in first + second if x["priority"] == "MEDIUM"),
            "opportunities": sum(1 for x in first + second if x["priority"] == "OPPORTUNITY"),
        },
        "disclaimer": (
            "This 30/60-day roadmap is generated from the observable audit evidence in this run. "
            "It is a prioritization framework, not a guarantee of rankings, traffic, conversions or AI citations."
        ),
    }
