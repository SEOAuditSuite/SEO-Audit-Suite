"""C2A application-level policy; not OS/browser egress containment (C3).

Routed GETs use C1 numeric-IP connections. No continue_/fetch fallback. Cookies,
authentication, unsafe methods and implicit browser network access are not supported.
"""
from collections import Counter
import os
import time
from urllib.parse import urljoin, urlsplit

from safe_http import SafeSession, TransportError, _target
from link_diagnostics import validate_fetch_url

LIMITS = dict(page_requests=100, crawl_requests=500, resource_bytes=5*1024*1024,
              page_bytes=20*1024*1024, crawl_bytes=100*1024*1024,
              page_network_seconds=30, redirects=10, evidence_entries=200)
NOTE = ('C2A anonymous GET browser broker; application interception is not complete network isolation. '
        'Blocked resources can limit rendered SEO evidence. C2B supervised crawler/diagnostic deadlines apply; C3 containment remains pending.')
DOC_POLICY = "frame-src 'none'; worker-src 'none'; object-src 'none'; form-action 'none'"
INIT_SCRIPT = """(() => {
    window.__seoBrowserPolicyBlocks = 0;
    document.addEventListener('securitypolicyviolation', () => window.__seoBrowserPolicyBlocks++);
    for (const name of ['RTCPeerConnection','webkitRTCPeerConnection','WebTransport','Worker','SharedWorker']) {
        Object.defineProperty(window, name, {value: undefined, configurable: false, writable: false});
    }
})()"""


def launch_browser(playwright, launch_args=None):
    args = list(launch_args or [])
    for flag in ['--disable-background-networking', '--disable-quic', '--dns-prefetch-disable',
                 '--force-webrtc-ip-handling-policy=disable_non_proxied_udp']:
        if flag not in args:
            args.append(flag)
    # Only bootstrap/environment paths, not API keys, inherited proxies or credentials.
    env = {k:v for k,v in os.environ.items() if k.upper() in (
        'PATH','SYSTEMROOT','WINDIR','TEMP','TMP','HOME','LOCALAPPDATA',
        'XDG_RUNTIME_DIR','DISPLAY','WAYLAND_DISPLAY')}
    options = dict(headless=True, chromium_sandbox=True, args=args, env=env)
    for channel in ('chrome', None):
        try:
            return playwright.chromium.launch(**options, **({'channel':channel} if channel else {}))
        except Exception:
            pass  # Both attempts retain the policy; never retry without sandbox.
    raise RuntimeError('Secure browser launch unavailable; verify Chrome/Chromium and sandbox support')


def secure_context(browser, *, user_agent, viewport, blocked=None, init_script=True, on_block=None, defer_popup_close=False):
    context = browser.new_context(user_agent=user_agent, viewport=viewport,
        service_workers='block', accept_downloads=False, ignore_https_errors=False,
        permissions=[], proxy={'server':'http://127.0.0.1:9', 'bypass':'<-loopback>'})
    count = blocked if blocked is not None else Counter()
    def notify(reason):
        if on_block is not None: on_block(reason)
        else: count.update([reason])
    pending_websockets = []
    context._seo_pending_websockets = pending_websockets
    def reject_websocket(ws):
        notify('WebSocket blocked')
        # Playwright dispatches this handler on its asyncio loop, not the normal
        # sync API fibre. Calling sync ws.close() here waits on that same loop.
        # Returning without connect_to_server() keeps the server disconnected.
        pending_websockets.append(ws)
    context.route_web_socket('**/*', reject_websocket)
    first = []
    pending_popups = []
    context._seo_pending_popups = pending_popups
    def on_page(page):
        if first:
            notify('Popup blocked')
            if defer_popup_close:
                pending_popups.append(page)
            else:
                page.close()
            return
        first.append(page)
        page.on('download', lambda download: (notify('Download blocked'), download.cancel()))
    context.on('page', on_page)
    if init_script:
        context.add_init_script(INIT_SCRIPT)
    return context


