"""Optional, single-page raw/DOM comparison. Never feeds scores or crawl graphs."""
from collections import Counter
import hashlib
import ipaddress
import json
import os
from pathlib import Path
import re
import signal
import socket
import subprocess
import sys
import time
from urllib.parse import urljoin, urlsplit

from safe_http import SafeSession, resolve_addresses
from browser_isolation import secure_context, close_blocked_websockets
from bs4 import BeautifulSoup
from common import HEADERS, _launch_browser, clean_text, parse_html
from link_diagnostics import url_key, validate_fetch_url

LIMITS = dict(requests=40, resource_bytes=2*1024*1024, total_bytes=5*1024*1024,
              redirects=5, network_seconds=20, wall_seconds=45, settle_ms=1500,
              entries=200, value_chars=2000)
NOTE = ('One constrained desktop snapshot of one URL, using the same server response for raw HTML and browser replay. '
        'Only bounded same-origin GET resources are allowed; third-party resources, frames, workers, sockets, '
        'media and subsequent navigations are blocked. Differences are observations, not proof of a JavaScript defect '
        'or Google indexing behavior. No interactions, scrolling or full hydration guarantee; scores and crawl evidence are unchanged.')
FIELDS = ('Title', 'Meta description', 'Canonical', 'H1', 'H2', 'Indexability directives', 'Main textual content', 'Internal links')
CSP = ("default-src 'none'; script-src 'self' 'unsafe-inline' 'unsafe-eval'; style-src 'self' 'unsafe-inline'; "
       "connect-src 'self'; img-src data:; frame-src 'none'; worker-src 'none'; object-src 'none'; "
       "base-uri 'self'; form-action 'none'; sandbox allow-scripts allow-same-origin")


def origin(url):
    p = urlsplit(url)
    return p.scheme.lower(), (p.hostname or '').lower(), p.port or (443 if p.scheme == 'https' else 80)


def scoped_url(url, scope):
    validate_fetch_url(url)
    if origin(url) != scope:
        raise ValueError('Cross-origin request blocked')
    return url


def public_dns(url):
    """Compatibility helper for DNS policy tests; SafeSession pins actual connections."""
    p = urlsplit(url)
    return resolve_addresses(p.hostname, p.port or (443 if p.scheme == 'https' else 80), time.monotonic()+5)


class BoundedTransport:
    """All diagnostic HTTP traffic goes here, including every redirect hop."""
    def __init__(self, url):
        validate_fetch_url(url)
        self.scope = origin(url)
        self.started = time.monotonic()
        self.requests = self.bytes = 0
        self.session = SafeSession(max_total_bytes=LIMITS['total_bytes'])
        self.session.trust_env = False  # no inherited proxy/netrc credentials

    def close(self):
        self.session.close()

    def get(self, url):
        chain = []
        for hop in range(LIMITS['redirects'] + 1):
            scoped_url(url, self.scope)
            remaining = LIMITS['network_seconds'] - (time.monotonic() - self.started)
            if remaining <= 0 or self.requests >= LIMITS['requests'] or self.bytes >= LIMITS['total_bytes']:
                raise ValueError('Request, byte or network time budget exhausted')
            self.requests += 1
            with self.session.get(url, headers=HEADERS, allow_redirects=False, stream=True,
                                  timeout=min(5, remaining), deadline=self.started + LIMITS['network_seconds'],
                                  max_bytes=min(LIMITS['resource_bytes'], LIMITS['total_bytes']-self.bytes)) as response:
                headers = {k.lower(): v for k, v in response.headers.items()}
                if response.status_code in (301, 302, 303, 307, 308) and headers.get('location'):
                    chain.append(dict(url=url, status=response.status_code))
                    url = urljoin(url, headers['location'])
                    continue
                chunks, size = [], 0
                for chunk in response.iter_content(16384):
                    size += len(chunk)
                    self.bytes += len(chunk)
                    if size > LIMITS['resource_bytes'] or self.bytes > LIMITS['total_bytes']:
                        raise ValueError('Decoded response byte budget exceeded')
                    if time.monotonic() - self.started > LIMITS['network_seconds']:
                        raise ValueError('Network time budget exhausted')
                    chunks.append(chunk)
                return dict(url=response.url, status=response.status_code, headers=headers,
                            body=b''.join(chunks), redirects=chain)
        raise ValueError('Redirect budget exceeded')


def _safe_reference(base, value):
    try:
        result = urljoin(base, value)
        return url_key(result) if urlsplit(result).scheme in ('http', 'https') else '[unsupported URL]'
    except ValueError:
        return '[invalid or credential-bearing URL redacted]'


