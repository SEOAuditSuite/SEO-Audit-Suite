import re
from collections import Counter
from urllib.parse import urlparse

from bs4 import BeautifulSoup

from common import fetch, canonical_url, same_domain

TRUST_ENGINE_VERSION = "6.2-phase2-authority-reputation-fix1"

IDENTITY_SCHEMA_TYPES = {
    "organization", "localbusiness", "corporation", "person", "restaurant",
    "store", "bakery", "professionalservice", "website"
}
AUTHOR_SCHEMA_TYPES = {"person", "article", "newsarticle", "blogposting"}
REPUTATION_SCHEMA_TYPES = {"review", "aggregaterating", "product", "localbusiness", "organization"}
SOCIAL_HOSTS = (
    "facebook.com", "instagram.com", "linkedin.com", "youtube.com", "youtu.be",
    "x.com", "twitter.com", "tiktok.com", "pinterest.com"
)
POLICY_TERMS = ("privacy", "terms", "refund", "return", "shipping", "policy")


def _clean(value):
    return re.sub(r"\s+", " ", str(value or "")).strip()


def _flatten_schema(page):
    nodes = []
    for block in page.schema_blocks or []:
        if isinstance(block, list):
            candidates = block
        elif isinstance(block, dict):
            graph = block.get("@graph")
            candidates = graph if isinstance(graph, list) else [block]
        else:
            candidates = []
        nodes.extend(x for x in candidates if isinstance(x, dict))
    return nodes


def _schema_types(nodes):
    result = set()
    for node in nodes:
        raw = node.get("@type", [])
        vals = raw if isinstance(raw, list) else [raw]
        result.update(str(v).lower() for v in vals if v)
    return result


def _links(pages):
    internal, external = [], []
    for page in pages:
        internal.extend(page.internal_links or [])
        external.extend(page.external_links or [])
    return internal, external


def _link_blob(links):
    return " ".join(
        f"{_clean(x.get('anchor'))} {_clean(x.get('url'))}"
        for x in links if isinstance(x, dict)
    ).lower()


def _body_blob(pages):
    return " ".join(_clean(p.body_text) for p in pages).lower()


SOCIAL_UTILITY_PATH_MARKERS = (
    "/sharer", "/share", "/intent/", "/dialog/", "/login", "/signin",
    "/oauth", "/plugins/", "/widgets/", "/embed/", "/search",
)

SOCIAL_UTILITY_QUERY_KEYS = {
    "u", "url", "share", "text", "redirect", "redirect_uri", "next"
}


def _is_social_profile_url(url):
    """Return True only for plausible public social profile/channel URLs.

    Share endpoints, login/intent URLs, embeds and other utility links are
    intentionally excluded so they do not inflate reputation signals.
    """
    url = _clean(url)
    if not url:
        return False

    parsed = urlparse(url)
    host = parsed.netloc.lower().removeprefix("www.")
    path = (parsed.path or "").lower()
    query = (parsed.query or "").lower()

    if not any(host == domain or host.endswith("." + domain) for domain in SOCIAL_HOSTS):
        return False

    if any(marker in path for marker in SOCIAL_UTILITY_PATH_MARKERS):
        return False

    # Common share URLs can also be query-driven even when the path is short.
    if any(f"{key}=" in query for key in SOCIAL_UTILITY_QUERY_KEYS) and (
        "share" in path or "intent" in path or "sharer" in path
    ):
        return False

    # A bare social-network homepage is not evidence of the audited brand's profile.
    if path in ("", "/"):
        return False

    return True


def _social_profiles(external_links):
    found = []
    for item in external_links:
        if not isinstance(item, dict):
            continue
        url = _clean(item.get("url"))
        if _is_social_profile_url(url):
            found.append(url)
    return list(dict.fromkeys(found))


def _brand_from_pages(pages):
    if not pages:
        return ""
    title = _clean(pages[0].title)
    if not title:
        return ""
    pieces = [p.strip() for p in re.split(r"\s*[|–—]\s*", title) if p.strip()]
    short = [p for p in pieces if 1 <= len(p.split()) <= 6]
    return min(short, key=lambda x: len(x.split())) if short else pieces[0]


