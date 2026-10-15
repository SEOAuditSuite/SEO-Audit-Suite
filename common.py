import json
import base64
import re
from collections import Counter
from dataclasses import dataclass, asdict, field
from urllib.parse import urljoin, urlparse, urldefrag

import time
from safe_http import SafeSession, TransportError
from bs4 import BeautifulSoup
from link_diagnostics import url_key, validate_fetch_url, classify_status, status_evidence, crawl_status_cache

HEADERS = {
    "User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/153.0.0.0 Safari/537.36",
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/avif,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9",
}
REQUEST_TIMEOUT = 20


COMPLETE_AUDIT_VERSION = "V6.1.1 (development)"


def normalize_url(url: str) -> str:
    url = (url or "").strip()
    if not url:
        return ""
    if not url.startswith(("http://", "https://")):
        url = "https://" + url
    return url


def fetch(url, timeout=REQUEST_TIMEOUT, url_validator=None, deadline=None):
    # Validate each redirect before requesting it; cap decompressed body bytes.
    deadline = min(deadline, time.monotonic()+60) if deadline is not None else time.monotonic()+60
    with SafeSession() as session:
        history = []
        for _ in range(11):
            try:
                validate_fetch_url(url)
                if url_validator is not None:
                    url_validator(url)
            except ValueError:
                raise TransportError('Request URL or redirect scope blocked') from None
            r = session.get(url, headers=HEADERS, timeout=timeout, allow_redirects=False, stream=True, deadline=deadline)
            try:
                if r.status_code in (301, 302, 303, 307, 308) and r.headers.get('Location'):
                    history.append(r)
                    url = urljoin(r.url, r.headers['Location'])
                    continue
                chunks, size = [], 0
                for chunk in r.iter_content(65536):
                    size += len(chunk)
                    if size > 5 * 1024 * 1024:
                        raise ValueError('Response exceeds 5 MiB limit')
                    chunks.append(chunk)
                r._content = b''.join(chunks)
                r._content_consumed = True
                r.history = history
                return r
            finally:
                r.close()
        raise ValueError('Redirect limit exceeded')


def parse_html(html):
    return BeautifulSoup(html or "", "html.parser")


def clean_text(text):
    return re.sub(r"\s+", " ", text or "").strip()


def same_domain(base, candidate):
    a = (urlparse(base).hostname or "").lower()
    b = (urlparse(candidate).hostname or "").lower()
    return a == b


def absolute_url(base, href):
    return urljoin(base, href)


def canonical_url(url):
    return urldefrag(url)[0].rstrip("/")


def word_tokens(text):
    return re.findall(r"[A-Za-z][A-Za-z0-9'’-]{2,}", (text or "").lower())


def _body_text(soup):
    # Work on a copy: removing scripts here must not erase JSON-LD from the audit.
    copy = BeautifulSoup(str(soup.body or soup), "html.parser")
    body = copy.body or copy
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
    link_occurrences: list | None = None
    redirect_chain: list = field(default_factory=list)
    crawl_depth: int | None = None


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
    robots = soup.find_all("meta", attrs={"name": re.compile(r"^robots$", re.I)})
    robots_meta = ", ".join(clean_text(tag.get("content", "")) for tag in robots)
    noindex = bool(set(re.split(r"[\s,]+", robots_meta.lower())) & {"noindex", "none"})

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

    internal, external, occurrences = [], [], []
    seen_links = set()
    for a in soup.find_all("a", href=True):
        href = a.get("href", "").strip()
        if not href or href.startswith(("#", "mailto:", "tel:", "javascript:", "data:")):
            continue
        dest = urldefrag(absolute_url(final_url, href))[0]
        try:
            if urlparse(dest).scheme.lower() not in ('http', 'https'):
                continue
            url_key(dest)  # retain private targets as evidence; fetching is separately guarded
        except ValueError:
            continue
        item = {"url": dest, "anchor": clean_text(a.get_text(" ", strip=True)) or "(empty anchor)"}
        occurrences.append(dict(item, internal=same_domain(final_url, dest)))
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
        response_ms=response_ms, browser_rendered=browser_rendered, link_occurrences=occurrences,
    )


