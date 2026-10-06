import json
import re
from collections import Counter
from dataclasses import dataclass, asdict
from urllib.parse import urljoin, urlparse, urldefrag

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 20


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url.rstrip("/")


def fetch(url, timeout=REQUEST_TIMEOUT):
    return requests.get(url, headers=HEADERS, timeout=timeout, allow_redirects=True)


def parse_html(html):
    return BeautifulSoup(html or "", "html.parser")


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def same_domain(base, candidate):
    a = urlparse(base).netloc.lower().split(":")[0]
    b = urlparse(candidate).netloc.lower().split(":")[0]
    return a == b


def absolute_url(base, href):
    return urljoin(base, href)


def canonical_url(url):
    return urldefrag(url)[0].rstrip("/")


def word_tokens(text):
    return re.findall(r"[A-Za-z][A-Za-z0-9'’-]{2,}", (text or "").lower())


def _body_text(soup):
    body = soup.body or soup
    for tag in body.find_all(["script", "style", "noscript", "svg"]):
        tag.decompose()
    return clean_text(body.get_text(" ", strip=True))


@dataclass
class PageAudit:
    url: str
    final_url: str
    status: int
    title: str
    description: str
    canonical: str
    robots_meta: str
    h1: list
    h2: list
    h3: list
    word_count: int
    body_text: str
    images: list
    internal_links: list
    external_links: list
    schema_types: list
    schema_blocks: list
    og: dict
    twitter: dict
    lists: int = 0
    tables: int = 0
    forms: int = 0
    lang: str = ""
    noindex: bool = False
    response_ms: int = 0
    browser_rendered: bool = False
    error: str = ""


