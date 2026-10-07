import re
from urllib.parse import urlparse

from common import get_robots_sitemap, canonical_url
from aeo_engine import (
    body_text_to_segments,
    run_aeo_analysis,
    analyze_answer_completeness,
    calculate_aeo_score_v2,
)

V6_ENGINE_VERSION = "6.1-evidence-workflow"

IDENTITY_TYPES = {
    "organization", "localbusiness", "corporation", "person", "place",
    "restaurant", "bakery", "store"
}


def _nodes(block):
    if isinstance(block, list):
        return block
    if isinstance(block, dict):
        graph = block.get("@graph")
        return graph if isinstance(graph, list) else [block]
    return []


def _unique(values):
    return list(dict.fromkeys(v for v in values if v))


def build_aeo_v2_for_page(page):
    """One shared AEO 2.0 pipeline used by GEO and cross-module scoring."""
    headings = list(page.h1 or []) + list(page.h2 or []) + list(page.h3 or [])
    paragraphs = body_text_to_segments(page.body_text or "")
    heading_text = " ".join(headings).lower()
    faq_heading = any(x in heading_text for x in (
        "faq", "faqs", "frequently asked questions", "common questions"
    ))
    faq_schema = any(str(x).lower() == "faqpage" for x in (page.schema_types or []))
    faq_present = faq_heading or faq_schema

    result = run_aeo_analysis(
        headings=headings,
        paragraphs=paragraphs,
        lists=page.lists,
        tables=page.tables,
        faq_present=faq_present,
    )
    dom = getattr(page, "aeo_question_answers", []) or []
    if dom:
        questions = [x.get("question", "") for x in dom if x.get("question")]
        result["questions"] = questions
        result["question_count"] = len(questions)
        result["direct_answers"] = dom

    quality = analyze_answer_completeness(result["direct_answers"])
    score = calculate_aeo_score_v2(
        questions=result["questions"],
        direct_answers=result["direct_answers"],
        answer_quality=quality,
        formats=result["formats"],
        faq_present=faq_present,
        schema_types=page.schema_types or [],
    )
    score["answer_quality_detail"] = quality
    score["faq_present"] = faq_present
    return score


def _title_brand(page):
    title = (page.title or "").strip()
    if not title:
        return ""
    # Prefer the site/brand-looking side of common title separators.
    parts = [p.strip() for p in re.split(r"\s*[|–—]\s*", title) if p.strip()]
    candidates = []
    for p in parts:
        words = re.findall(r"[A-Za-z0-9][A-Za-z0-9&'\-]*", p)
        if 1 <= len(words) <= 6:
            candidates.append(p)
    if candidates:
        # A short repeated/brand-like title segment is stronger than a long SEO phrase.
        return min(candidates, key=lambda x: len(x.split()))
    return ""


