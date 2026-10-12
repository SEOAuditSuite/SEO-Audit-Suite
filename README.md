# SEO Audit Suite V6.1

## Phase 3: optional raw HTML / rendered DOM comparison

Use **Meta & Canonical > Optional raw HTML / rendered DOM comparison** for a single URL,
or enable the first-page comparison in **Client Workspace**. It is off by default and
does not feed the existing crawl graph, sitemap candidates, issue scoring or audit scores.

The diagnostic compares title and description elements, resolved canonical URLs, H1/H2
headings, generic/Googlebot/Bingbot meta directives and the shared HTTP X-Robots-Tag,
main textual content, and internal anchor occurrences (target, text and rel). Added,
removed, changed and unchanged-in-snapshot values are explicit. Reordered headings
are changed; removed/added lists do not invent one-to-one element identities.

A fresh server response is fetched once and replayed in an isolated Chrome/Chromium
context. Raw and rendered evidence therefore share the initial response; they are
separate from the earlier navigation crawl's timestamp and cookie state. HTML base
URLs are respected. Fragments are excluded from link identity; path case, trailing
slashes and queries remain distinct. Canonicals remain hints, never merge rules.

### Resource policy and limits

- One requested page; only same-origin HTTP(S) GET resources. Every HTTP redirect hop
  is validated. Cross-origin document redirects are rejected, rather than silently
  changing the audited site. Redirected subresources are not replayed at a false base URL.
- Up to 40 HTTP requests and 40 browser route attempts, 5 redirect hops per request,
  2 MiB per decoded resource/DOM and 5 MiB aggregate admitted HTTP bytes. A rejecting
  chunk can exceed the byte counter by at most one 16 KiB streaming chunk; it is not retained.
- Five-second HTTP request timeout, 20-second network budget, 15-second navigation
  timeout and 1.5-second settling window. A separate worker has a 45-second deadline;
  process-tree cleanup may take up to ten further seconds.
- Browser requests are fulfilled by the bounded HTTP transport or aborted; no route
  continues directly. Service workers, frames, popups via sandbox policy, workers,
  WebSockets, WebRTC APIs, media and non-GET requests are restricted. An additional
  context proxy sink and CSP restrict network fall-through. Browser cache/profile is fresh.
- DNS preflight rejects non-public resolved addresses, and TLS verification remains
  enabled. The HTTP transport ignores inherited proxies/netrc and does not forward
  browser cookies, credentials or authorization headers.
- Up to 200 entries per element type and 2,000 characters per value. Oversized fields
  are explicitly not assessed, never silently called unchanged. Main text is compared
  using its full normalized hash and character count, with a bounded excerpt.

The main-content heuristic selects the first main/role=main/article/body, excludes
navigation/script/explicitly hidden descendants and normalizes whitespace. It does
not inspect computed CSS visibility, shadow DOM or semantic content quality. The
HTTP X-Robots-Tag belongs to the shared response; JavaScript cannot change that header.

Client packs add `rendering-comparison.csv`, bounded raw/rendered snapshots and
resource warnings in `evidence.json`, and optional PDF/HTML summaries. Failures remain
**Not assessed**; they never become removed content or a successful unchanged result.
When disabled, the original nine default exports remain unchanged. Phase 2 exports
and scoring also remain unchanged when enabled alongside this diagnostic.

### Interpretation and security limitations

This is a constrained desktop observation, not Googlebot simulation or an indexing
decision. Blocking CDNs, authentication, cross-origin APIs, workers, redirected scripts
or late interactions can prevent hydration. Script errors, blocked resources, pending
requests and extraction limits must be reviewed before attributing missing elements to
the website. Browser HTML parsing alone can also cause differences.

DNS checks are not DNS pinning: rebinding/races remain unresolved. Browser restrictions
are not an OS network sandbox or comprehensive browser hardening. There are no process
CPU/RAM quotas; cancellation relies on OS process-tree termination. Existing Phase 1/2
fetch paths are not retroactively hardened. Public multi-user deployment is not approved.
URLs, query strings and page content in evidence may contain sensitive data; review exports.

