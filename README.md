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

## V6.1.1 Phase A stabilization (development)

Complete Audit and its standalone HTML download now use the V6.1.1 development
label. Crawl-wide image elements/unique URLs are explicitly separate from
first-page non-empty ALT coverage. Counts include repeated/hidden elements;
non-empty ALT is not proof of descriptive quality, and decorative empty ALT may
be appropriate. Image SEO identifies the first page and actual fallback mode.

Phase 3 tables show readable before/after values and link evidence. The original
structured rows remain available in an expander and evidence exports. Optional
client HTML/PDF comparison summaries use the same readable values. Head-only
HTML retains title/metadata but no longer treats it as main textual content.

This is not a release or security-hardening milestone. Startup/autofill changes,
DNS pinning, browser egress isolation and CPU/RAM quotas are outside Phase A.
Existing scoring, network restrictions, serialized version identifiers and all
nine default Client Workspace exports are preserved. The separate Complete
Audit HTML download intentionally changes its presentation and filename.


## Phase A R2 — mobile Complete Audit table containment

The standalone Complete Audit Crawled Pages table is contained in a keyboard-focusable, labeled horizontal scroll region. All eight columns and values remain available. The page is not cropped or globally overflow-hidden. Existing scores, default Client Workspace exports and network restrictions are unchanged.

The original Windows run verified 165 automated tests and 40 of 41 Chrome checks; mobile Complete Audit page overflow was the only failure. R2 adds one focused automated regression (166 total) and three Chrome checks (44 total), including reproduction of the original unwrapped table overflow and verification that the last column remains reachable. Four additional table screenshots bring the total to fourteen. R2 Windows acceptance remains pending until its own run succeeds and screenshots are reviewed.


## Phase C1 — shared connection-bound HTTP transport (development)

`safe_http.py` is used by common HTTP collectors (including crawl fallback,
link checks and sitemaps) and Phase 3's controlled replay transport. Each hop
resolves once, rejects the entire answer set if any destination is unsafe, and
connects to an approved numeric address. HTTPS retains the original IDNA
hostname for certificate checks, SNI and Host. Paths/query strings and existing
redirect evidence remain intact. No proxy, netrc, Authorization, cookie jar or
ambient credentials are inherited. Explicit credential-bearing URLs are blocked.

Limits: at most four outstanding DNS workers, 32 approved addresses per lookup,
60 seconds per common fetch including redirects, and 5 MiB each of encoded and
decoded response bytes. Redirect bodies are not downloaded. Phase 3 retains its
stricter 20-second network, 40-request, 2-MiB resource and 5-MiB session limits;
failed transfers conservatively consume their reserved session byte allocation.
Sitemap fetches also share the inventory's existing elapsed-time deadline.
Unsupported compression, blocked destinations and request failures remain
unknown/unavailable, never synthetic HTTP errors or proof of broken links.

Compatibility boundaries: anonymous HTTP GET only; gzip/identity responses;
normal public DNS destinations only. Private/intranet audits, mixed public/private
DNS, proxy-only networks, cookie-dependent redirects and unsupported encodings
may now yield unavailable evidence. The system/default Python TLS CA store is
used; certificate verification is never disabled. Requirements, scoring formulas,
nine default exports, and existing UI/report presentation are unchanged.

This is **not complete SSRF protection or public deployment readiness**. The
normal Playwright crawler, its subresources, WebSockets and browser-internal
traffic are not connection-bound by this patch. The fixed Google PageSpeed API
client is unchanged. C2 must cover browser egress; C3 must provide OS/network
isolation, process-tree cleanup and CPU/RAM limits. An OS DNS lookup can outlive
its caller's deadline, although only four daemon resolver workers can remain
outstanding. Existing Phase 3 replay CSP and same-origin restrictions remain;
JavaScript-heavy sites may still produce incomplete evidence. No deployment is
authorized by these changes.


## Phase C2A — anonymous browser GET broker (development)

Normal crawler HTTP(S) document/resource requests now use the C1 connection-bound
`SafeSession` via `browser_isolation.GetBroker`. There is no direct
`route.continue_()` or `route.fetch()` fallback. Navigation redirects are resolved
in C1 before Chromium sees the final document at its true URL; requested identity,
observed redirect chain, depth and cross-host graph exclusions remain available.
Redirected subresources are blocked rather than replayed at an incorrect base URL.
Direct public CDN scripts, styles, images and fonts are supported. XHR/fetch are
same-origin anonymous GET only. Cookies, authorization, POST, cross-origin APIs,
streaming/media and authenticated browsing are unsupported and can limit evidence.

The shared context enables TLS verification, blocks service workers/WebSockets,
rejects downloads and additional pages, and adds frame/worker/object/form CSP
restrictions to normal documents. The browser launch explicitly enables Chromium
sandboxing and retains it on both Chrome/Chromium attempts; unsupported sandbox
launch fails, with only the existing C1 HTTP fallback permitted. A temporary
browser profile is used; credentials/proxy environment variables are not passed
to the browser. Phase 3 retains its stricter same-origin replay/CSP limits.