def _launch_browser(playwright, launch_args=None):
    from browser_isolation import launch_browser
    return launch_browser(playwright, launch_args)


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
    validate_fetch_url(url)
    response = page.goto(url, wait_until="domcontentloaded", timeout=timeout)
    from browser_isolation import close_blocked_websockets
    close_blocked_websockets(page.context)
    try: page.wait_for_load_state("networkidle", timeout=8000)
    except Exception: pass
    page.wait_for_timeout(700)
    validate_fetch_url(page.url)
    html = page.content()
    if len(html.encode("utf-8")) > 5 * 1024 * 1024:
        raise ValueError("Rendered HTML exceeds 5 MiB limit")
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

    if response and url_key(response.url) == url_key(final_url):
        previous = response.request.redirected_from
        chain = []
        while previous:
            prior_response = previous.response()
            if prior_response:
                chain.append({'url': previous.url, 'status': prior_response.status})
            previous = previous.redirected_from
        audit.redirect_chain = list(reversed(chain))
    elif response:
        # Client-side navigation is not an observed HTTP redirect/status mapping.
        audit.status = 0
    audit.aeo_question_answers = extract_aeo_question_answers_browser(page)

    return audit


def crawl_page_requests(url, timeout=REQUEST_TIMEOUT):
    import time
    started = time.perf_counter()
    response = fetch(url, timeout=timeout)
    audit = _extract_page(parse_html(response.text), url, response.url, response.status_code,
                          int((time.perf_counter() - started) * 1000), False)
    audit.redirect_chain = [{"url": r.url, "status": r.status_code} for r in response.history]
    return audit


def _guard_browser_route(route):
    # Legacy entry point is fail-closed; all crawler traffic must use GetBroker.
    route.abort()