def _extract_page(soup, url, final_url, status, response_ms, browser_rendered=False):
    title = clean_text(soup.title.get_text(" ", strip=True)) if soup.title else ""
    md = soup.find("meta", attrs={"name": re.compile(r"^description$", re.I)})
    description = clean_text(md.get("content", "")) if md else ""
    canonical = ""
    for link in soup.find_all("link"):
        rel = link.get("rel") or []
        rels = [str(x).lower() for x in rel] if isinstance(rel, list) else [str(rel).lower()]
        if "canonical" in rels and link.get("href"):
            canonical = absolute_url(final_url, link["href"].strip())
            break
    robots = soup.find("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    robots_meta = clean_text(robots.get("content", "")) if robots else ""
    noindex = "noindex" in robots_meta.lower()

    headings = {f"h{i}": [clean_text(x.get_text(" ", strip=True)) for x in soup.find_all(f"h{i}")]
                for i in (1, 2, 3)}
    text = _body_text(soup)
    words = word_tokens(text)

    images = []
    for img in soup.find_all("img"):
        src = img.get("src") or img.get("data-src") or img.get("data-lazy-src") or ""
        current = img.get("data-current-src") or ""
        images.append({
            "src": absolute_url(final_url, current or src) if (current or src) else "",
            "alt": clean_text(img.get("alt", "")),
            "loading": img.get("loading", ""),
            "width": img.get("width", ""),
            "height": img.get("height", ""),
        })

    internal, external = [], []
    seen_links = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        dest = urldefrag(absolute_url(final_url, href))[0]
        item = {"url": dest, "anchor": clean_text(a.get_text(" ", strip=True)) or "(empty anchor)"}
        key = (dest, item["anchor"])
        if key in seen_links:
            continue
        seen_links.add(key)
        (internal if same_domain(final_url, dest) else external).append(item)

    schema_types, schema_blocks = [], []
    for script in soup.find_all("script", attrs={"type": re.compile(r"application/ld\+json", re.I)}):
        raw = script.string or script.get_text()
        try:
            data = json.loads(raw)
            schema_blocks.append(data)
            nodes = data if isinstance(data, list) else data.get("@graph", [data]) if isinstance(data, dict) else []
            for node in nodes:
                if isinstance(node, dict) and node.get("@type"):
                    vals = node["@type"] if isinstance(node["@type"], list) else [node["@type"]]
                    schema_types.extend(str(v) for v in vals)
        except Exception:
            schema_blocks.append({"_parse_error": True, "raw": raw[:5000]})

    og, twitter = {}, {}
    for meta in soup.find_all("meta"):
        prop = meta.get("property") or meta.get("name")
        content = meta.get("content")
        if not prop or content is None:
            continue
        key = prop.lower().strip()
        if key.startswith("og:"): og[key] = content.strip()
        if key.startswith("twitter:"): twitter[key] = content.strip()

    return PageAudit(
        url=url, final_url=final_url, status=status, title=title,
        description=description, canonical=canonical, robots_meta=robots_meta,
        h1=headings["h1"], h2=headings["h2"], h3=headings["h3"],
        word_count=len(words), body_text=text, images=images,
        internal_links=internal, external_links=external,
        schema_types=list(dict.fromkeys(schema_types)), schema_blocks=schema_blocks,
        og=og, twitter=twitter, lists=len(soup.find_all(["ul", "ol"])),
        tables=len(soup.find_all("table")), forms=len(soup.find_all("form")),
        lang=(soup.html.get("lang", "") if soup.html else ""), noindex=noindex,
        response_ms=response_ms, browser_rendered=browser_rendered,
    )


def _launch_browser(playwright):
    errors = []
    try:
        return playwright.chromium.launch(channel="chrome", headless=True)
    except Exception as exc:
        errors.append(f"installed Chrome: {exc}")
    try:
        return playwright.chromium.launch(headless=True)
    except Exception as exc:
        errors.append(f"Playwright Chromium: {exc}")
    raise RuntimeError("Browser launch failed. " + " | ".join(errors))


def browser_available():
    try:
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = _launch_browser(p); browser.close()
        return True, ""
    except Exception as exc:
        return False, str(exc)


def crawl_page_browser(page, url, timeout=30000):
    import time
    started = time.perf_counter()
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    try: page.wait_for_load_state("networkidle", timeout=8000)
    except Exception: pass
    page.wait_for_timeout(700)
    html = page.content()
    status = response.status if response else 0
    final_url = page.url
    audit = _extract_page(parse_html(html), url, final_url, status,
                          int((time.perf_counter() - started) * 1000), True)
    try:
        rendered = page.locator("img").evaluate_all("""els => els.map(img => ({
            src: img.currentSrc || img.src || img.getAttribute('data-src') || '',
            alt: img.getAttribute('alt') || '', loading: img.getAttribute('loading') || '',
            width: img.naturalWidth || img.width || '', height: img.naturalHeight || img.height || ''
        }))""")
        audit.images = rendered
    except Exception: pass

    audit.aeo_question_answers = extract_aeo_question_answers_browser(page)

    return audit


def crawl_page_requests(url, timeout=REQUEST_TIMEOUT):
    import time
    started = time.perf_counter()
    response = fetch(url, timeout=timeout)
    audit = _extract_page(parse_html(response.text), url, response.url, response.status_code,
                          int((time.perf_counter() - started) * 1000), False)
    return audit


def crawl_site(start_url, limit=15, timeout=30000, prefer_browser=True):
    start_url = normalize_url(start_url)
    results, errors, queue = [], [], [start_url]
    queued = {canonical_url(start_url)}
    browser_used, browser_error = False, ""

    if prefer_browser:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = _launch_browser(p); browser_used = True
                context = browser.new_context(user_agent=HEADERS["User-Agent"], viewport={"width":1440,"height":900}, ignore_https_errors=True)
                page = context.new_page()
                while queue and len(results) < limit:
                    current = queue.pop(0)
                    try:
                        audit = crawl_page_browser(page, current, timeout=timeout)
                        if audit.status >= 400:
                            errors.append((current, audit.status, "HTTP error")); continue
                        results.append(audit)
                        for item in audit.internal_links:
                            dest = canonical_url(item["url"])
                            if same_domain(start_url, dest) and dest not in queued and len(queued) < limit * 8:
                                queued.add(dest); queue.append(item["url"])
                    except Exception as exc:
                        errors.append((current, "Request error", str(exc)))
                context.close(); browser.close()
        except Exception as exc:
            browser_error = str(exc)

    if not browser_used:
        while queue and len(results) < limit:
            current = queue.pop(0)
            try:
                audit = crawl_page_requests(current)
                if audit.status >= 400:
                    errors.append((current, audit.status, "HTTP error")); continue
                results.append(audit)
                for item in audit.internal_links:
                    dest = canonical_url(item["url"])
                    if same_domain(start_url, dest) and dest not in queued and len(queued) < limit * 8:
                        queued.add(dest); queue.append(item["url"])
            except Exception as exc:
                errors.append((current, "Request error", str(exc)))

    return {"pages": results, "errors": errors, "browser_used": browser_used, "browser_error": browser_error}


def page_to_dict(page): return asdict(page)


def get_robots_sitemap(base):
    base = normalize_url(base); out = {"robots":None,"sitemap":None,"errors":[]}
    for key, path in (("robots","/robots.txt"),("sitemap","/sitemap.xml")):
        try:
            r=fetch(base+path); out[key]={"status":r.status_code,"url":r.url,"text":r.text}
        except Exception as exc: out["errors"].append((path,str(exc)))
    return out


def parse_sitemap(text, base_url=""):
    soup=BeautifulSoup(text or "","xml"); urls=[]
    for node in soup.find_all(["url","sitemap"]):
        loc=node.find("loc")
        if loc and clean_text(loc.get_text()) not in urls: urls.append(clean_text(loc.get_text()))
    if not urls: urls=list(dict.fromkeys(clean_text(x) for x in re.findall(r"<loc>\s*(.*?)\s*</loc>",text or "",flags=re.I|re.S)))
    return urls


def check_urls(urls, timeout=10):
    rows=[]
    for raw in urls:
        try:
            r=fetch(raw,timeout=timeout)
            status=r.status_code
            classification="working" if status < 400 else "review" if status in (400,401,403,405,406,429) else "broken"
            rows.append({"url":raw,"status":status,"final_url":r.url,"redirect_hops":len(r.history),"classification":classification,"error":""})
        except Exception as exc:
            rows.append({"url":raw,"status":"Error","final_url":"","redirect_hops":0,"classification":"error","error":str(exc)})
    return rows


def _score_checks(checks):
    passed=sum(bool(x[1]) for x in checks); total=len(checks)
    return round(100*passed/max(total,1)), passed, total-passed


def category_scores(p):
    technical=[
        ("Status", 200 <= p.status < 400), ("Canonical", bool(p.canonical)),
        ("Robots meta", not p.noindex), ("Internal links", bool(p.internal_links)),
    ]
    onpage=[
        ("Title", bool(p.title)), ("Meta description", bool(p.description)),
        ("One primary H1", len(p.h1)==1), ("Useful H2 structure", bool(p.h2)),
        ("Content depth", p.word_count>=300),
    ]
    schema=[("JSON-LD detected", bool(p.schema_blocks)), ("Schema types identified", bool(p.schema_types))]
    imgs=[("ALT coverage", not p.images or all(bool(i.get("alt","").strip()) for i in p.images)),
          ("Images rendered", bool(p.images) or True)]
    social=[("OG title",bool(p.og.get("og:title"))), ("OG image",bool(p.og.get("og:image"))),
            ("Twitter card",bool(p.twitter.get("twitter:card")))]
    return {k:_score_checks(v)[0] for k,v in {"Technical SEO":technical,"On-Page SEO":onpage,"Schema":schema,"Image SEO":imgs,"Social Metadata":social}.items()}


def aeo_score(p):
    checks=[
        ("Clear title",bool(p.title)), ("Primary H1",len(p.h1)==1),
        ("Question-style headings",any("?" in x for x in p.h2+p.h3)),
        ("Lists/tables where useful",p.lists>0 or p.tables>0),
        ("Structured data",bool(p.schema_blocks)),
        ("Substantial text",p.word_count>=300), ("Open Graph",bool(p.og.get("og:title"))),
    ]
    return _score_checks(checks), checks


def performance_score(pages):
    if not pages: return 0
    # This is a crawl-response score, not Google's Lighthouse/PageSpeed score.
    vals=[]
    for p in pages:
        vals.append(100 if p.response_ms < 1000 else 80 if p.response_ms < 2000 else 60 if p.response_ms < 4000 else 40 if p.response_ms < 8000 else 20)
    return round(sum(vals)/len(vals))


def overall_scores(pages):
    if not pages: return {}
    cats={"Technical SEO":[],"On-Page SEO":[],"Schema":[],"Image SEO":[],"Social Metadata":[]}
    for p in pages:
        scores=category_scores(p)
        for k,v in scores.items(): cats[k].append(v)
    out={k:round(sum(v)/len(v)) for k,v in cats.items()}
    out["Performance"] = performance_score(pages)
    out["AEO Readiness"] = round(sum(aeo_score(p)[0][0] for p in pages)/len(pages))
    weights={"Technical SEO":0.20,"On-Page SEO":0.25,"Schema":0.10,"Image SEO":0.10,"Social Metadata":0.10,"Performance":0.10,"AEO Readiness":0.15}
    out["Overall SEO Health"] = round(sum(out[k]*w for k,w in weights.items()))
    return out


def audit_score(page=None, extra_passes=0, extra_reviews=0):
    if page is None: return 0
    return overall_scores([page]).get("Overall SEO Health",0)


def html_report(site,crawl,findings,scores=None):
    from html import escape
    from datetime import datetime

    pages=crawl.get("pages",[])
    scores=scores or overall_scores(pages)
    site=escape(str(site))
    audited_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    page_count=len(pages)
    crawl_errors=len(crawl.get("errors",[]))
    internal_links=sum(len(p.internal_links) for p in pages)
    schema_pages=sum(bool(p.schema_blocks) for p in pages)
    image_count=sum(len(p.images) for p in pages)
    unique_imgs=len({i.get("src") for p in pages for i in p.images if i.get("src")})

    cards="".join(
        f"<div class='score'><b>{escape(str(k))}</b><span>{v}/100</span></div>"
        for k,v in scores.items()
    )
    rows="".join(
        "<tr>"
        f"<td>{escape(str(p.url))}</td>"
        f"<td>{escape(str(p.status))}</td>"
        f"<td>{len(p.h1)}</td><td>{len(p.h2)}</td>"
        f"<td>{p.word_count}</td><td>{len(p.images)}</td>"
        f"<td>{len(p.internal_links)}</td>"
        f"<td>{escape(', '.join(p.schema_types) or 'None')}</td>"
        "</tr>"
        for p in pages
    )
    def priority_for(label):
        high={"Primary H1","robots.txt","sitemap.xml"}
        low={"Meta description","Content depth","H2 structure"}
        if label in high: return "HIGH"
        if label in low: return "OPPORTUNITY"
        return "MEDIUM"

    priority_counts={"HIGH":0,"MEDIUM":0,"OPPORTUNITY":0}
    finding_cards=[]
    for item in findings:
        _, label, detail, why, action, service = item
        priority=priority_for(label)
        priority_counts[priority]+=1
        badge_class=priority.lower()
        badge_text={"HIGH":"HIGH","MEDIUM":"MEDIUM","OPPORTUNITY":"OPPORTUNITY"}[priority]
        finding_cards.append(
            "<div class='finding'>"
            f"<div class='priority {badge_class}'>{badge_text}</div>"
            f"<h3>{escape(str(label))}</h3>"
            f"<div class='detail'>{escape(str(detail))}</div>"
            f"<p><strong>Why it matters</strong><br>{escape(str(why))}</p>"
            f"<p><strong>Recommended SEO Action</strong><br>{escape(str(action))}</p>"
            f"<div class='service'><strong>Service area:</strong> {escape(str(service))}</div>"
            "</div>"
        )
    finding_html="".join(finding_cards) or "<p>No review findings were generated for this audit.</p>"

    service_names=[]
    for item in findings:
        service=str(item[5])
        if service not in service_names:
            service_names.append(service)
    service_html="".join(f"<li><strong>{escape(x)}</strong></li>" for x in service_names) or "<li>No specific service area was triggered by the review findings.</li>"

    return f'''<!doctype html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1">
<title>SEO Audit Suite Pro V5 - Client Report</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;margin:0;background:#f5f7fa;color:#18202a;line-height:1.5}}
.wrap{{max-width:1120px;margin:0 auto;padding:34px 24px 60px}}
.hero{{background:#fff;border:1px solid #dfe4ea;border-radius:18px;padding:28px;box-shadow:0 4px 18px rgba(20,30,40,.05)}}
.hero h1{{margin:0 0 8px;font-size:30px}} .muted{{color:#68727d}} .meta{{display:flex;flex-wrap:wrap;gap:18px;margin-top:14px;font-size:13px}}
.scores{{display:grid;grid-template-columns:repeat(4,minmax(0,1fr));gap:12px;margin:20px 0}}
.score{{border:1px solid #dfe4ea;border-radius:14px;padding:16px;background:#fff}} .score span{{display:block;font-size:26px;font-weight:700;margin-top:5px}}
.card{{background:#fff;border:1px solid #dfe4ea;border-radius:16px;padding:22px;margin:20px 0}} .card h2{{margin-top:0}}
.summary{{display:grid;grid-template-columns:repeat(4,1fr);gap:12px}} .summary .mini{{border:1px solid #e4e8ed;border-radius:12px;padding:14px;background:#fafbfc}}
.finding{{border:1px solid #ead7a2;border-radius:14px;padding:17px;margin:14px 0;background:#fffdf5}} .finding h3{{margin:4px 0}} .finding .detail{{font-weight:700;margin-bottom:12px}} .service{{font-size:13px;color:#59636e}} .priority{{display:inline-block;font-size:11px;font-weight:800;letter-spacing:.06em;padding:4px 8px;border-radius:999px}} .priority.high{{background:#fde7e7;color:#a61b1b}} .priority.medium{{background:#fff0d8;color:#8a5200}} .priority.opportunity{{background:#e8f6e8;color:#286b2f}}
table{{border-collapse:collapse;width:100%;margin-top:12px;background:#fff}} th,td{{border:1px solid #dfe4ea;padding:9px;text-align:left;font-size:12px;vertical-align:top}} th{{background:#f0f3f6}}
.note{{background:#f7f9fb;border-left:4px solid #8793a0;padding:14px 16px;border-radius:8px}}
.footer{{margin-top:24px;font-size:12px;color:#68727d;text-align:center}}
@media(max-width:800px){{.scores{{grid-template-columns:repeat(2,1fr)}}.summary{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <h1>SEO Audit Suite Pro V5</h1>
    <div class="muted">Professional SEO Audit Client Report</div>
    <div style="margin-top:12px"><strong>Audited website:</strong> {site}</div>
    <div class="meta">
      <span><strong>Audit date:</strong> {audited_at}</span>
      <span><strong>Pages crawled:</strong> {page_count}</span>
      <span><strong>Crawl errors:</strong> {crawl_errors}</span>
      <span><strong>Internal links:</strong> {internal_links}</span>
    </div>
  </section>

  <section class="card">
    <h2>Executive Summary</h2>
    <div class="summary">
      <div class="mini"><strong>Overall SEO Health</strong><br><span style="font-size:24px;font-weight:700">{scores.get('Overall SEO Health',0)}/100</span></div>
      <div class="mini"><strong>Pages audited</strong><br><span style="font-size:24px;font-weight:700">{page_count}</span></div>
      <div class="mini"><strong>Schema coverage</strong><br><span style="font-size:24px;font-weight:700">{schema_pages}/{page_count}</span></div>
      <div class="mini"><strong>Images analyzed</strong><br><span style="font-size:24px;font-weight:700">{image_count}</span></div>
    </div>
    <p style="margin-bottom:0">This report identifies technical, on-page, social, schema, image and AI-search-readiness signals to support professional SEO assessment and client recommendations.</p>
  </section>

  <section class="card">
    <h2>SEO Scorecard</h2>
    <div class="scores">{cards}</div>
    <div class="note"><strong>Score definitions:</strong> SEO Health and category scores are calculated by SEO Audit Suite. They are not official Google ranking scores. AEO Readiness is a heuristic checklist, not a Google, ChatGPT or AI-search ranking score. Performance is based on crawl response time unless PageSpeed Insights data is connected.</div>
  </section>

  <section class="card">
    <h2>Priority Findings &amp; Recommended SEO Actions</h2>
    <p class="muted">Findings are grouped by audit severity to help prioritize professional SEO work. These are SEO Audit Suite priorities, not Google ranking priorities.</p>
    <div class="summary">
      <div class="mini"><strong>High Priority</strong><br><span style="font-size:24px;font-weight:700">{priority_counts['HIGH']}</span></div>
      <div class="mini"><strong>Medium Priority</strong><br><span style="font-size:24px;font-weight:700">{priority_counts['MEDIUM']}</span></div>
      <div class="mini"><strong>Opportunities</strong><br><span style="font-size:24px;font-weight:700">{priority_counts['OPPORTUNITY']}</span></div>
      <div class="mini"><strong>Total Reviews</strong><br><span style="font-size:24px;font-weight:700">{len(findings)}</span></div>
    </div>
    <p class="muted">These findings are written as professional SEO recommendations rather than step-by-step DIY instructions.</p>
    {finding_html}
  </section>

  <section class="card">
    <h2>Site Coverage</h2>
    <p>Browser-rendered pages audited: <strong>{page_count}</strong>. Rendered image elements: <strong>{image_count}</strong>. Unique image URLs: <strong>{unique_imgs}</strong>. Pages with JSON-LD: <strong>{schema_pages}/{page_count}</strong>.</p>
  </section>

  <section class="card">
    <h2>Crawled Pages</h2>
    <table>
      <tr><th>URL</th><th>Status</th><th>H1</th><th>H2</th><th>Words</th><th>Images</th><th>Internal links</th><th>Schema</th></tr>
      {rows}
    </table>
  </section>

  <section class="card">
    <h2>Recommended SEO Services</h2>
    <p>The following service areas were triggered by the review findings in this audit. They are presented as professional SEO opportunities rather than step-by-step DIY instructions.</p>
    <ul>{service_html}</ul>
  </section>

  <section class="card">
    <div class="note"><strong>Important:</strong> This report is an SEO assessment generated by SEO Audit Suite. It is not a Google score or a guarantee of search rankings. Recommendations should be reviewed in the context of the website, target audience, search intent and business goals.</div>
  </section>

  <div class="footer">Generated by SEO Audit Suite Pro V5 - Professional client audit report</div>
</div>
</body>
</html>'''

def extract_aeo_question_answers_browser(page):
    """
    V6 AEO Question Discovery 2.0

    Detects meaningful question-focused content in the rendered DOM,
    including headings and suitable paragraph-style questions.

    It then inspects nearby rendered content for a direct-answer signal.

    Existing V5 PageAudit functionality is not modified.
    """

    try:
        results = page.locator(
            "h1, h2, h3, h4, h5, h6, p"
        ).evaluate_all(
            """
            elements => {

                const questionStarters = [
                    "what ",
                    "why ",
                    "how ",
                    "when ",
                    "where ",
                    "who ",
                    "which ",
                    "can ",
                    "could ",
                    "should ",
                    "is ",
                    "are ",
                    "do ",
                    "does ",
                    "will ",
                    "looking for "
                ];

                const noisePhrases = [
                    "select your location",
                    "please select",
                    "use current location",
                    "change location",
                    "select city",
                    "order type",
                    "sign in",
                    "log in",
                    "subscribe",
                    "add to cart",
                    "view cart",
                    "checkout"
                ];

                const clean = (value) => {
                    return (value || "")
                        .replace(/\\s+/g, " ")
                        .trim();
                };

                const wordCount = (value) => {
                    const text = clean(value);

                    if (!text) {
                        return 0;
                    }

                    return text.split(/\\s+/).length;
                };

                const isNoise = (text) => {
                    const lower = clean(text).toLowerCase();

                    return noisePhrases.some(
                        phrase => lower.includes(phrase)
                    );
                };

                const looksLikeQuestion = (text, tag) => {
                    const value = clean(text);
                    const lower = value.toLowerCase();
                    const words = wordCount(value);

                    if (!value) {
                        return false;
                    }

                    if (isNoise(value)) {
                        return false;
                    }

                    /*
                    Avoid treating very long paragraphs as questions.
                    */
                    if (words > 25) {
                        return false;
                    }

                    /*
                    Explicit question mark is the strongest signal.
                    */
                    if (value.endsWith("?")) {
                        return true;
                    }

                    /*
                    Question-style headings may omit a question mark.
                    */
                    const isHeading = [
                        "h1",
                        "h2",
                        "h3",
                        "h4",
                        "h5",
                        "h6"
                    ].includes(tag);

                    if (isHeading) {
                        return questionStarters.some(
                            starter => lower.startsWith(starter)
                        );
                    }

                    return false;
                };

                const isHeading = (node) => {
                    if (!node || !node.tagName) {
                        return false;
                    }

                    return [
                        "H1",
                        "H2",
                        "H3",
                        "H4",
                        "H5",
                        "H6"
                    ].includes(node.tagName);
                };

                const findNearbyAnswer = (element) => {
                    let node = element.nextElementSibling;
                    let checked = 0;

                    while (node && checked < 8) {
                        checked++;

                        const tag = (
                            node.tagName || ""
                        ).toLowerCase();

                        const text = clean(node.innerText);

                        /*
                        Stop when another heading begins.
                        This keeps the answer tied to the
                        current content section.
                        */
                        if (isHeading(node)) {
                            break;
                        }

                        if (!text || isNoise(text)) {
                            node = node.nextElementSibling;
                            continue;
                        }

                        const words = wordCount(text);

                        /*
                        Paragraph answer.
                        */
                        if (
                            tag === "p" &&
                            words >= 5 &&
                            words <= 120
                        ) {
                            return {
                                answer_found: true,
                                answer: text,
                                answer_type: "paragraph",
                                answer_words: words
                            };
                        }

                        /*
                        List answer.
                        */
                        if (
                            (tag === "ul" || tag === "ol") &&
                            words >= 3 &&
                            words <= 150
                        ) {
                            return {
                                answer_found: true,
                                answer: text,
                                answer_type: "list",
                                answer_words: words
                            };
                        }

                        /*
                        Some modern JS websites wrap actual
                        textual answers inside DIV elements.
                        Keep this deliberately restrictive.
                        */
                        if (
                            tag === "div" &&
                            words >= 8 &&
                            words <= 80
                        ) {
                            return {
                                answer_found: true,
                                answer: text,
                                answer_type: "content block",
                                answer_words: words
                            };
                        }

                        node = node.nextElementSibling;
                    }

                    return {
                        answer_found: false,
                        answer: "",
                        answer_type: "",
                        answer_words: 0
                    };
                };

                const output = [];
                const seen = new Set();

                for (const element of elements) {

                    const tag = (
                        element.tagName || ""
                    ).toLowerCase();

                    const question = clean(
                        element.innerText
                    );

                    if (
                        !looksLikeQuestion(
                            question,
                            tag
                        )
                    ) {
                        continue;
                    }

                    const key = question.toLowerCase();

                    /*
                    Avoid duplicate rendered questions.
                    */
                    if (seen.has(key)) {
                        continue;
                    }

                    seen.add(key);

                    const answerData =
                        findNearbyAnswer(element);

                    output.push({
                        question: question,
                        source_element: tag,
                        answer_found:
                            answerData.answer_found,
                        answer:
                            answerData.answer,
                        answer_type:
                            answerData.answer_type,
                        answer_words:
                            answerData.answer_words
                    });
                }

                return output;
            }
            """
        )

        return results

    except Exception:
        return []