def analyze_authority(pages):
    """
    Score on-site authority foundations only.

    This does not estimate proprietary domain authority, PageRank, backlink power,
    or third-party authority metrics. External evidence is handled separately.
    """
    pages = pages or []
    if not pages:
        return {
            "score": 0, "readiness": "Weak", "evidence": {}, "findings": [],
            "disclaimer": "No crawl evidence was available."
        }

    all_nodes = []
    all_types = set()
    schema_pages = 0
    author_pages = 0
    for p in pages:
        nodes = _flatten_schema(p)
        types = _schema_types(nodes)
        all_nodes.extend(nodes)
        all_types.update(types)
        if types:
            schema_pages += 1
        if types & AUTHOR_SCHEMA_TYPES:
            author_pages += 1

    internal, external = _links(pages)
    internal_blob = _link_blob(internal)
    body = _body_blob(pages)

    https_ok = all((p.final_url or p.url or "").lower().startswith("https://") for p in pages)
    about_signal = bool(re.search(r"\babout(?:\s+us)?\b", internal_blob))
    contact_signal = bool(re.search(r"\bcontact(?:\s+us)?\b|mailto:|tel:", internal_blob)) or bool(
        re.search(r"\b(contact us|telephone|phone|email)\b", body)
    )
    policy_signal = any(term in internal_blob for term in POLICY_TERMS)
    identity_schema = bool(all_types & IDENTITY_SCHEMA_TYPES)
    author_signal = author_pages > 0 or bool(re.search(r"\b(author|written by|reviewed by)\b", body))

    # Outbound citations: non-social external links with descriptive anchors.
    citation_links = []
    for item in external:
        if not isinstance(item, dict):
            continue
        url = _clean(item.get("url"))
        anchor = _clean(item.get("anchor"))
        host = urlparse(url).netloc.lower().removeprefix("www.")
        if any(host == d or host.endswith("." + d) for d in SOCIAL_HOSTS):
            continue
        if anchor and anchor != "(empty anchor)":
            citation_links.append(url)
    citation_domains = sorted({urlparse(u).netloc.lower().removeprefix("www.") for u in citation_links if u})

    avg_words = round(sum(p.word_count for p in pages) / len(pages)) if pages else 0
    depth_signal = avg_words >= 300
    internal_signal = len({canonical_url(x.get("url", "")) for x in internal if x.get("url")}) >= 10
    schema_coverage = round(schema_pages / len(pages) * 100) if pages else 0

    components = {
        "HTTPS foundation": (10 if https_ok else 0, 10),
        "About identity": (15 if about_signal else 0, 15),
        "Contact transparency": (10 if contact_signal else 0, 10),
        "Identity schema": (15 if identity_schema else 0, 15),
        "Author/editorial signals": (15 if author_signal else 0, 15),
        "External citations": (10 if citation_domains else 0, 10),
        "Content depth": (10 if depth_signal else (5 if avg_words >= 150 else 0), 10),
        "Trust/policy pages": (5 if policy_signal else 0, 5),
        "Internal architecture": (5 if internal_signal else 0, 5),
        "Structured data coverage": (5 if schema_coverage >= 50 else 3 if schema_coverage >= 20 else 0, 5),
    }
    score = sum(v for v, _ in components.values())
    readiness = "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak"

    findings = []
    if not about_signal:
        findings.append(("HIGH", "No clear About-page signal was detected across the crawled site.", "Brand / Entity Authority"))
    if not identity_schema:
        findings.append(("HIGH", "No clear Organization/LocalBusiness/Person identity schema was detected in the crawl.", "Structured Entity Authority"))
    if not author_signal:
        findings.append(("MEDIUM", "No strong author/editorial ownership signal was detected.", "Editorial Authority"))
    if not citation_domains:
        findings.append(("MEDIUM", "No clear non-social external citation pattern was detected.", "Source & Citation Quality"))
    if not policy_signal:
        findings.append(("OPPORTUNITY", "Trust/policy navigation signals were limited or not detected.", "Trust Foundations"))

    return {
        "score": score,
        "readiness": readiness,
        "components": components,
        "evidence": {
            "pages_crawled": len(pages),
            "average_words": avg_words,
            "schema_coverage_percent": schema_coverage,
            "identity_schema": identity_schema,
            "author_signal": author_signal,
            "about_signal": about_signal,
            "contact_signal": contact_signal,
            "policy_signal": policy_signal,
            "citation_domains": citation_domains,
            "citation_count": len(citation_links),
            "internal_destinations": len({canonical_url(x.get("url", "")) for x in internal if x.get("url")}),
            "schema_types": sorted(all_types),
        },
        "findings": findings,
        "disclaimer": (
            "Authority Score is an application-defined audit of observable on-site authority foundations. "
            "It is not Google PageRank, Moz DA, Ahrefs DR, Semrush Authority Score, or a backlink-quality metric."
        ),
    }


