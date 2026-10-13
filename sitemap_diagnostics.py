"""Bounded sitemap inventory and conservative, sample-scoped reconciliation."""
import gzip
import base64
import io
import math
import time
from collections import deque, defaultdict
from urllib.parse import urlsplit, urljoin
from lxml import etree
from common import fetch, normalize_url
from link_diagnostics import url_key, validate_fetch_url, analyze_links, crawl_status_cache, status_evidence

LIMITS = dict(documents=20, pages=2000, depth=3, document_bytes=5*1024*1024,
              total_bytes=10*1024*1024, seconds=60, timeout=10)
NOTE = ('Potential orphan candidates have no observed incoming links from other pages in the navigation sample. '
        'This is limited evidence, not proof of an orphan or indexing status. Sitemap URLs never seed the navigation crawl. '
        'Canonical hints do not merge resources. Unknown page status remains unverified.')


def _decode_sitemap(content, max_bytes):
    data = content.encode('utf-8') if isinstance(content, str) else content
    if data[:2] == b'\x1f\x8b':
        with gzip.GzipFile(fileobj=io.BytesIO(data)) as stream:
            data = stream.read(max_bytes + 1)
    if len(data) > max_bytes:
        raise ValueError('Decoded sitemap exceeds document byte limit')
    return data


def parse_sitemap_document(content, max_bytes=LIMITS['document_bytes']):
    """Parse direct protocol entries only; never recover malformed XML or load entities."""
    return _parse_xml(_decode_sitemap(content, max_bytes))


def _parse_xml(data):
    parser = etree.XMLParser(resolve_entities=False, load_dtd=False, no_network=True,
                             recover=False, huge_tree=False)
    root = etree.fromstring(data, parser)
    if root.getroottree().docinfo.doctype or any(isinstance(n, etree._Entity) for n in root.iter()):
        raise ValueError('DTD and entity declarations are not supported')
    q = etree.QName(root)
    if q.localname not in ('urlset', 'sitemapindex') or q.namespace not in (None, 'http://www.sitemaps.org/schemas/sitemap/0.9'):
        raise ValueError('Unsupported sitemap root or namespace')
    tag = lambda name: '{' + q.namespace + '}' + name if q.namespace else name
    urls = []
    for entry in root:
        if entry.tag != tag('url' if q.localname == 'urlset' else 'sitemap'):
            continue
        locs = entry.findall(tag('loc'))
        if len(locs) != 1 or len(locs[0]) or not locs[0].text:
            raise ValueError('Entry requires one plain-text loc')
        value = locs[0].text.strip()
        if len(value) > 8192:
            raise ValueError('Sitemap URL exceeds length limit')
        urls.append(value)
    return dict(kind=q.localname, urls=urls, decoded_bytes=len(data))


def _evidence_url(url):
    try:
        parts = urlsplit(url)
        if parts.username is not None or parts.password is not None:
            return '[credential-bearing URL redacted]'
    except ValueError:
        return '[invalid URL]'
    return url


def sitemap_scope_validator(base):
    host = (urlsplit(base).hostname or '').lower()
    def guard(url):
        validate_fetch_url(url)
        if (urlsplit(url).hostname or '').lower() != host:
            raise ValueError('Sitemap discovery leaves audit hostname')
    return guard