def snapshot(html, final_url, headers=None):
    """DOM text heuristic, not computed visibility or semantic content quality."""
    if len(html if isinstance(html, bytes) else html.encode('utf-8')) > LIMITS['resource_bytes']:
        raise ValueError('HTML/DOM byte budget exceeded')
    charset = re.search(r'charset\s*=\s*["\']?([^;\s"\']+)', (headers or {}).get('content-type', ''), re.I)
    soup = BeautifulSoup(html, 'html.parser', from_encoding=charset.group(1)) if isinstance(html, bytes) and charset else parse_html(html)
    base_tag = soup.find('base', href=True)
    base = urljoin(final_url, base_tag['href']) if base_tag else final_url
    values = {field: [] for field in FIELDS}
    values['Title'] = [clean_text(t.get_text(' ', strip=True)) for t in soup.find_all('title')]
    values['Meta description'] = [clean_text(t.get('content', '')) for t in soup.find_all('meta') if t.get('name', '').lower() == 'description']
    values['Canonical'] = [_safe_reference(base, t['href']) for t in soup.find_all('link', href=True) if 'canonical' in [r.lower() for r in t.get('rel', [])]]
    for tag in ('h1', 'h2'):
        values[tag.upper()] = [clean_text(t.get_text(' ', strip=True)) for t in soup.find_all(tag)]
    values['Indexability directives'] = [t.get('name', '').lower() + ': ' + clean_text(t.get('content', '')).lower()
        for t in soup.find_all('meta') if re.fullmatch(r'robots|googlebot(?:-news)?|bingbot', t.get('name', '').lower())]
    xrobots = (headers or {}).get('x-robots-tag', '')
    if xrobots:
        values['Indexability directives'].append('HTTP X-Robots-Tag (shared response): ' + xrobots)
    for a in soup.find_all('a', href=True):
        href = a['href'].strip()
        if not href or href.startswith('#'):
            continue
        dest = _safe_reference(base, href)
        if urlsplit(dest).hostname == urlsplit(final_url).hostname:
            values['Internal links'].append(json.dumps(dict(url=dest, anchor=clean_text(a.get_text(' ', strip=True)),
                rel=sorted(a.get('rel', []))), ensure_ascii=False, sort_keys=True))
    region = soup.find('main') or soup.find(attrs={'role': 'main'}) or soup.find('article') or soup.body or soup
    region_name = region.name or 'document'
    for tag in list(region.find_all(['head', 'title', 'script', 'style', 'noscript', 'template', 'svg', 'nav', 'header', 'footer', 'aside'])):
        if tag.parent is not None:
            tag.decompose()
    for tag in list(region.find_all(True)):
        if tag.parent is not None and (tag.has_attr('hidden') or tag.get('aria-hidden', '').lower() == 'true'):
            tag.decompose()
    text = clean_text(region.get_text(' ', strip=True))
    values['Main textual content'] = [text] if text else []
    result = dict(fields={}, content_region=region_name, truncated_fields=[])
    for name, items in values.items():
        if name == 'Main textual content':
            result['fields'][name] = dict(values=[text[:2000]] if text else [], count=len(items),
                characters=len(text), sha256=hashlib.sha256(text.encode()).hexdigest(), truncated=False,
                excerpt_shortened=len(text) > 2000)
        else:
            truncated = len(items) > LIMITS['entries'] or any(len(v) > LIMITS['value_chars'] for v in items)
            result['fields'][name] = dict(values=[v[:LIMITS['value_chars']] for v in items[:LIMITS['entries']]],
                                         count=len(items), truncated=truncated)
            if truncated:
                result['truncated_fields'].append(name)
    return result


def compare_snapshots(raw, rendered):
    rows = []
    for name in FIELDS:
        a, b = raw['fields'][name], rendered['fields'][name]
        before, after = a['values'], b['values']
        limited = a['truncated'] or b['truncated']
        same = a.get('sha256') == b.get('sha256') if name == 'Main textual content' else before == after
        change = 'Not assessed (extraction limit)' if limited else 'Unchanged in snapshot' if same else 'Added' if not before else 'Removed' if not after else 'Changed'
        added = list((Counter(after)-Counter(before)).elements()) if not limited and name != 'Main textual content' else []
        removed = list((Counter(before)-Counter(after)).elements()) if not limited and name != 'Main textual content' else []
        rows.append(dict(Element=name, Change=change, Raw=json.dumps(a, ensure_ascii=False),
                         Rendered=json.dumps(b, ensure_ascii=False), Added=json.dumps(added, ensure_ascii=False),
                         Removed=json.dumps(removed, ensure_ascii=False)))
    return rows


