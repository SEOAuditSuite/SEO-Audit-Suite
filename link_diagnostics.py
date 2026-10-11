"""Sample-scoped link evidence; never an orphan inventory or a ranking model."""
from collections import Counter, defaultdict, deque
from urllib.parse import urlsplit, urlunsplit
import ipaddress


def url_key(url):
    """Only normalize scheme/host and empty root path; preserve resource identity."""
    p = urlsplit(url)
    host = (p.hostname or '').lower()
    if ':' in host:
        host = '[' + host + ']'
    netloc = host + (':' + str(p.port) if p.port is not None else '')
    if p.username is not None or p.password is not None:
        raise ValueError('Credential-bearing URLs are not supported')
    return urlunsplit((p.scheme.lower(), netloc, p.path or '/', p.query, ''))


def validate_fetch_url(url):
    """Narrow syntactic/literal-address guard, NOT DNS rebinding protection."""
    if any(ord(c) < 33 for c in url) or '\\' in url:
        raise ValueError('Invalid URL characters')
    p = urlsplit(url)
    if p.scheme.lower() not in ('http', 'https') or not p.hostname:
        raise ValueError('Only absolute HTTP(S) URLs are supported')
    url_key(url)  # validates credentials, port and IPv6 syntax
    host = p.hostname.lower().rstrip('.')
    if '%' in host or host == 'localhost' or host.endswith(('.localhost', '.local')):
        raise ValueError('Local addresses are not supported')
    try:
        address = ipaddress.ip_address(host)
    except ValueError:
        # Browsers accept legacy integer, octal and hex IPv4 spellings.
        if all(part.isdigit() or part.lower().startswith('0x') for part in host.split('.')):
            raise ValueError('Ambiguous numeric address')
    else:
        if not address.is_global or (address.version == 6 and address.ipv4_mapped and not address.ipv4_mapped.is_global):
            raise ValueError('Non-public IP address')
    return url


def classify_status(status):
    if not isinstance(status, int) or status < 100:
        return 'unknown'
    if 200 <= status < 300:
        return 'working'
    if status in (404, 410):
        return 'broken'
    return 'review'


def status_evidence(page):
    chain = getattr(page, 'redirect_chain', [])
    return dict(url=page.url, status=page.status, final_url=page.final_url,
                requested_status=chain[0]['status'] if chain else page.status,
                redirect_hops=len(chain), redirect_chain=chain,
                classification=classify_status(page.status), error='')


def crawl_status_cache(crawl):
    cache = {url_key(r['url']): r for r in crawl.get('status_checks', [])}
    for page in crawl.get('pages', []):
        cache.setdefault(url_key(page.url), status_evidence(page))
    # A fetched final response can answer a direct status check without refetching.
    for row in list(cache.values()):
        for i, hop in enumerate(row.get('redirect_chain', [])):
            cache.setdefault(url_key(hop['url']), dict(row, url=hop['url'],
                requested_status=hop['status'], redirect_hops=len(row['redirect_chain']) - i,
                redirect_chain=row['redirect_chain'][i:]))
        if row.get('final_url') and isinstance(row.get('status'), int) and row['status'] > 0:
            key = url_key(row['final_url'])
            if key == url_key(row['url']) or row.get('redirect_hops', 0):
                cache.setdefault(key, dict(row, url=row['final_url'], requested_status=row['status'],
                                           redirect_hops=0, redirect_chain=[]))
    return cache


def coverage_note(crawl):
    c = crawl.get('coverage')
    if not c:
        return 'Crawl coverage/depth unavailable in this legacy snapshot; completeness is unknown.'
    return (f"Audit hostname: {c.get('audit_hostname', 'not recorded')}. "
            f"Sample: {c['pages_inspected']} pages inspected; requested limit {c['requested_limit']}; "
            f"{c['attempted_urls']} URL attempts; {len(c['remaining_queue'])} queued; "
            f"{c['skipped_discoveries']} discoveries omitted by limit; "
            f"{len(c.get('out_of_scope_redirects', []))} cross-host destinations excluded. Stop: {c['stop_reason']}. "
            'Queue exhaustion only describes observed navigation, not full-site coverage.')