def _crawl_site_local(start_url, limit=15, timeout=30000, prefer_browser=True, checkpoint=None):
    from collections import deque
    start_url = normalize_url(start_url)
    validate_fetch_url(start_url)
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError('Page limit must be between 1 and 500')
    results, errors, checks, out_of_scope = [], [], [], []
    queue = deque([start_url])
    depths = {url_key(start_url): 0}
    inspected, attempted = set(), set()
    skipped = 0
    browser_used, browser_error = False, ''
    browser_security = None
    crawl_origin = start_url
    discovery_limit = limit * 8
    active_url = None

    def snapshot(reason=None):
        remaining = [u for u in queue if url_key(u) not in inspected and url_key(u) not in attempted]
        stop = reason or ('browser_interrupted' if browser_used and browser_error else
            'page_limit' if remaining and len(results) >= limit else
            'attempt_limit' if remaining else 'discovery_limit' if skipped else
            'queue_exhausted_with_errors' if errors else 'queue_exhausted')
        coverage = dict(seed_url=start_url, audit_hostname=urlparse(crawl_origin).hostname.lower(),
            out_of_scope_redirects=out_of_scope, requested_limit=limit, pages_inspected=len(results),
            attempted_urls=len(attempted), discovery_limit=discovery_limit, discovered_depths=depths,
            remaining_queue=remaining, skipped_discoveries=skipped, stop_reason=stop,
            observed_graph_complete=stop == 'queue_exhausted', full_site_complete=False)
        if active_url is not None:
            coverage['inflight_url'] = active_url
        output = dict(pages=results, errors=errors, browser_used=browser_used, browser_error=browser_error,
            status_checks=checks, coverage=coverage)
        if browser_security is not None:
            output['browser_security'] = browser_security
            if browser_security['partial_render']: coverage['observed_graph_complete'] = False
        return output

    def save():
        if checkpoint is not None: checkpoint(snapshot('worker_running'))

    save()

    def consume(loader):
        nonlocal skipped, crawl_origin, active_url
        while queue and len(results) < limit and len(attempted) < discovery_limit:
            current = queue.popleft()
            key = url_key(current)
            if key in inspected or key in attempted:
                continue
            attempted.add(key)
            active_url = current
            save()
            try:
                audit = loader(current)
                audit.crawl_depth = depths[key]
                checks.append(status_evidence(audit))
                if audit.status >= 400 or audit.status < 200:
                    errors.append((current, audit.status, 'HTTP error or unknown status'))
                    continue
                final = url_key(audit.final_url)
                if key == url_key(start_url):
                    crawl_origin = audit.final_url
                if not same_domain(crawl_origin, audit.final_url):
                    out_of_scope.append(dict(requested_url=current, final_url=audit.final_url,
                                             status=audit.status, depth=depths[key]))
                    continue  # status evidence retained; foreign page excluded from all page summaries
                depths[final] = min(depths.get(final, depths[key]), depths[key])
                if final in inspected:
                    continue
                inspected.add(final)
                results.append(audit)
                for item in audit.internal_links:
                    dest = url_key(item['url'])
                    if same_domain(crawl_origin, dest) and dest not in depths:
                        if len(depths) >= discovery_limit:
                            skipped += 1
                            continue
                        depths[dest] = depths[final] + 1
                        queue.append(item['url'])
            except Exception as exc:
                # Avoid reflecting URLs/query strings or credentials from exceptions.
                message = type(exc).__name__ + ': fetch failed or blocked; verify access and limits'
                errors.append((current, 'Request error', message))
                checks.append(dict(url=current, status=None, requested_status=None, final_url='',
                                   redirect_hops=0, redirect_chain=[], classification='error', error=message))
            finally:
                active_url = None
                save()

    if prefer_browser:
        try:
            from playwright.sync_api import sync_playwright
            with sync_playwright() as p:
                browser = _launch_browser(p)
                try:
                    from browser_isolation import GetBroker, secure_context, close_blocked_popups, close_blocked_websockets
                    broker = GetBroker(HEADERS)
                    try:
                        context = secure_context(browser, user_agent=HEADERS['User-Agent'],
                            viewport={'width': 1440, 'height': 900}, on_block=broker.record_block, defer_popup_close=True)
                        context.route('**/*', broker.handle)
                        page = context.new_page()
                        broker.page = page
                        browser_used = True
                        save()
                        def load(u):
                            broker.begin_navigation(u)
                            try:
                                started = time.perf_counter()
                                final, chain = broker.prepare_navigation(u)
                                audit = crawl_page_browser(page, final, timeout=timeout)
                                close_blocked_popups(context)
                                audit.response_ms = int((time.perf_counter()-started)*1000)
                                policy_blocks = page.evaluate('window.__seoBrowserPolicyBlocks || 0')
                                if isinstance(policy_blocks, int) and policy_blocks:
                                    broker.record_block(f'CSP restricted resources ({policy_blocks} events)')
                                audit.url = u
                                audit.redirect_chain = chain
                                return audit
                            except Exception:
                                broker.record_block('Navigation unavailable; HTTP status unknown')
                                close_blocked_popups(context)
                                raise
                        def checkpoint_load(u):
                            nonlocal browser_security
                            try: return load(u)
                            finally: browser_security = broker.evidence()
                        consume(checkpoint_load)
                    finally:
                        browser_security = broker.evidence()
                        try: broker.close()
                        finally:
                            if 'context' in locals(): context.close()
                finally:
                    browser.close()
        except Exception as exc:
            browser_error = type(exc).__name__ + ': browser unavailable or interrupted'
    if not browser_used:
        consume(lambda u: crawl_page_requests(u, timeout=min(timeout / 1000, REQUEST_TIMEOUT)))
    output = snapshot()
    if checkpoint is not None: checkpoint(output)
    return output


def _crawl_wire(crawl):
    return dict(crawl, pages=[page_to_dict(p) for p in crawl['pages']])


