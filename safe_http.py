"""Connection-bound, GET-only HTTP for audit collectors (not browser isolation).

No environment proxies/netrc, cookie jar, global DNS patch, or automatic redirects.
The caller owns redirect scope and evidence. DNS workers are bounded; an OS resolver
that outlives its deadline cannot be killed here (C2/C3 containment remains needed).
"""
import http.client
import ipaddress
import math
import queue
import socket
import ssl
import threading
import time
import zlib
from urllib.parse import urlsplit, quote

from requests import Response
from requests.structures import CaseInsensitiveDict
from requests.utils import get_encoding_from_headers
from link_diagnostics import validate_fetch_url

_DNS_SLOTS = threading.BoundedSemaphore(4)
_REDIRECTS = (301, 302, 303, 307, 308)


class TransportError(ValueError):
    """A sanitized blocked/unknown request, never an HTTP failure status."""


def remaining(deadline):
    seconds = deadline - time.monotonic()
    if seconds <= 0:
        raise TransportError('HTTP operation deadline exceeded')
    return seconds


def _public_address(value):
    ip = ipaddress.ip_address(value)
    if not ip.is_global or ip.is_multicast or ip.is_reserved or ip.is_unspecified:
        return False
    if ip.version == 4 and any(ip in ipaddress.ip_network(n) for n in ('192.0.0.0/24', '192.88.99.0/24')):
        return False
    if ip.version == 6:
        if ip.ipv4_mapped is not None:
            return _public_address(str(ip.ipv4_mapped))
        # Transition/translation ranges can reach IPv4 endpoints indirectly.
        if ip.sixtofour is not None or ip.teredo is not None:
            return False
        if any(ip in ipaddress.ip_network(n) for n in ('64:ff9b::/96', '64:ff9b:1::/48', '2001::/23')):
            return False
    return True


def resolve_addresses(host, port, deadline):
    """Resolve once and reject the complete answer set before any connection."""
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        if not _DNS_SLOTS.acquire(blocking=False):
            raise TransportError('DNS capacity unavailable')
        result = queue.Queue(maxsize=1)
        def run():
            try:
                result.put((True, socket.getaddrinfo(host, port, type=socket.SOCK_STREAM)))
            except Exception:
                result.put((False, None))
            finally:
                _DNS_SLOTS.release()
        try:
            threading.Thread(target=run, daemon=True, name='audit-dns').start()
        except Exception:
            _DNS_SLOTS.release()
            raise TransportError('DNS worker unavailable') from None
        try:
            ok, rows = result.get(timeout=remaining(deadline))
        except queue.Empty:
            raise TransportError('DNS deadline exceeded') from None
        if not ok:
            raise TransportError('DNS resolution failed')
    else:
        family = socket.AF_INET6 if ip.version == 6 else socket.AF_INET
        rows = [(family, socket.SOCK_STREAM, 0, '', (str(ip), port))]
    approved = []
    for family, kind, proto, _, address in rows:
        if family not in (socket.AF_INET, socket.AF_INET6) or kind != socket.SOCK_STREAM:
            raise TransportError('Unsupported DNS address')
        value = address[0]
        if '%' in value or not _public_address(value):
            raise TransportError('Non-public DNS destination blocked')
        # Never use DNS-provided ports, scope IDs or names at connection time.
        target = (str(ipaddress.ip_address(value)), port, 0, 0) if family == socket.AF_INET6 else (str(ipaddress.ip_address(value)), port)
        entry = (family, target)
        if entry not in approved:
            approved.append(entry)
    if not approved or len(approved) > 32:
        raise TransportError('Empty or excessive DNS address set')
    remaining(deadline)
    return approved


def _target(url):
    validate_fetch_url(url)
    p = urlsplit(url)
    host = p.hostname.encode('idna').decode('ascii').lower()
    # Revalidate IDNA output (e.g. Unicode digits/dots can map to numeric IPs).
    authority = '[' + host + ']' if ':' in host else host
    if p.port is not None:
        authority += ':' + str(p.port)
    validate_fetch_url(p.scheme + '://' + authority + '/')
    if p.port == 0:
        raise TransportError('Invalid destination port')
    target = quote(p.path or '/', safe="/%:@!$&'()*+,;=-._~")
    if p.query or '?' in url.split('#', 1)[0]:
        target += '?' + quote(p.query, safe="/%?:@!$&'()*+,;=-._~")
    return p.scheme.lower(), host, p.port or (443 if p.scheme == 'https' else 80), authority, target


class _DeadlineConnection(http.client.HTTPConnection):
    """Socket is installed before request(); never reconnect by hostname."""
    def connect(self):
        raise TransportError('Implicit reconnect blocked')


