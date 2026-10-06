import re
from urllib.parse import urlparse

from common import get_robots_sitemap, canonical_url
from aeo_engine import (
    body_text_to_segments,
    run_aeo_analysis,
    analyze_answer_completeness,
    calculate_aeo_score_v2,
)

V6_ENGINE_VERSION = "6.1-phase1-integration"

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


def _robots_groups(text):
    groups, agents, rules = [], [], []
    for raw in (text or "").splitlines():
        line = raw.split("#", 1)[0].strip()
        if not line or ":" not in line:
            continue
        k, v = [x.strip() for x in line.split(":", 1)]
        k = k.lower()
        if k == "user-agent":
            if agents and rules:
                groups.append((agents, rules)); agents, rules = [], []
            agents.append(v.lower())
        elif k in ("allow", "disallow") and agents:
            rules.append((k, v))
    if agents:
        groups.append((agents, rules))
    return groups


def analyze_ai_crawlers(page, base_url):
    rs = get_robots_sitemap(base_url)
    robots, sitemap = rs.get("robots") or {}, rs.get("sitemap") or {}
    groups = _robots_groups(robots.get("text", ""))
    bots = ["gptbot", "oai-searchbot", "chatgpt-user", "google-extended", "claudebot", "perplexitybot"]
    bot_rows = []
    for bot in bots:
        matching = [rules for agents, rules in groups if bot in agents]
        explicit = bool(matching)
        blocked = any(
            k == "disallow" and v.strip() == "/"
            for rules in matching for k, v in rules
        )
        bot_rows.append({
            "crawler": bot,
            "explicit_rule": explicit,
            "blocked_all": blocked,
            "status": "Explicitly blocked" if blocked else "No full-site block detected",
        })

    robots_ok = robots.get("status") == 200
    sitemap_ok = sitemap.get("status") == 200
    canonical_ok = not page.canonical or canonical_url(page.canonical) == canonical_url(page.final_url)
    indexable = not page.noindex
    content_ok = page.word_count >= 100
    rendered = bool(page.browser_rendered)
    score = sum([
        15 if robots_ok else 0, 15 if sitemap_ok else 0, 20 if indexable else 0,
        15 if canonical_ok else 0, 20 if content_ok else 0, 15 if rendered else 0,
    ])
    blocked = [x["crawler"] for x in bot_rows if x["blocked_all"]]
    if blocked:
        score = max(0, score - min(30, 5 * len(blocked)))

    findings = []
    if not robots_ok:
        findings.append(("HIGH", "robots.txt was not successfully retrieved.", "Crawler Access"))
    if blocked:
        findings.append(("HIGH", f"Full-site blocking detected for: {', '.join(blocked)}.", "AI Crawler Access"))
    if not indexable:
        findings.append(("HIGH", "The audited page carries a noindex signal.", "Indexability"))
    if not canonical_ok:
        findings.append(("MEDIUM", "Canonical does not match the rendered final URL.", "Canonical Consistency"))
    if not sitemap_ok:
        findings.append(("MEDIUM", "sitemap.xml was not successfully retrieved.", "Discovery"))

    readiness = "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak"
    return {
        "score": min(score, 100), "readiness": readiness,
        "robots_status": robots.get("status"), "sitemap_status": sitemap.get("status"),
        "indexable": indexable, "canonical_ok": canonical_ok, "rendered": rendered,
        "content_ok": content_ok, "bots": bot_rows, "findings": findings,
        "errors": rs.get("errors", []),
    }


def calculate_geo(aeo, entity, crawler, page):
    aeo_score = aeo.get("score", 0)
    entity_score = entity.get("score", 0)
    crawler_score = crawler.get("score", 0)
    schema_count = len(page.schema_types or [])
    schema_score = 100 if schema_count >= 4 else 75 if schema_count >= 3 else 50 if schema_count >= 2 else 25 if schema_count == 1 else 0
    links = len(page.internal_links or [])
    linking_score = 100 if links >= 20 else 75 if links >= 10 else 50 if links >= 5 else 25 if links else 0
    relevance = 100 if page.word_count >= 500 else 80 if page.word_count >= 300 else 60 if page.word_count >= 150 else 30 if page.word_count >= 50 else 10
    components = {
        "AEO readiness": (aeo_score, 30),
        "Entity clarity": (entity_score, 20),
        "AI crawler accessibility": (crawler_score, 20),
        "Content relevance": (relevance, 15),
        "Structured data": (schema_score, 10),
        "Internal linking": (linking_score, 5),
    }
    score = round(sum(v * w / 100 for v, w in components.values()))
    opportunities = []
    for name, (value, weight) in components.items():
        if value < 50:
            opportunities.append(("HIGH" if weight >= 20 else "MEDIUM", f"{name} is a weak GEO signal ({value}/100).", name))
    readiness = "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak"
    return {"score": score, "readiness": readiness, "components": components, "opportunities": opportunities}