Google documents that rendering can reveal content/links and that an initial noindex
can cause rendering to be skipped. Removing noindex in JavaScript does not establish
indexability. See [Google's JavaScript SEO basics](https://developers.google.com/search/docs/crawling-indexing/javascript/javascript-seo-basics).

For controlled real-Chrome validation, run:

```powershell
py -3.12 tests/browser_rendering_validation.py --output phase3-browser-results
```

Install the requirements in an isolated Python 3.12 environment first. The browser
validation runner uses installed Google Chrome and in-memory fixtures, saves actual
results plus normal desktop/mobile screenshots, and fails clearly if Chrome cannot run.
It is intentionally separate from the automated unittest suite. See VALIDATION.md for
what has actually executed; a prepared script is not a passed browser test.

A local Python/Streamlit toolkit for sampled SEO audits and client delivery.

Start with [START-HERE.md](START-HERE.md) for installation and the Roman Urdu workflow.
Read [UPWORK-SERVICE-KIT.md](UPWORK-SERVICE-KIT.md) for service copy, package scopes,
client intake and proposal/delivery messages.

## Main workflow

Open **Client Workspace**, collect a bounded sample, and download the client pack.
Use the project skill `seo-client-delivery` with the evidence in Codex to prepare
client-specific keyword mapping, content briefs and a practical implementation plan.
The skill is in `.agents/skills/seo-client-delivery/`.

## Included capabilities

- Browser rendering with HTTP fallback; metadata, headings, images, links and JSON-LD.
- Origin-based robots/sitemap discovery and URL-specific robots rule inspection.
- Heuristic AEO/GEO/entity, authority/reputation and competitor comparisons.
- GSC CSV analysis and a separate PageSpeed module.
- PDF/HTML reports, page-level issue logs, inventories, keyword CSV and JSON evidence.
- Persistent client-pack downloads and an assistant handoff from the same saved run.

## Scope

Read the report scope. Scores are internal prioritization aids. The app does not
measure live rankings, proprietary backlink metrics, conversions or AI citations.
First-page AI checks are not a full-site measurement. Keyword mapping imports supplied
research; strategy still requires manual review. Public multi-user hosting is outside
this local release's validation scope.

The synthetic report in `demo-client-pack/` demonstrates format only. It is not a
real client result. See [VALIDATION.md](VALIDATION.md) for checks and limitations.

## Run

```powershell
python -m pip install -r requirements.txt
python -m playwright install chromium
python -m streamlit run app.py
```

## Verify

```powershell
python -m unittest discover -s tests -v
```

Built from the supplied V6 source. V5 history and the original Beyond SEO archive
are not included. The newly written project skill uses this toolkit's actual evidence.

## Phase 2: Sitemap-Based Candidate Review

In **Sitemap & Robots Health**, provide the site URL and optionally an explicit XML
sitemap URL. The tool combines supplied robots.txt `Sitemap:` directives with the
explicit URL and `/sitemap.xml`, processes sitemap indexes recursively, and keeps
page inventory separate from sitemap document inventory. Image/video extension
URLs are not treated as page URLs. Existing optional page-status checks remain
separate from navigation evidence.

Enable **Compare with navigation crawl** to compare sitemap-listed URLs with
Phase 1 internal-link evidence. In **Client Workspace**, enable **Include bounded
sitemap candidate review** to add the same analysis to a saved client pack.
The feature is disabled by default in Client Workspace. It adds no score component
and does not change existing exports when disabled.

Findings are **potential orphan candidates with limited evidence**. A URL with no
observed referring pages may still be linked outside the crawl sample, unavailable,
intentionally excluded, or listed in a stale sitemap. Unknown status stays unknown.
A failed or empty sitemap inventory, failed crawl, or legacy snapshot without coverage
is reported as not assessed rather than an established zero-candidate result.
Sitemap URLs never seed the navigation crawl. Queue exhaustion does not prove
full-site coverage. Canonical hints are exposed for review and do not merge URLs.
Only successful, consistent observed HTTP redirect evidence resolves aliases;
failed/conflicting/cyclic mappings remain unresolved. Exact hostname scope is
preserved, including distinctions between `www` and non-`www` hosts unless an
observed seed redirect establishes the final hostname.

Collection defaults: 20 XML documents, 2,000 unique page URLs, index depth 3
(root depth 0), 5 MiB decoded XML per document, 10 MiB cumulative admitted decoded
XML (including malformed documents), 10-second request timeout and a best-effort
60-second collection deadline. Root and child queues are bounded. Lower limits can
be supplied programmatically; limits cannot exceed defaults. A gzip overflow check
may read one sentinel byte beyond the admission budget. Oversized bodies are never
submitted to the XML parser. The shared fetcher also caps response bodies at 5 MiB.
Existing origin discovery runs before the collector and has its own bounded requests;
the 60-second budget is not a hard deadline for the entire client workflow.

The parser rejects DTD/entity declarations, malformed XML, excessive XML depth,
unsupported roots/namespaces, nested/duplicate `loc` entries, oversized URLs,
relative URLs, credential-bearing URLs and private literal addresses. Uncached
sitemap redirects are checked before every request and must remain on the audit
hostname. Recorded cached redirect hops are checked too; older caches without
intermediate history explicitly retain that limitation. Sitemap fetches do not
resolve DNS defensively: DNS rebinding/private-address resolution protection and
comprehensive browser network isolation remain separate security work. Public
multi-user hosting is not approved or validated.

Optional client exports include `sitemap-candidate-evidence.csv`,
`sitemap-documents.csv` and `sitemap-exclusions.csv`, plus versioned JSON evidence.
PDF/HTML reports show up to ten representative URLs and coverage warnings. PDF URL
examples longer than 300 characters are shortened for readability; CSV retains full
accepted URLs. Existing source-to-target internal-link exports remain available.
URLs, queries and page content can contain sensitive information: review evidence
before sharing. Rejected credential-bearing sitemap URLs are redacted. Cross-host
sitemap documents are excluded, so legitimate CDN-hosted sitemaps need separate
review. Google Search Console inventory reconciliation is a future enhancement;
the existing GSC screen is unchanged.