def analyze_entities(page):
    """Evaluate structured identity plus rendered brand/business evidence."""
    nodes = []
    for block in page.schema_blocks or []:
        nodes.extend(_nodes(block))

    types, schema_names, same_as, ids = set(), [], [], []
    contact_schema = False
    address_schema = False
    for node in nodes:
        if not isinstance(node, dict):
            continue
        raw = node.get("@type", [])
        vals = raw if isinstance(raw, list) else [raw]
        types.update(str(x).lower() for x in vals if x)
        if node.get("name"):
            schema_names.append(str(node["name"]).strip())
        if node.get("@id"):
            ids.append(str(node["@id"]).strip())
        sa = node.get("sameAs", [])
        if isinstance(sa, str):
            sa = [sa]
        same_as.extend(str(x).strip() for x in sa if x)
        contact_schema = contact_schema or bool(
            node.get("telephone") or node.get("email") or node.get("contactPoint")
        )
        address_schema = address_schema or bool(node.get("address"))

    links = (page.internal_links or []) + (page.external_links or [])
    link_text = " ".join(
        f"{x.get('anchor', '')} {x.get('url', '')}" for x in links if isinstance(x, dict)
    ).lower()
    body = (page.body_text or "").lower()

    about_signal = bool(re.search(r"\babout(?:\s+us)?\b", link_text))
    contact_link = bool(re.search(r"\bcontact(?:\s+us)?\b|mailto:|tel:", link_text))
    contact_text = bool(re.search(r"\b(contact us|phone|telephone|email)\b", body))
    address_text = bool(re.search(r"\b(address|location|karachi|lahore|islamabad)\b", body))
    product_service_signal = bool(re.search(
        r"\b(product|products|shop|menu|services?|order|collection|category|categories)\b",
        link_text,
    ))

    rendered_brand = _title_brand(page)
    rendered_names = [rendered_brand] if rendered_brand else []
    names = _unique(schema_names + rendered_names)
    same_as = _unique(same_as)
    ids = _unique(ids)

    identity_schema = bool(types & IDENTITY_TYPES)
    structured_name = bool(schema_names)
    rendered_identity = bool(rendered_brand)
    contact = contact_schema or contact_link or contact_text
    address = address_schema or address_text

    # 100-point transparent model: structured identity remains the strongest evidence,
    # but a clearly rendered brand is no longer treated as "no entity evidence".
    score = 0
    score += 25 if identity_schema else 0
    score += 15 if structured_name else (10 if rendered_identity else 0)
    score += 15 if same_as else 0
    score += 10 if ids else 0
    score += 10 if contact else 0
    score += 10 if address else 0
    score += 10 if about_signal else 0
    score += 5 if product_service_signal else 0
    score = min(score, 100)

    findings = []
    if not identity_schema:
        findings.append(("HIGH", "No clear Organization/LocalBusiness/Person identity schema detected.", "Entity Schema"))
    if not structured_name:
        if rendered_identity:
            findings.append(("MEDIUM", f"Rendered brand evidence was detected ({rendered_brand}), but no structured entity name was found.", "Entity Definition"))
        else:
            findings.append(("HIGH", "No clear structured or rendered entity name was detected.", "Entity Definition"))
    if not same_as:
        findings.append(("MEDIUM", "No sameAs identity references were detected.", "Entity Consistency"))
    if not about_signal:
        findings.append(("OPPORTUNITY", "No clear About-page signal was found in rendered internal links.", "Brand Identity"))

    readiness = "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak"
    return {
        "score": score,
        "readiness": readiness,
        "types": sorted(types),
        "names": names,
        "schema_names": _unique(schema_names),
        "rendered_brand": rendered_brand,
        "same_as": same_as,
        "ids": ids,
        "contact": contact,
        "address": address,
        "about_signal": about_signal,
        "product_service_signal": product_service_signal,
        "findings": findings,
    }