def discover_sitemap_inventory(base, discovery=None, sitemap_url='', limits=None, fetcher=None, audit_hostname=None):
    """Document fetches only. Same-host checks run before every uncached redirect hop."""
    if set(limits or {}) - set(LIMITS):
        raise ValueError('Unknown sitemap limit')
    limits = dict(LIMITS, **(limits or {}))
    for name in LIMITS:
        if (isinstance(limits[name], bool) or not isinstance(limits[name], (int, float))
                or not math.isfinite(limits[name]) or limits[name] <= 0 or limits[name] > LIMITS[name]
                or (name not in ('seconds', 'timeout') and not isinstance(limits[name], int))):
            raise ValueError('Limits must be positive and no greater than defaults: ' + name)
    base = normalize_url(base)
    validate_fetch_url(base)
    host = (audit_hostname or urlsplit(base).hostname or '').lower()
    start = time.monotonic()
    result = dict(version='phase2-sitemaps-1', audit_hostname=host, limits=limits,
                  documents=[], inventory=[], warnings=[], excluded=[], complete=False)
    def guard(url):
        validate_fetch_url(url)
        if (urlsplit(url).hostname or '').lower() != host:
            raise ValueError('Sitemap document leaves audit hostname')
        if time.monotonic() - start >= limits['seconds']:
            raise ValueError('Sitemap elapsed-time budget reached')
    discovery = discovery or {}
    roots = []
    root_keys = set()
    def add_root(value):
        if value in root_keys:
            return
        if len(roots) >= limits['documents']:
            result['warnings'].append('Sitemap root queue limit reached; inventory truncated.')
            return
        roots.append(value)
        root_keys.add(value)
    if sitemap_url:
        add_root(sitemap_url)
    robots = discovery.get('robots') or {}
    if robots.get('status') == 200 and (urlsplit(robots.get('url', base)).hostname or '').lower() == host:
        for line in robots.get('text', '').splitlines():
            key, sep, value = line.partition(':')
            if sep and key.strip().lower() == 'sitemap':
                add_root(value.split('#', 1)[0].strip())
    add_root(urljoin(base, '/sitemap.xml'))
    queue = deque((u, 0) for u in roots if u)
    seen, entries, total = set(), {}, 0
    while queue:
        if len(result['documents']) >= limits['documents'] or time.monotonic() - start >= limits['seconds']:
            result['warnings'].append('Document count or elapsed-time limit reached; inventory truncated.')
            break
        raw, depth = queue.popleft()
        try:
            guard(raw)
            key = url_key(raw)
        except ValueError as exc:
            result['excluded'].append(dict(URL=_evidence_url(raw), Reason=str(exc)))
            result['warnings'].append('A sitemap document was excluded; discovery is incomplete.')
            continue
        if key in seen:
            continue
        if total >= limits['total_bytes']:
            queue.appendleft((raw, depth))
            result['warnings'].append('Total decoded XML byte limit reached; inventory truncated.')
            break
        seen.add(key)
        doc = dict(URL=raw, Final_URL='', Depth=depth, Status=None, Pages=0, Decoded_bytes=0, Error='')
        result['documents'].append(doc)
        try:
            cached = discovery.get('sitemap') or {}
            if key == url_key(urljoin(base, '/sitemap.xml')) and cached.get('status') == 200:
                final = cached.get('url', raw)
                for hop in cached.get('redirect_chain', []):
                    guard(hop['url'])
                doc['Redirect_evidence'] = ('Recorded cached redirect chain' if 'redirect_chain' in cached
                                            else 'Cached intermediate redirect history unavailable')
                doc['Redirect_chain'] = cached.get('redirect_chain', [])
                guard(final)
                content = (base64.b64decode(cached['content_base64'], validate=True)
                           if 'content_base64' in cached else cached.get('text', ''))
                status = cached['status']
            else:
                response = (fetcher(raw, timeout=limits['timeout'], url_validator=guard) if fetcher else
                            fetch(raw, timeout=limits['timeout'], url_validator=guard,
                                  deadline=start + limits['seconds']))
                final, content, status = response.url, response.content, response.status_code
                guard(final)
                doc['Redirect_chain'] = [{'url': h.url, 'status': h.status_code} for h in getattr(response, 'history', [])]
                doc['Redirect_evidence'] = 'Collection fetch uses per-hop hostname validator'
            doc.update(Final_URL=final, Status=status)
            if status != 200:
                raise ValueError('Sitemap returned non-200 response')
            remaining_bytes = limits['total_bytes'] - total
            if remaining_bytes <= 0:
                raise ValueError('Total decoded XML byte limit reached')
            try:
                decoded = _decode_sitemap(content, min(limits['document_bytes'], remaining_bytes))
            except ValueError as exc:
                if remaining_bytes < limits['document_bytes'] and 'byte limit' in str(exc):
                    raise ValueError('Total decoded XML byte limit reached') from exc
                raise
            # Malformed XML consumes the same budget as accepted XML.
            total += len(decoded)
            doc['Decoded_bytes'] = len(decoded)
            parsed = _parse_xml(decoded)
            doc['Kind'] = parsed['kind']
            if parsed['kind'] == 'sitemapindex':
                if depth >= limits['depth'] and parsed['urls']:
                    raise ValueError('Sitemap index depth limit reached')
                # Bound queued documents as well as fetched documents.
                for child in parsed['urls']:
                    if len(queue) >= limits['documents']:
                        result['warnings'].append('Sitemap queue limit reached; inventory truncated.')
                        break
                    queue.append((child, depth + 1))
            else:
                for page in parsed['urls']:
                    try:
                        validate_fetch_url(page)
                        page_key = url_key(page)
                    except ValueError as exc:
                        result['excluded'].append(dict(URL=_evidence_url(page), Reason=str(exc)))
                        result['warnings'].append('Invalid page loc excluded.')
                        continue
                    if page_key not in entries:
                        if len(entries) >= limits['pages']:
                            result['warnings'].append('Page inventory limit reached; inventory truncated.')
                            break
                        entries[page_key] = dict(URL=page_key, Raw_URL=page, Sitemaps=[])
                    if final not in entries[page_key]['Sitemaps']:
                        entries[page_key]['Sitemaps'].append(final)
                    doc['Pages'] += 1
        except Exception as exc:
            doc['Error'] = (str(exc) if isinstance(exc, ValueError) else
                            type(exc).__name__ + ': sitemap fetch or parsing failed; verify access and format')
            result['warnings'].append('Sitemap document failed or was truncated: ' + raw)
            if 'Total decoded XML byte limit reached' in str(exc):
                break
    result.update(inventory=list(entries.values()), remaining_documents=len(queue), decoded_bytes=total,
                  complete=not queue and not result['warnings'])
    result['warnings'] = list(dict.fromkeys(result['warnings']))
    return result