class SafeSession:
    trust_env = False

    def __init__(self, max_total_bytes=None):
        self.max_total_bytes = max_total_bytes
        self.decoded_bytes = 0

    def __enter__(self):
        return self

    def __exit__(self, *args):
        self.close()

    def close(self):
        pass  # every get owns/closes its socket; no persistent credentials/cookies

    def get(self, url, *, headers=None, timeout=20, allow_redirects=False,
            stream=True, deadline=None, max_bytes=5*1024*1024):
        if allow_redirects:
            raise TransportError('Automatic redirects prohibited')
        if not isinstance(timeout, (int, float)) or not math.isfinite(timeout) or timeout <= 0:
            raise TransportError('Invalid HTTP timeout')
        if not isinstance(max_bytes, int) or max_bytes < 1 or max_bytes > 5*1024*1024:
            raise TransportError('Invalid HTTP byte limit')
        if deadline is not None and (not isinstance(deadline, (int, float)) or not math.isfinite(deadline)):
            raise TransportError('Invalid operation deadline')
        if self.max_total_bytes is not None:
            max_bytes = min(max_bytes, self.max_total_bytes - self.decoded_bytes)
            if max_bytes < 1:
                raise TransportError('Session decoded byte budget exceeded')
        deadline = min(deadline, time.monotonic()+60) if deadline is not None else time.monotonic()+60
        # Failed transfers conservatively consume their allocation: retries cannot
        # evade a session budget through malformed/oversized or partial bodies.
        start_bytes = self.decoded_bytes
        try:
            return self._get(url, headers or {}, timeout, deadline, max_bytes)
        except TransportError:
            if self.max_total_bytes is not None:
                self.decoded_bytes = max(self.decoded_bytes, start_bytes + max_bytes)
            raise
        except Exception:
            if self.max_total_bytes is not None:
                self.decoded_bytes = max(self.decoded_bytes, start_bytes + max_bytes)
            raise TransportError('HTTP request failed or blocked') from None

    def _get(self, url, headers, timeout, deadline, max_bytes):
        scheme, host, port, authority, target = _target(url)
        addresses = resolve_addresses(host, port, deadline)
        request_headers = {k: v for k, v in headers.items() if k.lower() in ('user-agent', 'accept', 'accept-language')}
        request_headers.update({'Host': authority, 'Accept-Encoding': 'gzip', 'Connection': 'close'})
        for family, address in addresses:
            seconds = remaining(deadline)
            sock = socket.socket(family, socket.SOCK_STREAM)
            owned = [sock]
            def abort(sockets=owned):
                for s in list(sockets):
                    try: s.shutdown(socket.SHUT_RDWR)
                    except OSError: pass
                    try: s.close()
                    except OSError: pass
            timer = threading.Timer(seconds, abort)
            timer.daemon = True
            connection = response = None
            timer.start()
            try:
                sock.settimeout(min(timeout, remaining(deadline)))
                try:
                    sock.connect(address)  # numeric sockaddr: no second name resolution
                except OSError:
                    remaining(deadline)
                    continue  # only previously approved addresses may be tried
                if scheme == 'https':
                    context = ssl.create_default_context()  # CERT_REQUIRED and check_hostname
                    sock = context.wrap_socket(sock, server_hostname=host, do_handshake_on_connect=False)
                    owned.append(sock)
                    sock.do_handshake()
                sock.settimeout(min(timeout, remaining(deadline)))
                connection = _DeadlineConnection(host, port, timeout=timeout)
                connection.sock = sock
                connection.request('GET', target, headers=request_headers)
                response = connection.getresponse()
                out = Response()
                out.url, out.status_code, out.reason = url, response.status, response.reason
                out.headers = CaseInsensitiveDict(response.getheaders())
                out.encoding = get_encoding_from_headers(out.headers)
                out.history = []
                body = bytearray()
                if response.status not in _REDIRECTS or not out.headers.get('Location'):
                    encoding = out.headers.get('Content-Encoding', '').lower().strip()
                    if encoding not in ('', 'identity', 'gzip'):
                        raise TransportError('Unsupported response encoding')
                    decoder = zlib.decompressobj(16+zlib.MAX_WBITS) if encoding == 'gzip' else None
                    wire = 0
                    while not response.isclosed():
                        sock.settimeout(min(timeout, remaining(deadline)))
                        chunk = response.read1(min(16384, max_bytes+1))
                        if not chunk:
                            break
                        wire += len(chunk)
                        if wire > max_bytes:
                            raise TransportError('Encoded response byte limit exceeded')
                        data = decoder.decompress(chunk, max_bytes-len(body)+1) if decoder else chunk
                        self.decoded_bytes += len(data)
                        body.extend(data)
                        if len(body) > max_bytes or (decoder and decoder.unconsumed_tail):
                            raise TransportError('Decoded response byte limit exceeded')
                    if decoder and (not decoder.eof or decoder.unused_data):
                        raise TransportError('Incomplete or concatenated compressed response')
                    if response.length not in (None, 0):
                        raise TransportError('Incomplete HTTP response')
                remaining(deadline)
                out._content, out._content_consumed = bytes(body), True
                return out
            finally:
                timer.cancel()
                if response is not None:
                    response.close()
                if connection is not None:
                    connection.close()
                abort()
        raise TransportError('Approved destinations unreachable')