Normal broker budgets: 100 network requests and 20 MiB per page; 500 requests and
100 MiB per crawl; 5 MiB encoded/decoded per resource; 30 seconds of page network
time; 10 navigation redirect hops; 200 representative resource rows. Failed
transfers conservatively reserve their C1 byte allocation. The existing page,
attempt and DOM limits still apply. Response-time evidence includes C1 preparation
and browser extraction. No scoring formula is changed.

`browser_security` evidence records observed HTTP statuses or unknown requests,
redacted query-free URLs, blocked reasons, per-page summaries and truncation.
Partial rendering makes observed-graph completeness false and adds warnings to
Complete Audit and client HTML/PDF/JSON without creating new default exports.
Scores describe the collected snapshot; missing content/links need verification
when restrictions affect rendering. Reports without broker evidence retain their
existing output. Nine default exports remain nine.

This is application-level interception, NOT complete browser network isolation.
The deny-proxy/flags/CSP are defence in depth, not an OS firewall. Browser-internal
requests, alternative protocols, WebRTC/WebTransport bypasses, host-loopback
services and compromised renderers need C3 containment. C2B's normal-crawler outer
worker deadline/process cleanup is not implemented here. CPU/RAM/PID quotas,
filesystem/secret isolation and public deployment remain pending. Phase 3's
existing cleanup edge case is unchanged. A post-extraction DOM size check cannot
prevent allocations or hostile JavaScript before capture. Local HTTP fallback
must never be reported as browser validation.


### C2A R2 — popup dispatch and Windows diagnostics

Normal-crawler popup requests are rejected independently by GetBroker. Popup
closure is queued and drained from normal capture control flow, avoiding a
synchronous close waiting inside the page event dispatcher. Phase 3's existing
strict routing and lifecycle are unchanged. C2B process containment is not added.
The Windows harness now emits flushed stage/route progress, incremental progress
JSON and periodic Python thread stacks. Its existing 240-second C2A timeout is
unchanged. The exact cause of the two earlier Windows timeouts remains unverified
without stack evidence; successful R2 Windows verification is still required.


### C2A R3 — confirmed synchronous WebSocket callback wait

Windows thread stacks identified `WebSocketRoute.close()` waiting inside the
asyncio-dispatched WebSocket handler. Unlike ordinary control flow, that callback
cannot synchronously wait for the same loop. The handler now records/queues the
blocked socket and never calls `connect_to_server()`. Closure is drained from
normal synchronous capture control flow. Phase 3 uses the same mechanism instead
of its duplicate inline close callback; stricter same-origin/CSP rules remain.
R2 popup deferral and logging remain. The Windows stage timeout is still 240 s.
Real Windows R3 acceptance remains pending; C2B/C3 are not implemented here.


## Phase C2B — supervised browser lifecycle (development)

Baseline: `9439ff93d89854f6b207ad68057ae75e51fbedd2`. C1, C2A R3 and the
discovery-status correction are merged. Earlier pending C2A statements above
record their pre-acceptance development state; accepted R3 had 230 automated
tests, 75 Chrome checks and 18 reviewed screenshots. C2B acceptance is separate.

Normal `crawl_site(..., prefer_browser=True)` now runs the existing brokered
crawler in a dedicated Python worker. Default wall budget is
`min(600, max(60, 15 + limit * (timeout / 1000 + 15)))` seconds; explicit
`wall_seconds` accepts 1–600 seconds. Navigation timeout accepts 1–120000 ms.
Startup, C1 HTTP fallback inside that worker, rendering and graceful shutdown
share this deadline. A parent timeout/crash never starts a retry or unrestricted
browser. Explicit HTTP-only crawling still uses the existing C1 path.

Windows assigns a kill-on-close Job Object before releasing the worker's stdin
gate. Failed assignment stops before Chrome can start. POSIX uses a dedicated
session/process group; Linux also tracks owned descendants and detached Chrome
groups by host PID/start-time identity. Cleanup runs after success, crash, timeout and propagated
interruption, including stray descendants. Browser contexts close explicitly
before browsers. Cleanup has separate bounded waits (up to approximately 12
additional seconds); incomplete confirmation is an operator warning, not success.
Phase 3 uses the same supervisor and catches the second pipe-drain timeout.

Atomic, local crawl checkpoints retain completed pages, link/redirect evidence,
queue, depths and coverage. Checkpoint/result acceptance is capped at 64 MiB
(this is a serialization limit, not a process RAM quota). Interrupted in-flight
requests have unknown status; no missing headings or broken-link verdicts are
invented. Lifecycle evidence appears only on abnormal runs in existing JSON
and report scope notes; successful output fields, scoring formulas and the nine
default export filenames remain unchanged.