def unavailable(url, reason):
    return dict(version='phase3-render-comparison-1', requested_url=url, final_url='', browser_url='',
                status='Not assessed', comparison_available=False, rows=[], raw=None, rendered=None,
                warnings=[reason], scope_note=NOTE, limits=dict(LIMITS), network={}, redirects=[])


class ReplayRoutes:
    """Fail closed: never calls route.continue_ or route.fetch."""
    def __init__(self, initial, transport):
        self.initial, self.transport = initial, transport
        self.scope = origin(initial['url'])
        self.served = False
        self.attempts = 0
        self.blocked = Counter()
        self.navigation_blocked = False

    def handle(self, route):
        request = route.request
        self.attempts += 1
        reason = 'Blocked resource, URL or budget'
        try:
            if request.resource_type == 'document' and (self.served or request.frame.parent_frame is not None):
                self.navigation_blocked = True
                raise ValueError('Navigation/frame blocked')
            if self.attempts > LIMITS['requests']:
                raise ValueError('Browser request budget')
            scoped_url(request.url, self.scope)
            if request.method != 'GET':
                raise ValueError('Only GET permitted')
            if request.resource_type == 'document':
                if self.served or request.frame.parent_frame is not None or url_key(request.url) != url_key(self.initial['url']):
                    self.navigation_blocked = True
                    raise ValueError('Navigation/frame blocked')
                self.served = True
                resource = self.initial
            elif request.resource_type in ('script', 'stylesheet', 'xhr', 'fetch'):
                resource = self.transport.get(request.url)
                if resource.get('redirects'):
                    raise ValueError('Redirected subresource not replayed at an incorrect base URL')
                if resource['status'] >= 400:
                    self.blocked['HTTP resource error'] += 1
            else:
                raise ValueError('Resource type blocked')
            headers = {k: v for k, v in resource['headers'].items() if k in ('content-type', 'content-security-policy', 'x-content-type-options')}
            if request.resource_type == 'document':
                headers['content-security-policy'] = (headers.get('content-security-policy', '') + ', ' + CSP).lstrip(', ')
            route.fulfill(status=resource['status'], headers=headers, body=resource['body'])
        except Exception:
            self.blocked[reason] += 1
            route.abort()


INIT_SCRIPT = """(() => {
    window.__seoPolicyBlocks = 0;
    document.addEventListener('securitypolicyviolation', () => window.__seoPolicyBlocks++);
    for (const name of ['RTCPeerConnection', 'webkitRTCPeerConnection', 'Worker', 'SharedWorker']) {
        Object.defineProperty(window, name, {value: undefined, configurable: false, writable: false});
    }
})()"""