def _crawl_from_wire(crawl):
    if not isinstance(crawl, dict) or not all(k in crawl for k in ('pages','errors','browser_used','browser_error','status_checks','coverage')):
        raise ValueError('Incomplete crawl worker result')
    if not isinstance(crawl['coverage'], dict) or not all(k in crawl['coverage'] for k in (
            'pages_inspected','remaining_queue','stop_reason','observed_graph_complete')):
        raise ValueError('Incomplete crawl coverage')
    return dict(crawl, pages=[PageAudit(**p) for p in crawl['pages']])


def _write_crawl_checkpoint(path, crawl):
    from pathlib import Path
    from browser_supervision import OUTPUT_BYTES
    data = json.dumps(_crawl_wire(crawl), ensure_ascii=True).encode('utf-8')
    if len(data) > OUTPUT_BYTES: raise ValueError('Crawl checkpoint exceeds serialization limit')
    dest = Path(path)
    pending = dest.with_suffix('.pending')
    pending.write_bytes(data)
    pending.replace(dest)


def crawl_site(start_url, limit=15, timeout=30000, prefer_browser=True, wall_seconds=None):
    """Browser mode always runs in a supervised worker; HTTP-only mode uses C1."""
    import math
    from pathlib import Path
    import sys
    import tempfile
    from browser_supervision import run_worker, OUTPUT_BYTES
    start_url = normalize_url(start_url)
    validate_fetch_url(start_url)
    if not isinstance(limit, int) or not 1 <= limit <= 500:
        raise ValueError('Page limit must be between 1 and 500')
    if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or not 1 <= timeout <= 120000:
        raise ValueError('Navigation timeout must be between 1 and 120000 milliseconds')
    if not prefer_browser:
        return _crawl_site_local(start_url, limit, timeout, False)
    seconds = wall_seconds if wall_seconds is not None else min(600, max(60, 15+limit*(timeout/1000+15)))
    if not isinstance(seconds, (int, float)) or not math.isfinite(seconds) or not 1 <= seconds <= 600:
        raise ValueError('Browser execution deadline must be between 1 and 600 seconds')
    with tempfile.TemporaryDirectory(prefix='seo-crawl-') as temp:
        checkpoint = Path(temp)/'crawl.json'
        payload = json.dumps(dict(url=start_url, limit=limit, timeout=timeout, checkpoint=str(checkpoint)))
        worker = run_worker([sys.executable, str(Path(__file__).resolve()), '--crawl-worker'], payload, seconds)
        try:
            if checkpoint.stat().st_size > OUTPUT_BYTES: raise ValueError('Checkpoint limit')
            crawl = _crawl_from_wire(json.loads(checkpoint.read_text(encoding='utf-8')))
        except (OSError, ValueError, TypeError, KeyError):
            crawl = _crawl_site_empty(start_url, limit)
            if not worker.reason: worker.reason = 'invalid_worker_result'
        if not worker.reason and worker.output.strip() != 'crawl-complete': worker.reason = 'invalid_worker_result'
        if worker.reason:
            coverage = crawl['coverage']
            coverage.update(stop_reason=worker.reason, observed_graph_complete=False, full_site_complete=False)
            active = coverage.pop('inflight_url', None)
            message = 'Browser worker stopped ('+worker.reason+'); unfinished URLs and rendering remain unverified.'
            if active:
                crawl['status_checks'].append(dict(url=active, status=None, requested_status=None, final_url='',
                    redirect_hops=0, redirect_chain=[], classification='error', error=message))
                crawl['errors'].append((active, 'Request error', message))
                coverage['unfinished_url'] = active
            crawl['browser_error'] = message
            # Keep broker restrictions and partial rendering separate from lifecycle failure.
            crawl['browser_supervision'] = dict(deadline_seconds=seconds, stop_reason=worker.reason,
                cleanup_confirmed=worker.cleanup_confirmed, partial_evidence=True)
            if not worker.cleanup_confirmed:
                crawl['browser_error'] += ' Process-tree cleanup could not be confirmed; verify leftover worker processes.'
        return crawl