def analyze_ai_crawlers(page, base_url, discovery=None):
    """Inspect the audited URL; unavailable robots evidence remains unknown."""
    from robots_rules import evaluate_robots
    rs = discovery if discovery is not None else get_robots_sitemap(base_url)
    robots, sitemap = rs.get("robots") or {}, rs.get("sitemap") or {}
    code = robots.get("status")
    known = code is not None and 200 <= code < 300
    absent = code in (404, 410)
    # Training controls and user-triggered fetchers are informational, not search penalties.
    bots = {
        "googlebot": "Search crawler",
        "oai-searchbot": "Search crawler",
        "perplexitybot": "Search crawler",
        "gptbot": "Training control",
        "google-extended": "Training / grounding control",
        "claudebot": "Training control",
        "chatgpt-user": "User-triggered fetcher",
    }
    target = page.final_url or base_url
    rows = []
    for bot, purpose in bots.items():
        rule = evaluate_robots(robots.get("text", "") if known else "", bot, target)
        blocked = rule["blocked"] if known else False if absent else None
        rows.append({
            "crawler": bot, "purpose": purpose,
            "explicit_rule": known and rule["group"] == "specific",
            "blocked_url": blocked,
            "group": rule["group"] if known else "none" if absent else "unknown",
            "matched_rule": rule["matched_rule"] if known else "robots.txt absent" if absent else "Not verified",
            "status": ("Blocked for this URL" if blocked else "No matching restriction for this URL")
                      if known else "robots.txt absent; no rules retrieved" if absent else "Unknown: robots.txt not available",
        })
    search_rows = [r for r in rows if r["purpose"] == "Search crawler"]
    blocked = [r["crawler"] for r in search_rows if r["blocked_url"] is True]
    canonical_ok = not page.canonical or canonical_url(page.canonical) == canonical_url(target)
    indexable = not page.noindex
    content_ok = page.word_count >= 100
    sitemap_ok = sitemap.get("status") == 200
    components = [
        ("Search robots rules", 0 if blocked else 100 if known or absent else None, 30),
        ("No generic meta noindex", 100 if indexable else 0, 25),
        ("Canonical consistency", 100 if canonical_ok else 0, 20),
        ("Text availability proxy", 100 if content_ok else 0, 15),
        ("Default sitemap retrieval", 100 if sitemap_ok else 0, 10),
    ]
    weight = sum(w for _, value, w in components if value is not None)
    score = round(sum(value * w for _, value, w in components if value is not None) / weight)
    findings = []
    if not known and not absent:
        findings.append(("MEDIUM", "Robots rules are unverified; excluded from the accessibility score.", "Crawler Access"))
    if blocked:
        findings.append(("HIGH", f"Audited URL has matching Disallow rules for: {', '.join(blocked)}. Confirm intended access before changing rules.", "Search Crawler Access"))
    if not indexable:
        findings.append(("HIGH", "Generic meta noindex/none detected on the audited URL. Confirm intended indexability.", "Indexability"))
    if not canonical_ok:
        findings.append(("MEDIUM", "Canonical points to another URL; verify whether consolidation is intended.", "Canonical"))
    if not sitemap_ok:
        findings.append(("OPPORTUNITY", "Default /sitemap.xml was not retrieved; inspect declared or alternative sitemap locations.", "Discovery"))
    return {
        "score": score, "readiness": "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak",
        "robots_status": code, "sitemap_status": sitemap.get("status"),
        "indexable": indexable, "canonical_ok": canonical_ok,
        "rendered": bool(page.browser_rendered), "content_ok": content_ok,
        "bots": rows, "findings": findings, "errors": rs.get("errors", []),
        "coverage_percent": weight, "evaluated_url": target,
        "limitations": "URL-specific robots rule simulation, not observed bot access. Vendor behavior varies. Generic meta robots only; HTTP X-Robots-Tag, bot-specific meta directives, WAF and login restrictions need separate verification. Training controls do not lower the search score. Rendering mode is informational.",
    }


def calculate_geo(aeo, entity, crawler, page):
    aeo_score = aeo.get("score", 0)
    entity_score = entity.get("score", 0)
    crawler_score = crawler.get("score", 0)
    schema_count = len(page.schema_types or [])
    schema_score = 100 if schema_count >= 4 else 75 if schema_count >= 3 else 50 if schema_count >= 2 else 25 if schema_count == 1 else 0
    links = len(page.internal_links or [])
    linking_score = 100 if links >= 20 else 75 if links >= 10 else 50 if links >= 5 else 25 if links else 0
    relevance = 100 if page.word_count >= 500 else 80 if page.word_count >= 300 else 60 if page.word_count >= 150 else 30 if page.word_count >= 50 else 0
    components = {
        "AEO readiness": (aeo_score, 30),
        "Entity clarity": (entity_score, 20),
        "AI crawler accessibility": (crawler_score, 20),
        "Content length proxy": (relevance, 15),
        "Structured data": (schema_score, 10),
        "Internal linking": (linking_score, 5),
    }
    score = round(sum(v * w / 100 for v, w in components.values()))
    opportunities = []
    for name, (value, weight) in components.items():
        if value < 50:
            opportunities.append(("HIGH" if weight >= 20 else "MEDIUM", f"{name} is a weak GEO signal ({value}/100).", name))
    readiness = "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak"
    return {"score": score, "readiness": readiness, "components": components, "opportunities": opportunities, "limitations": "Content length, schema count and link count are heuristic proxies. They do not measure semantic relevance, schema eligibility, rankings or AI citations. Manual intent and quality review is required."}