def _compare_page(url, transport=None):
    """Worker entry; injected transport is only used by controlled tests."""
    result = unavailable(url, 'Rendering did not complete')
    owned = transport is None
    transport = transport or BoundedTransport(url)
    stage = 'Raw response collection'
    try:
        initial = transport.get(url)
        result.update(final_url=initial['url'], redirects=initial['redirects'], http_status=initial['status'])
        if not 200 <= initial['status'] < 300 or 'text/html' not in initial['headers'].get('content-type', '').lower():
            result['warnings'] = ['Successful text/html response required; no DOM comparison performed.']
            return result
        raw = snapshot(initial['body'], initial['url'], initial['headers'])
        result['raw'] = raw
        result['raw_html_sha256'] = hashlib.sha256(initial['body']).hexdigest()
        stage = 'Browser launch'
        from playwright.sync_api import sync_playwright
        with sync_playwright() as p:
            browser = _launch_browser(p, ['--disable-background-networking', '--disable-quic', '--dns-prefetch-disable',
                '--force-webrtc-ip-handling-policy=disable_non_proxied_udp'])
            try:
                stage = 'Browser replay/capture'
                shared_blocks = Counter()
                context = secure_context(browser, blocked=shared_blocks, user_agent=HEADERS['User-Agent'],
                    viewport={'width':1440,'height':900}, init_script=False)
                routes = ReplayRoutes(initial, transport)
                routes.blocked = shared_blocks
                context.route('**/*', routes.handle)
                context.add_init_script(INIT_SCRIPT)
                page = context.new_page()
                errors = []
                pending = set()
                page.on('request', lambda request: pending.add(request))
                page.on('requestfinished', lambda request: pending.discard(request))
                page.on('requestfailed', lambda request: pending.discard(request))
                page.on('pageerror', lambda _: errors.append('Script execution error') if len(errors) < 20 else None)
                page.on('download', lambda download: download.cancel())
                page.goto(initial['url'], wait_until='domcontentloaded', timeout=15000)
                page.wait_for_timeout(LIMITS['settle_ms'])
                close_blocked_websockets(context)
                html = page.content()
                result['browser_url'] = page.url
                result['rendered_dom_sha256'] = hashlib.sha256(html.encode('utf-8')).hexdigest()
                policy_blocks = page.evaluate('window.__seoPolicyBlocks || 0')
                if url_key(page.url) != url_key(initial['url']) or routes.navigation_blocked:
                    result['warnings'] = ['Client navigation changed or attempted to replace the paired document; comparison not assessed.']
                    return result
                rendered = snapshot(html, initial['url'], initial['headers'])
                warnings = []
                if routes.blocked or policy_blocks:
                    warnings.append('Resources were blocked or failed under the replay policy; missing content may reflect these restrictions.')
                if errors:
                    warnings.append('Script execution errors occurred; the DOM may be incomplete.')
                if pending:
                    warnings.append('Requests remained pending at capture; the DOM may be incomplete.')
                if raw['truncated_fields'] or rendered['truncated_fields']:
                    warnings.append('Extraction limits exceeded; affected fields are not assessed. See snapshot truncation markers.')
                if raw['content_region'] != rendered['content_region']:
                    warnings.append('Main content container changed; textual differences may reflect heuristic selection.')
                directives = ' '.join(raw['fields']['Indexability directives']['values'])
                if re.search(r'\b(noindex|none)\b', directives, re.I):
                    warnings.append('Raw noindex/none directive observed. JavaScript removal does not establish indexability; Google may skip rendering.')
                result.update(status='Compared (limited snapshot)', comparison_available=True,
                    rows=compare_snapshots(raw, rendered), rendered=rendered, warnings=warnings,
                    network=dict(browser_requests=routes.attempts, blocked=dict(routes.blocked), csp_violations=policy_blocks,
                                 pending_at_capture=len(pending), settle_ms=LIMITS['settle_ms'],
                                 http_requests=transport.requests, decoded_bytes=transport.bytes),
                    browser_version=browser.version)
            finally:
                browser.close()
    except Exception as exc:
        result['warnings'] = [stage + ' failed (' + type(exc).__name__ + '); verify browser availability, access and resource limits. Comparison not assessed.']
    finally:
        if not result['network']:
            result['network'] = dict(http_requests=transport.requests, decoded_bytes=transport.bytes)
        if owned:
            transport.close()
    return result


def compare_url(url):
    """Hard outer timeout isolates hostile scripts, DNS stalls and browser hangs."""
    try:
        validate_fetch_url(url)
    except ValueError:
        return unavailable('[invalid URL]', 'Only public HTTP(S) URLs without credentials are supported.')
    flags = {'creationflags': subprocess.CREATE_NEW_PROCESS_GROUP} if os.name == 'nt' else {'start_new_session': True}
    try:
        process = subprocess.Popen([sys.executable, str(Path(__file__).resolve()), '--worker'],
            stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.DEVNULL, text=True, encoding='utf-8', **flags)
    except OSError:
        return unavailable(url, 'Isolated worker could not start; no comparison is available.')
    try:
        output, _ = process.communicate(json.dumps({'url': url}), timeout=LIMITS['wall_seconds'])
        if process.returncode:
            return unavailable(url, 'Isolated worker failed; no comparison is available.')
        return json.loads(output)
    except subprocess.TimeoutExpired:
        cleanup_failed = False
        try:
            if os.name == 'nt':
                cleanup_failed = subprocess.run(['taskkill', '/PID', str(process.pid), '/T', '/F'], capture_output=True, timeout=5).returncode != 0
            else:
                os.killpg(process.pid, signal.SIGKILL)
        except (OSError, subprocess.TimeoutExpired):
            cleanup_failed = True
        finally:
            process.kill()
            process.communicate(timeout=5)
        return unavailable(url, '45-second isolated execution deadline exceeded; no comparison is available.' +
                           (' Process-tree cleanup could not be confirmed; close leftover browser processes.' if cleanup_failed else ''))
    except (ValueError, OSError):
        return unavailable(url, 'Invalid worker result; no comparison is available.')


if __name__ == '__main__' and sys.argv[1:] == ['--worker']:
    print(json.dumps(_compare_page(json.load(sys.stdin)['url']), ensure_ascii=True))