C3 remains required: network egress/host/secret isolation, CPU/RAM/PID quotas,
container/OS watchdogs and protection against compromised processes escaping
POSIX groups or disabling the parent. Application interception and lifecycle
control do not establish public deployment readiness. Non-Linux POSIX hosts cannot certify detached-tree
cleanup and report it as unconfirmed rather than success. Windows Job behavior and
real Chrome lifecycle checks require the separate C2B validation package.


### C2B R2 — verified Windows fixture deadline ordering

Windows run `20261014-153924-677c6efb` matched the original 14-file patch and
all source checksums: 256 automated, 44 existing Chrome, 5 C1 and 26 C2A checks
passed; C2B passed 21/23. The two failed checks were the infinite-JavaScript hard
deadline and its tree-cleanup assertion. Actual evidence was a navigation
TimeoutError, `queue_exhausted_with_errors`, unknown HTTP status and no abnormal
`browser_supervision` record. This was not a demonstrated tree-cleanup failure.
Crash and browser-close deadline cases confirmed cleanup on the same Windows run.

Confirmed fixture error: every navigation used 5000 ms but the infinite-script
worker wall deadline was 10 seconds. The inner timeout won and the crawler
closed normally before the hard-deadline case could execute. R2 keeps the outer
10-second deadline and cleanup waits unchanged. Only that controlled fixture
uses the existing production-default 30000 ms navigation budget, deliberately
longer than the outer deadline. Normal fixture navigation remains 5000 ms.
Production navigation defaults/limits, deadlines, Job assignment, termination,
C1/C2A policies, scoring and exports are unchanged. No implementation failure
in termination has been established by the supplied evidence.

R2 adds diagnostic evidence, not relaxed protection: actual worker/driver IDs,
script-start marker, requested navigation budget, elapsed wall/cleanup time,
and exact owned Windows Job membership before termination and after cleanup.
The existing two checks now require actual script execution, correctly timed
hard deadline and owned worker/driver membership followed by zero active Job
processes. Membership-query failures/truncation cannot count as complete proof.
No URLs, command lines, credentials or inherited environment are added to logs.
Diagnostics remain outside normal application outputs; report/export fields
and filenames remain compatible.

Thirteen focused R2 regressions cover navigation-vs-wall timeout distinction,
missing/early/late evidence, incomplete or surviving Job members, bounded Job
queries and serializable supervisor diagnostics. Full corrected target: 269
automated tests and the same 98 Chrome checks/22 screenshots. R2 Chrome/Windows
acceptance remains pending; prior-version passes do not certify the R2 package.


## Phase C3A — local launch and worker environment policy (development)

Baseline: `faa7a38337f1217953298794baf0137da2cfe5af`. This phase adds only local
Streamlit binding and explicit browser-worker environment filtering. C1, C2A
and C2B security behavior, deadlines, scoring and default exports are preserved.

### Safe local Windows use

- Use Python 3.12 in the project's virtual environment and installed Google Chrome.
  Run **START-APP.bat**; both its virtual-environment and fallback-Python branches
  explicitly bind to **127.0.0.1**. Open `http://127.0.0.1:8501` locally. The
  launcher does not disable Streamlit CORS or XSRF protection or alter their config.
- A manual launch must include the same binding:
  `python -m streamlit run app.py --server.address=127.0.0.1`. A separate manual
  command, environment override or configuration remains the operator's responsibility.
- Prefer a dedicated non-admin audit account and clean working directories. Audit
  only authorized public websites, keep Chrome/Windows updated, and do not expose
  the app through router forwarding, public tunnels or shared LAN hosting.
- PageSpeed credentials can still be entered in the existing password field or
  supplied as `PAGESPEED_API_KEY` to the parent application. The launcher does not
  clear the parent environment; browser workers never receive that variable.
- Install requirements into the selected virtual environment. Workers use the
  caller's explicit Python executable; inherited `PYTHONPATH`, `PYTHONHOME`, user
  site-packages and Python/Node startup hooks are not supported bootstrap methods.

Both normal crawls and Phase 3 workers receive only explicit OS bootstrap/profile,
temporary/cache, locale/display and Chrome installation paths plus optional
`PLAYWRIGHT_BROWSERS_PATH` / `PLAYWRIGHT_NODEJS_PATH` runtime paths. Fixed UTF-8,
no-user-site and no-bytecode Python settings replace inherited Python settings.
Proxy variables, PageSpeed/API credentials, tokens, passwords and unrelated
parent variables are excluded; the parent's values are not mutated or logged.
Existing browser environment filtering remains unchanged. Bootstrap path values
are trusted local configuration, not a place to store secrets.

**Limits:** this is environment hygiene and loopback binding, not OS network or
filesystem isolation. Profile paths remain available for compatibility; the worker
still runs under the same OS account and permissions. C3B CPU/RAM/PID quotas and
whole-operation resource controls, and C3C firewall/container/public infrastructure,
are not implemented. Public deployment remains on hold. Native Windows launch
and Chrome acceptance must be recorded separately; local automated tests do not
certify Windows Firewall, ACL or container isolation.