def close_blocked_popups(context):
    """Close rejected pages from regular control flow, not a sync event callback.

    GetBroker rejects their requests independently before any C1 fetch. Closing
    inside the page event can wait on routing work still queued by that dispatch.
    """
    close_blocked_websockets(context)
    pending = context._seo_pending_popups
    while pending:
        page = pending.pop(0)
        if not page.is_closed():
            page.close()


def close_blocked_websockets(context):
    """Drain from normal synchronous control flow, never the socket callback."""
    pending = getattr(context, '_seo_pending_websockets', None)
    if not isinstance(pending, list):
        return  # compatibility with captures not created by the shared context
    while pending:
        pending.pop(0).close()


def _origin(url):
    p=urlsplit(url)
    return p.scheme.lower(), (p.hostname or '').encode('idna').decode('ascii').lower(), p.port or (443 if p.scheme=='https' else 80)


def _navigation_key(url):
    # Match Chromium's IDNA/default-port representation to the exact C1 wire target.
    # Do not normalize slash, query, percent-escape case or dot-segment identity.
    scheme, host, port, authority, target = _target(url)
    host_part='['+host+']' if ':' in host else host
    authority=host_part if port==(443 if scheme=='https' else 80) else authority
    return scheme+'://'+authority+target


def _evidence_url(url):
    # Request URLs can contain secrets; persist path/origin only, never query/userinfo.
    try:
        p=urlsplit(url)
        host=p.hostname or ''
        authority='['+host+']' if ':' in host else host
        if p.port: authority+=':'+str(p.port)
        return p.scheme+'://'+authority+p.path
    except ValueError:
        return '[invalid URL]'