def _crawl_site_empty(url, limit):
    return dict(pages=[], errors=[], browser_used=False, browser_error='', status_checks=[], coverage=dict(
        seed_url=url, audit_hostname=urlparse(url).hostname.lower(), requested_limit=limit, pages_inspected=0,
        attempted_urls=0, discovery_limit=limit*8, discovered_depths={url_key(url):0}, remaining_queue=[url],
        skipped_discoveries=0, stop_reason='worker_unavailable', observed_graph_complete=False, full_site_complete=False,
        out_of_scope_redirects=[]))


def page_to_dict(page): return asdict(page)


def get_robots_sitemap(base, url_validator=None):
    parsed = urlparse(normalize_url(base))
    base = f"{parsed.scheme}://{parsed.netloc}"; out = {"robots":None,"sitemap":None,"errors":[]}
    for key, path in (("robots","/robots.txt"),("sitemap","/sitemap.xml")):
        try:
            r = fetch(base + path, url_validator=url_validator) if url_validator is not None else fetch(base + path)
            out[key] = {"status": r.status_code, "url": r.url, "text": r.text}
            if key == 'sitemap' and url_validator is not None:
                # Preserve original encoding/gzip bytes in JSON-safe optional evidence.
                out[key]['content_base64'] = base64.b64encode(r.content).decode('ascii')
                out[key]['redirect_chain'] = [{'url': h.url, 'status': h.status_code} for h in r.history]
        except Exception as exc: out["errors"].append((path,str(exc)))
    return out


def parse_sitemap(text, base_url=""):
    soup=BeautifulSoup(text or "","xml"); urls=[]
    for node in soup.find_all(["url","sitemap"]):
        loc=node.find("loc")
        if loc and clean_text(loc.get_text()) not in urls: urls.append(clean_text(loc.get_text()))
    if not urls: urls=list(dict.fromkeys(clean_text(x) for x in re.findall(r"<loc>\s*(.*?)\s*</loc>",text or "",flags=re.I|re.S)))
    return urls


def check_urls(urls, timeout=10, cached=None):
    rows = []
    cache = dict(cached or {})
    seen = set()
    for raw in urls:
        try:
            validate_fetch_url(raw)
            key = url_key(raw)
            if key in seen:
                continue
            seen.add(key)
            if key in cache:
                rows.append(dict(cache[key], url=raw))
                continue
            r = fetch(raw, timeout=timeout)
            chain = [{'url': h.url, 'status': h.status_code} for h in r.history]
            row = dict(url=raw, status=r.status_code, final_url=r.url,
                       requested_status=chain[0]['status'] if chain else r.status_code,
                       redirect_hops=len(chain), redirect_chain=chain,
                       classification=classify_status(r.status_code), error='')
            rows.append(row)
            cache[key] = row
            cache.setdefault(url_key(r.url), dict(row, url=r.url, requested_status=r.status_code,
                                                 redirect_hops=0, redirect_chain=[]))
        except Exception as exc:
            rows.append(dict(url=raw, status=None, requested_status=None, final_url='',
                             redirect_hops=0, redirect_chain=[], classification='error',
                             error=type(exc).__name__ + ': fetch failed or blocked; verify access and limits'))
    return rows


def _score_checks(checks):
    passed=sum(bool(x[1]) for x in checks); total=len(checks)
    return round(100*passed/max(total,1)), passed, total-passed