def analyze_sitemap_candidates(crawl, sitemap, links=None):
    """Reconcile without requesting pages; preserve conflicting aliases as unknown evidence."""
    links = links if links is not None else analyze_links(crawl)
    host = links['audit_hostname']
    aliases = links['aliases']
    destinations = defaultdict(set)
    records = list(crawl.get('status_checks', []))
    records += [status_evidence(p) for p in crawl.get('pages', [])]
    for r in records:
        if r.get('redirect_hops') and r.get('final_url') and isinstance(r.get('status'), int) and r['status'] >= 100:
            for source in [r['url']] + [h['url'] for h in r.get('redirect_chain', [])]:
                destinations[url_key(source)].add(url_key(r['final_url']))
    def resolve(key):
        visited = set()
        while key in aliases:
            if key in visited or len(destinations[key]) > 1:
                return key, False
            visited.add(key)
            key = aliases[key]
        return key, True
    ambiguous = {key for key, values in destinations.items() if len(values) > 1}
    for record in records:
        if record.get('redirect_hops') and record.get('final_url'):
            status = record.get('status')
            if not isinstance(status, int) or not 200 <= status < 300:
                ambiguous.add(url_key(record['url']))
                ambiguous.add(url_key(record['final_url']))
    ambiguous.update(value for key in list(ambiguous) for value in destinations[key])
    cache = crawl_status_cache(crawl)
    inventory = {r['URL']: r for r in links['inventory']}
    seed = (crawl.get('coverage') or {}).get('seed_url') or (crawl['pages'][0].url if crawl.get('pages') else '')
    seed = resolve(url_key(seed))[0] if seed else ''
    valid_graph = bool(crawl.get('coverage') and any(200 <= p.status < 300 for p in crawl.get('pages', [])) and sitemap.get('inventory') and host and sitemap['audit_hostname'] == host)
    pages = {url_key(p.final_url): p for p in crawl.get('pages', [])}
    rows = []
    for entry in sitemap['inventory']:
        key = entry['URL']
        final, reliable = resolve(key)
        observation = inventory.get(final, {})
        status = cache.get(key, cache.get(final, {}))
        if key in ambiguous or final in ambiguous:
            reliable = False
        if not reliable:
            classification = 'Unresolved redirect evidence'
        elif (urlsplit(final).hostname or '').lower() != host:
            classification = 'Outside audit hostname'
        elif not valid_graph:
            classification = 'Insufficient navigation evidence'
        elif final == seed:
            classification = 'Navigation seed'
        elif observation.get('Unique referring pages', 0) > 0:
            classification = 'Observed internally linked'
        elif isinstance(status.get('status'), int) and status['status'] >= 400:
            classification = 'Observed unavailable; review separately'
        else:
            classification = 'Potential orphan candidate (limited evidence)'
        page = pages.get(final)
        counted = valid_graph and reliable and (urlsplit(final).hostname or '').lower() == host
        canonical_review = ''
        if page and page.canonical:
            try:
                canonical_key = url_key(page.canonical)
            except ValueError:
                canonical_review = 'Invalid or unsupported canonical hint; verify the declaration.'
            else:
                if canonical_key != final:
                    canonical_review = 'Declared canonical differs from the observed destination; verify intended consolidation.'
        rows.append(dict(URL=key, Raw_URL=entry['Raw_URL'], Sitemaps=' | '.join(entry['Sitemaps']),
                         Final_URL=final, Classification=classification,
                         Unique_referring_pages=observation.get('Unique referring pages', 0) if counted else None,
                         Observed_link_occurrences=observation.get('Observed link occurrences') if counted else None,
                         Inspected=observation.get('Inspected', False), Depth=observation.get('Observed seed-relative depth'),
                         Status=status.get('status'), Canonical_hint=page.canonical if page else '', Canonical_review=canonical_review,
                         Redirect_alias=final != key, Evidence=NOTE))
    return dict(version='phase2-sitemaps-1', rows=rows, candidate_count=sum(r['Classification'].startswith('Potential orphan') for r in rows),
                comparison_available=valid_graph, scope_note=NOTE + ' ' + links['coverage_note'],
                sitemap=sitemap, navigation_coverage=crawl.get('coverage'))