class GetBroker:
    def __init__(self, headers, limits=None):
        self.headers = headers
        self.limits = dict(LIMITS, **(limits or {}))
        self.session = SafeSession(max_total_bytes=self.limits['crawl_bytes'])
        self.requests = 0
        self.page_requests = 0
        self.blocked = Counter()
        self.rows = []
        self.evidence_count = 0
        self.pages = []
        self.page = None
        self.allowed_documents = set()
        self.current = {}
        self._page_blocked = Counter()
        self.cached_document = None

    def begin_navigation(self, url):
        validate_fetch_url(url)
        self.page_requests = 0
        self.page_start_bytes = self.session.decoded_bytes
        self.deadline = time.monotonic()+self.limits['page_network_seconds']
        self.allowed_documents = {_navigation_key(url)}
        self.document_origin = _origin(url)
        self.redirects = 0
        self._page_blocked.clear()
        if self.cached_document is not None: self.cached_document.close()
        self.cached_document = None
        self.current = dict(url=_evidence_url(url), requests=0, blocked={}, partial_render=False)
        self.pages.append(self.current)
        if len(self.pages)>501: self.pages.pop(0)

    def evidence(self):
        self.current.update(requests=self.page_requests, blocked=dict(self.page_blocked),
                            partial_render=bool(self.page_blocked))
        return dict(policy='c2a-get-broker-1', requests=self.requests,
                    byte_budget_used=self.session.decoded_bytes, blocked=dict(self.blocked),
                    partial_render=bool(self.blocked), pages=list(self.pages), resources=list(self.rows),
                    evidence_truncated=self.evidence_count>len(self.rows), note=NOTE)

    @property
    def page_blocked(self):
        return self._page_blocked

    def record_resource(self, url, kind, status, result):
        self.evidence_count += 1
        if len(self.rows)<self.limits['evidence_entries']:
            self.rows.append(dict(url=_evidence_url(url), resource_type=kind,
                                  status=status, result=result))

    def record_block(self, reason):
        self.blocked.update([reason])
        self._page_blocked.update([reason])
        self.current.update(blocked=dict(self._page_blocked), partial_render=True)

    def close(self):
        if self.cached_document is not None: self.cached_document.close()
        self.session.close()

    def _fetch(self, url):
        if self.page_requests >= self.limits['page_requests'] or self.requests >= self.limits['crawl_requests']:
            raise TransportError('Request budget exhausted')
        self.page_requests += 1
        self.requests += 1
        max_bytes = min(self.limits['resource_bytes'],
                        self.limits['page_bytes']-(self.session.decoded_bytes-self.page_start_bytes))
        if max_bytes < 1 or time.monotonic() >= self.deadline:
            raise TransportError('Page byte or network time budget exhausted')
        return self.session.get(url, headers=self.headers, timeout=5,
            allow_redirects=False, deadline=self.deadline, max_bytes=max_bytes)

    def prepare_navigation(self, url):
        """Resolve navigation redirects in C1 before Chromium ever sees a Location.

        Native redirected requests are not reliably intercepted hop by hop.
        Capture the final document at its actual URL and preserve chain separately.
        """
        chain = []
        for _ in range(self.limits['redirects']+1):
            validate_fetch_url(url)
            try:
                response = self._fetch(url)
            except Exception:
                self.record_resource(url, 'document', None, 'Navigation fetch failed or blocked; HTTP status unknown')
                raise
            self.record_resource(url, 'document', response.status_code, 'Observed navigation response')
            if response.status_code in (301,302,303,307,308) and response.headers.get('location'):
                chain.append(dict(url=url,status=response.status_code))
                url = urljoin(url,response.headers['location'])
                response.close()
                continue
            if 'attachment' in response.headers.get('content-disposition','').lower():
                response.close()
                raise TransportError('Download response blocked')
            self.cached_document = response
            self.document_origin = _origin(url)
            self.allowed_documents = {_navigation_key(url)}
            return url, chain
        raise TransportError('Redirect budget exhausted')

    def handle(self, route):
        request = route.request
        reason = 'Request failed or destination blocked; HTTP status unknown'
        status = None
        try:
            if self.page is None or request.frame.page != self.page or request.frame.parent_frame is not None:
                reason = 'Popup or frame blocked'
                raise TransportError(reason)
            if request.method != 'GET':
                reason = 'Non-GET request blocked'
                raise TransportError(reason)
            validate_fetch_url(request.url)
            if request.resource_type not in ('document','script','stylesheet','image','font','xhr','fetch'):
                reason = 'Resource type blocked'
                raise TransportError(reason)
            if request.resource_type in ('xhr','fetch') and _origin(request.url) != self.document_origin:
                reason = 'Cross-origin API request blocked'
                raise TransportError(reason)
            if request.resource_type == 'document' and _navigation_key(request.url) not in self.allowed_documents:
                reason = 'Unrequested navigation blocked'
                raise TransportError(reason)
            if (self.page_requests >= self.limits['page_requests'] or
                self.requests >= self.limits['crawl_requests']):
                reason = 'Request budget exhausted'
                raise TransportError(reason)
            if request.resource_type == 'document':
                response = self.cached_document
                self.cached_document = None
                self.allowed_documents.clear()
                if response is None:
                    reason = 'Unprepared document blocked'
                    raise TransportError(reason)
            else:
                response = self._fetch(request.url)
            try:
                status = response.status_code
                headers = {k:v for k,v in response.headers.items() if k.lower() in (
                    'content-type','content-security-policy','x-content-type-options',
                    'access-control-allow-origin','access-control-allow-methods','access-control-allow-headers',
                    'cross-origin-resource-policy','cross-origin-opener-policy','cross-origin-embedder-policy')}
                if 'attachment' in response.headers.get('content-disposition','').lower():
                    reason = 'Download response blocked'
                    raise TransportError(reason)
                if status in (301,302,303,307,308) and response.headers.get('location'):
                    # No native redirects: Playwright may not route their next hop.
                    # Do not replay a redirected resource under the wrong base URL.
                    reason = 'Redirected subresource not replayed; final base URL unverified'
                    raise TransportError(reason)
                if request.resource_type=='document':
                    headers['content-security-policy'] = (response.headers.get('content-security-policy','')+', '+DOC_POLICY).lstrip(', ')
                route.fulfill(status=status, headers=headers, body=response.content)
                if status >= 400:
                    self.blocked.update(['Observed HTTP resource error'])
                    self._page_blocked.update(['Observed HTTP resource error'])
                reason = 'Observed HTTP response'
            finally:
                response.close()
        except Exception:
            self.record_block(reason)
            route.abort()
        finally:
            self.current.update(requests=self.page_requests, blocked=dict(self._page_blocked),
                                partial_render=bool(self._page_blocked))
            self.record_resource(request.url, request.resource_type, status, reason)