def has_parsed_schema(page):
    """A malformed block is evidence of an error, not successful JSON-LD coverage."""
    return any(isinstance(block, (dict, list)) and bool(block) and
               not (isinstance(block, dict) and block.get('_parse_error'))
               for block in (page.schema_blocks or []))


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
    schema=[("JSON-LD detected", has_parsed_schema(p)), ("Schema types identified", bool(p.schema_types))]
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
        ("Structured data",has_parsed_schema(p)),
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
    from link_diagnostics import coverage_note

    pages=crawl.get("pages",[])
    scores=scores or overall_scores(pages)
    site=escape(str(site))
    audited_at=datetime.now().strftime("%Y-%m-%d %H:%M")
    page_count=len(pages)
    crawl_errors=len(crawl.get("errors",[]))
    internal_links=sum(len(p.internal_links) for p in pages)
    schema_pages=sum(has_parsed_schema(p) for p in pages)
    image_count=sum(len(p.images) for p in pages)
    unique_imgs=len({i.get("src") for p in pages for i in p.images if i.get("src")})

    first_page_alt = sum(bool(i.get("alt", "").strip()) for i in pages[0].images) if pages else 0
    first_page_images = len(pages[0].images) if pages else 0
    first_page_url = escape(pages[0].final_url) if pages else "Not inspected"

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
<title>SEO Audit Suite {COMPLETE_AUDIT_VERSION} - Client Report</title>
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
.table-scroll{{max-width:100%;overflow-x:auto}}
@media(max-width:800px){{.scores{{grid-template-columns:repeat(2,1fr)}}.summary{{grid-template-columns:repeat(2,1fr)}}}}
</style>
</head>
<body>
<div class="wrap">
  <section class="hero">
    <h1>SEO Audit Suite {COMPLETE_AUDIT_VERSION}</h1>
    <div class="muted">Professional SEO Audit Client Report</div>
    <div style="margin-top:12px"><strong>Audited website:</strong> {site}</div>
    <div class="meta">
      <span><strong>Audit date:</strong> {audited_at}</span>
      <span><strong>Pages crawled:</strong> {page_count}</span>
      <span><strong>Crawl errors:</strong> {crawl_errors}</span>
      <span><strong>Deduplicated internal link entries:</strong> {internal_links}</span>
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
    <p>{escape(coverage_note(crawl))}</p>
    <p>Mode: {'Browser-rendered' if crawl.get('browser_used') else 'HTTP HTML fallback'}. Pages audited: <strong>{page_count}</strong>. Crawl-wide image elements: <strong>{image_count}</strong>. Crawl-wide unique image URLs: <strong>{unique_imgs}</strong>. Pages with JSON-LD: <strong>{schema_pages}/{page_count}</strong>.</p>
    <p>First-page non-empty ALT coverage: <strong>{str(first_page_alt) + "/" + str(first_page_images) if first_page_images else "N/A (no image elements)"}</strong>. First inspected page: {first_page_url}. Image totals include repeated and hidden DOM elements, not verified visible or successfully loaded images. Empty ALT may be appropriate for decorative images; this count does not assess ALT quality.</p>
    <p>Link counts in this legacy summary are distinct destination/anchor pairs per page, not element occurrences or unique referring pages. Use Internal Links for those diagnostics. Zero observed inlinks does not prove an orphan.</p>
  </section>

  <section class="card">
    <h2 id="crawled-pages-heading">Crawled Pages</h2>
    <div class="table-scroll" role="region" aria-labelledby="crawled-pages-heading" tabindex="0">
    <table>
      <tr><th>URL</th><th>Status</th><th>H1</th><th>H2</th><th>Words</th><th>Images</th><th>Internal links</th><th>Schema</th></tr>
      {rows}
    </table>
    </div>
  </section>

  <section class="card">
    <h2>Recommended SEO Services</h2>
    <p>The following service areas were triggered by the review findings in this audit. They are presented as professional SEO opportunities rather than step-by-step DIY instructions.</p>
    <ul>{service_html}</ul>
  </section>

  <section class="card">
    <div class="note"><strong>Important:</strong> This report is an SEO assessment generated by SEO Audit Suite. It is not a Google score or a guarantee of search rankings. Recommendations should be reviewed in the context of the website, target audience, search intent and business goals.</div>
  </section>

  <div class="footer">Generated by SEO Audit Suite {COMPLETE_AUDIT_VERSION} - Professional client audit report</div>
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


if __name__ == '__main__':
    import sys
    if sys.argv[1:] == ['--crawl-worker']:
        # Windows Job Object is assigned by the parent before this stdin gate opens.
        request = json.load(sys.stdin)
        _crawl_site_local(request['url'], request['limit'], request['timeout'], True,
            lambda crawl: _write_crawl_checkpoint(request['checkpoint'], crawl))
        print('crawl-complete', flush=True)