def analyze_links(crawl, checks=None, include_external=False):
    """Build evidence without network I/O. Only observed HTTP redirects are aliases."""
    pages = crawl.get('pages', [])
    coverage = crawl.get('coverage') or {}
    seed_url = coverage.get('seed_url') or (pages[0].url if pages else '')
    scope_host = coverage.get('audit_hostname')
    if not scope_host:
        seed_page = next((p for p in pages if url_key(p.url) == url_key(seed_url)), None)
        scope_host = (urlsplit(seed_page.final_url if seed_page else seed_url).hostname or '').lower()

    def in_scope(url):
        return bool(scope_host) and (urlsplit(url).hostname or '').lower() == scope_host

    cache = crawl_status_cache(crawl)
    for row in checks or []:
        cache[url_key(row['url'])] = row
    aliases = {}
    for key, row in cache.items():
        if row.get('redirect_hops') and row.get('final_url') and isinstance(row.get('status'), int) and row['status'] >= 100:
            aliases[key] = url_key(row['final_url'])

    def resolve(key):
        seen = set()
        original = key
        while key in aliases:
            if key in seen:
                return original  # conflicting/cyclic evidence: don't invent a destination
            seen.add(key)
            key = aliases[key]
        return key

    edges = []
    occurrences = Counter()
    sources = defaultdict(set)
    unknown_counts = set()
    graph = defaultdict(set)
    inspected = {resolve(url_key(p.final_url)) for p in pages
                 if in_scope(p.final_url) and in_scope(resolve(url_key(p.final_url)))}
    seen_sources = set()
    for page in pages:
        source = resolve(url_key(page.final_url))
        if not in_scope(source):
            continue  # legacy snapshots may include fetched cross-host redirect pages
        if source in seen_sources:
            continue  # repeated fetch of the same final page is not another referring page
        seen_sources.add(source)
        raw = getattr(page, 'link_occurrences', None)
        exact = raw is not None
        items = raw if exact else [dict(x, internal=True) for x in page.internal_links] + [dict(x, internal=False) for x in page.external_links]
        grouped = Counter((x['url'], x['anchor'], x.get('internal', True)) for x in items)
        for (target, anchor, internal), count in grouped.items():
            internal = in_scope(target)
            if not internal and not include_external:
                continue
            key = url_key(target)
            destination = resolve(key)
            row = cache.get(key, {})
            edges.append({'Source': page.final_url, 'Source requested URL': page.url,
                          'Target': target, 'Anchor': anchor, 'Internal': internal,
                          'Destination in audit scope': in_scope(destination),
                          'Redirect leaves audit scope': internal and not in_scope(destination),
                          'Occurrences': count if exact else None,
                          'Requested status': row.get('requested_status'),
                          'Status': row.get('status'), 'Final URL': row.get('final_url', ''),
                          'Redirect hops': row.get('redirect_hops'),
                          'Classification': row.get('classification', 'not checked'),
                          'Error': row.get('error', '')})
            if internal and in_scope(destination):
                occurrences[destination] += count
                if not exact:
                    unknown_counts.add(destination)
                # Self-links are evidence, but not links from another referring page.
                if source != destination:
                    sources[destination].add(source)
                graph[source].add(destination)
    seed = seed_url
    depths = {}
    if seed:
        seed = resolve(url_key(seed))
        depths[seed] = 0
        queue = deque([seed])
        while queue:
            source = queue.popleft()
            for dest in sorted(graph[source]):
                if dest not in depths:
                    depths[dest] = depths[source] + 1
                    queue.append(dest)
    inventory = []
    for dest in sorted(inspected | set(occurrences)):
        inventory.append({'URL': dest,
                          'Observed link occurrences': None if dest in unknown_counts else occurrences[dest],
                          'Unique referring pages': len(sources[dest]),
                          'Inspected': dest in inspected,
                          'Observed seed-relative depth': depths.get(dest)})
    unlinked = [r['URL'] for r in inventory if r['Inspected'] and not r['Unique referring pages'] and r['URL'] != seed]
    return {'definitions': 'Evidence occurrences count eligible anchor elements in one snapshot per in-scope final source URL. Internal describes the original href hostname. Outbound redirects remain evidence but their foreign destinations and pages are excluded from internal graph counts and depth. Unique referring pages exclude self-links. Legacy occurrence counts are unknown. Depth is shortest observed internal-link distance from the seed; HTTP redirects cost zero. Zero observed referring pages is not proof of an orphan.',
            'audit_hostname': scope_host,
            'edges': edges, 'inventory': inventory, 'aliases': aliases,
            'no_observed_inlinks': unlinked, 'coverage_note': coverage_note(crawl)}