def analyze_reputation(pages):
    """Evaluate observable on-site reputation and trust signals."""
    pages = pages or []
    if not pages:
        return {"score": 0, "readiness": "Weak", "evidence": {}, "findings": []}

    nodes = []
    all_types = set()
    for p in pages:
        n = _flatten_schema(p)
        nodes.extend(n)
        all_types.update(_schema_types(n))

    internal, external = _links(pages)
    internal_blob = _link_blob(internal)
    body = _body_blob(pages)
    social = _social_profiles(external)

    review_schema = bool(all_types & {"review", "aggregaterating"})
    review_text = bool(re.search(r"\b(review|reviews|testimonial|testimonials|rating|rated|customer feedback)\b", body))
    social_signal = len(social) >= 2
    contact_signal = bool(re.search(r"\bcontact(?:\s+us)?\b|mailto:|tel:", internal_blob)) or bool(
        re.search(r"\b(contact us|telephone|phone|email)\b", body)
    )
    address_signal = bool(re.search(r"\b(address|location|karachi|lahore|islamabad)\b", body))
    about_signal = bool(re.search(r"\babout(?:\s+us)?\b", internal_blob))
    policy_signal = any(term in internal_blob for term in POLICY_TERMS)
    brand = _brand_from_pages(pages)
    brand_presence = bool(brand and sum(1 for p in pages if brand.lower() in (p.title or "").lower()) >= max(1, len(pages) // 2))

    components = {
        "Review/rating schema": (20 if review_schema else 0, 20),
        "Review/testimonial content": (15 if review_text else 0, 15),
        "Social profile footprint": (20 if social_signal else 10 if social else 0, 20),
        "Contact transparency": (15 if contact_signal else 0, 15),
        "Address/location clarity": (10 if address_signal else 0, 10),
        "About/identity signal": (10 if about_signal else 0, 10),
        "Policy/trust pages": (5 if policy_signal else 0, 5),
        "Brand consistency": (5 if brand_presence else 0, 5),
    }
    score = sum(v for v, _ in components.values())
    readiness = "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak"

    findings = []
    if not review_schema:
        findings.append(("MEDIUM", "No Review or AggregateRating schema signal was detected in the crawled pages.", "Reputation Structured Data"))
    if not review_text:
        findings.append(("MEDIUM", "No clear review/testimonial content signal was detected in the crawl.", "Social Proof"))
    if not social_signal:
        findings.append(("MEDIUM", "A broad multi-platform social profile footprint was not detected from rendered external links.", "Social Reputation"))
    if not about_signal:
        findings.append(("OPPORTUNITY", "No clear About-page signal was detected in rendered navigation.", "Brand Trust"))

    return {
        "score": score,
        "readiness": readiness,
        "components": components,
        "evidence": {
            "brand": brand,
            "review_schema": review_schema,
            "review_text_signal": review_text,
            "social_profiles": social,
            "contact_signal": contact_signal,
            "address_signal": address_signal,
            "about_signal": about_signal,
            "policy_signal": policy_signal,
            "brand_consistency": brand_presence,
            "schema_types": sorted(all_types),
        },
        "findings": findings,
        "disclaimer": (
            "Reputation Score is based on observable website signals only. It does not automatically measure "
            "Google reviews, marketplace ratings, sentiment across the web, or brand mentions unless external evidence is supplied."
        ),
    }


def _visible_text(soup):
    for tag in soup.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return _clean(soup.get_text(" ", strip=True))


def verify_external_mention(target_url, brand_name, mention_url, timeout=20):
    target_url = _clean(target_url)
    brand_name = _clean(brand_name)
    mention_url = _clean(mention_url)
    row = {
        "url": mention_url,
        "domain": urlparse(mention_url).netloc.lower().removeprefix("www."),
        "status": 0,
        "brand_mentioned": False,
        "backlink_found": False,
        "followed_backlink": False,
        "link_rel": "",
        "final_url": "",
        "error": "",
    }
    if not mention_url:
        row["error"] = "Empty URL"
        return row
    try:
        response = fetch(mention_url, timeout=timeout)
        row["status"] = response.status_code
        row["final_url"] = response.url
        soup = BeautifulSoup(response.text or "", "html.parser")
        text = _visible_text(soup).lower()
        row["brand_mentioned"] = bool(brand_name and brand_name.lower() in text)

        target_host = urlparse(target_url).netloc.lower().removeprefix("www.")
        best_rel = ""
        backlink = False
        followed = False
        for a in soup.find_all("a", href=True):
            href = _clean(a.get("href"))
            if not href:
                continue
            href_host = urlparse(href).netloc.lower().removeprefix("www.")
            if not href_host and href.startswith("/"):
                continue
            if href_host == target_host or href_host.endswith("." + target_host):
                backlink = True
                rel_raw = a.get("rel") or []
                rels = [str(x).lower() for x in (rel_raw if isinstance(rel_raw, list) else [rel_raw])]
                best_rel = " ".join(rels)
                if not any(x in rels for x in ("nofollow", "sponsored", "ugc")):
                    followed = True
                    break
        row["backlink_found"] = backlink
        row["followed_backlink"] = followed
        row["link_rel"] = best_rel or ("follow" if backlink and followed else "")
    except Exception as exc:
        row["error"] = str(exc)
    return row


def summarize_external_mentions(rows):
    rows = rows or []
    if not rows:
        return {
            "score": None,
            "readiness": "Evidence required",
            "components": {},
            "evidence": {},
            "findings": [("INFO", "Add external mention URLs or a CSV to verify brand mentions and backlinks.", "External Evidence")],
        }

    reachable = [r for r in rows if 200 <= int(r.get("status") or 0) < 400]
    mentioned = [r for r in reachable if r.get("brand_mentioned")]
    backlinks = [r for r in reachable if r.get("backlink_found")]
    followed = [r for r in backlinks if r.get("followed_backlink")]

    supplied_domains = {r.get("domain") for r in rows if r.get("domain")}
    fetched_domains = {r.get("domain") for r in reachable if r.get("domain")}
    referring_domains = {r.get("domain") for r in backlinks if r.get("domain")}

    total = len(rows)
    mention_ratio = len(mentioned) / total
    backlink_ratio = len(backlinks) / total
    follow_ratio = len(followed) / total

    # Evidence Score intentionally rewards verified authority evidence only.
    # HTTP reachability is reported as a verification-quality signal, but it does
    # not add authority points by itself. This prevents a reachable page with no
    # brand mention or backlink from receiving a misleading positive authority score.
    mention_points = round(mention_ratio * 35)
    backlink_points = round(backlink_ratio * 35)
    follow_points = round(follow_ratio * 20)

    # Referring-domain diversity is meaningful only when a backlink is verified.
    if backlinks:
        diversity_ratio = min(len(referring_domains) / max(len(backlinks), 1), 1.0)
        diversity_points = round(diversity_ratio * 10)
    else:
        diversity_points = 0

    components = {
        "Verified brand mentions": (mention_points, 35),
        "Verified backlinks": (backlink_points, 35),
        "Followed backlink evidence": (follow_points, 20),
        "Verified referring-domain diversity": (diversity_points, 10),
    }

    score = min(sum(value for value, _ in components.values()), 100)
    readiness = "Strong" if score >= 80 else "Good" if score >= 60 else "Developing" if score >= 40 else "Weak"

    findings = []
    if len(mentioned) < total:
        findings.append(("MEDIUM", f"Brand mention text was verified on {len(mentioned)}/{total} supplied URLs.", "Brand Mentions"))
    if not backlinks:
        findings.append(("HIGH", "No backlinks to the audited domain were verified in the supplied evidence set.", "Off-Page Authority"))
    elif len(backlinks) < total:
        findings.append(("MEDIUM", f"Backlinks were verified on {len(backlinks)}/{total} supplied URLs.", "Backlink Coverage"))
    if backlinks and not followed:
        findings.append(("OPPORTUNITY", "Verified backlinks were present, but no followed backlink was detected.", "Link Equity Evidence"))
    if len(reachable) < total:
        findings.append(("INFO", f"{len(reachable)}/{total} supplied URLs were fetchable during verification; inaccessible URLs were not treated as negative authority evidence.", "Evidence Verification"))

    return {
        "score": score,
        "readiness": readiness,
        "components": components,
        "evidence": {
            "urls_checked": total,
            "reachable": len(reachable),
            "brand_mentions": len(mentioned),
            "backlinks": len(backlinks),
            "followed_backlinks": len(followed),
            "referring_domains": len(referring_domains),
            "supplied_domains": len(supplied_domains),
            "fetched_domains": len(fetched_domains),
            "domain_counts": dict(Counter(r.get("domain") for r in backlinks if r.get("domain"))),
        },
        "findings": findings,
        "disclaimer": (
            "External Mention Score summarizes verified mention/backlink evidence only from the URLs supplied for verification. "
            "Reachability alone does not increase the score. It is not a complete backlink index, domain-authority metric, "
            "or proof that a search engine credits a link."
        ),
    }

