from common import has_parsed_schema
from urllib.parse import urlparse

from common import crawl_site, normalize_url, overall_scores, canonical_url
from v6_intelligence import (
    build_aeo_v2_for_page,
    analyze_entities,
    analyze_ai_crawlers,
    calculate_geo,
)
from v6_trust import analyze_authority, analyze_reputation

COMPETITIVE_ENGINE_VERSION = "6.2-phase3-competitive-fix1"


def _readiness(score):
    if score >= 80:
        return "Strong"
    if score >= 60:
        return "Good"
    if score >= 40:
        return "Developing"
    return "Weak"


def _host(url):
    return urlparse(url or "").netloc.lower().removeprefix("www.")


def _round_mean(values):
    """Round non-negative score averages using conventional .5-up behavior."""
    values = list(values or [])
    if not values:
        return 0
    return int((sum(values) / len(values)) + 0.5)


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


def _schema_coverage_score(percent):
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


def _internal_architecture_score(unique_destinations):
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


def build_competitor_profile(url, crawl_limit=5):
    """Build one comparable profile using the same shared V6 engines."""
    target = normalize_url(url)
    crawl = crawl_site(target, limit=crawl_limit, prefer_browser=True)
    pages = crawl.get("pages", [])
    if not pages:
        return {
            "url": target,
            "domain": _host(target),
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
    schema_pages = sum(1 for p in pages if has_parsed_schema(p))
    schema_coverage = round(schema_pages / len(pages) * 100) if pages else 0
    unique_destinations = len({
        canonical_url(item.get("url", ""))
        for p in pages
        for item in (p.internal_links or [])
        if isinstance(item, dict) and item.get("url")
    })

    comparable = {
        "SEO": seo.get("Overall SEO Health", 0),
        "AEO": aeo.get("score", 0),
        "GEO": geo.get("score", 0),
        "Entity": entity.get("score", 0),
        "Crawler Access": crawler.get("score", 0),
        "Authority": authority.get("score", 0),
        "Reputation": reputation.get("score", 0),
        "Content length proxy": _content_score(avg_words),
        "Schema Coverage": _schema_coverage_score(schema_coverage),
        "Internal Architecture": _internal_architecture_score(unique_destinations),
    }

    composite = round(sum(comparable.values()) / len(comparable))

    return {
        "url": target,
        "domain": _host(home.final_url or target),
        "final_url": home.final_url,
        "pages_crawled": len(pages),
        "crawl_errors": len(crawl.get("errors", [])),
        "browser_used": bool(crawl.get("browser_used")),
        "scores": comparable,
        "competitive_score": composite,
        "readiness": _readiness(composite),
        "evidence": {
            "average_words": avg_words,
            "schema_coverage_percent": schema_coverage,
            "unique_internal_destinations": unique_destinations,
            "schema_types": sorted({t for p in pages for t in (p.schema_types or [])}),
            "social_profiles": len(reputation.get("evidence", {}).get("social_profiles", [])),
            "about_signal": authority.get("evidence", {}).get("about_signal", False),
            "contact_signal": authority.get("evidence", {}).get("contact_signal", False),
        },
        "raw": {
            "seo": seo,
            "aeo": aeo,
            "entity": entity,
            "crawler": crawler,
            "geo": geo,
            "authority": authority,
            "reputation": reputation,
        },
        "crawl": crawl,
        "error": "",
    }


def compare_profiles(target_profile, competitor_profiles):
    competitors = [p for p in competitor_profiles if p and not p.get("error")]
    if not target_profile or target_profile.get("error"):
        return {"comparison": [], "opportunities": [], "strengths": [], "summary": {}}

    target_scores = target_profile.get("scores", {})
    rows = []
    opportunities = []
    strengths = []

    for metric, target_value in target_scores.items():
        values = [p.get("scores", {}).get(metric, 0) for p in competitors]
        if values:
            best = max(values)
            avg = _round_mean(values)
            gap_to_best = best - target_value
            gap_to_avg = avg - target_value
        else:
            best = avg = target_value
            gap_to_best = gap_to_avg = 0

        rows.append({
            "metric": metric,
            "target": target_value,
            "competitor_average": avg,
            "competitor_best": best,
            "gap_to_best": gap_to_best,
        })

        if gap_to_best >= 20:
            priority = "HIGH"
        elif gap_to_best >= 10:
            priority = "MEDIUM"
        else:
            priority = ""

        if priority:
            opportunities.append({
                "priority": priority,
                "metric": metric,
                "target": target_value,
                "competitor_best": best,
                "gap": gap_to_best,
                "finding": f"{metric} trails the strongest supplied competitor by {gap_to_best} points.",
                "service_area": _service_area(metric),
            })
        elif target_value >= best + 10 and competitors:
            strengths.append({
                "metric": metric,
                "target": target_value,
                "competitor_best": best,
                "advantage": target_value - best,
            })

    opportunities.sort(key=lambda x: (0 if x["priority"] == "HIGH" else 1, -x["gap"]))
    strengths.sort(key=lambda x: -x["advantage"])

    competitor_scores = [p.get("competitive_score", 0) for p in competitors]
    target_comp = target_profile.get("competitive_score", 0)
    best_comp = max(competitor_scores) if competitor_scores else target_comp
    avg_comp = _round_mean(competitor_scores) if competitor_scores else target_comp
    signed_difference = target_comp - best_comp
    lead_over_best = max(signed_difference, 0)
    deficit_to_best = max(-signed_difference, 0)

    return {
        "comparison": rows,
        "opportunities": opportunities,
        "strengths": strengths,
        "summary": {
            "target_score": target_comp,
            "competitor_average": avg_comp,
            "competitor_best": best_comp,
            "signed_difference_vs_best": signed_difference,
            "lead_over_best": lead_over_best,
            "deficit_to_best": deficit_to_best,
            "position_vs_best": (
                "Ahead" if signed_difference > 0
                else "Behind" if signed_difference < 0
                else "Tied"
            ),
            "competitors_analyzed": len(competitors),
        },
    }


def _service_area(metric):
    mapping = {
        "SEO": "Technical / On-Page SEO",
        "AEO": "AEO / Answer Optimization",
        "GEO": "GEO / AI Search Readiness",
        "Entity": "Entity SEO / Structured Identity",
        "Crawler Access": "AI Crawler Accessibility",
        "Authority": "Authority / Trust Foundations",
        "Reputation": "Reputation / Social Proof",
        "Content length proxy": "Content Strategy",
        "Schema Coverage": "Structured Data",
        "Internal Architecture": "Internal Linking / Information Architecture",
    }
    return mapping.get(metric, metric)
