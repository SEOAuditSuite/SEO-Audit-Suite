# Validation - V6.1 client delivery edition

## Phase 3 development validation - 12 October 2026

Baseline: `06545fe364c44f202d6ddd209016ba89a114bf8f` (verified GitHub main at checkout).
Development is isolated and uncommitted. Existing published Phase 1/2 history is preserved.

- **153 automated tests passed, zero failures/errors/skips** on Python 3.12.14: 104
  existing tests and 49 new Phase 3 tests. New coverage includes metadata/headings,
  duplicate link occurrences, ordering, base URLs and resource identity, robot directives,
  text hashing beyond display excerpts, extraction/HTTP byte/request/deadline limits,
  redirect scope, public-DNS preflight, fail-closed browser routes, process cancellation,
  missing browser/raw evidence retention, pending/script-error warnings, UI state,
  reporting and disabled compatibility. Mocked browser API tests are not real Chrome tests.
- Controlled loopback HTTP tests verified redirect evidence and that cross-origin
  targets were not requested. Only test fixtures bypass DNS preflight; production guards
  remain enabled. No external client website was audited.
- Baseline comparison confirmed byte-identical nine default exports when Phase 3 is
  disabled; all twelve exports also match with Phase 2 enabled. PDF metadata was made
  deterministic with ReportLab invariant mode for this comparison only.
- Score/crawl extraction function ASTs match the baseline. `link_diagnostics.py`,
  `sitemap_diagnostics.py`, `v6_strategy.py` and `requirements.txt` are unchanged.
- Synthetic successful-comparison and unavailable-result HTML/PDF/CSV/JSON reports
  generated. HTML structure/escaping and explicit failure labels were checked. The
  successful sample PDF has six pages; new comparison content was inspected visually.
  Poppler exhibited a local font-substitution spacing artifact; a secondary MuPDF render
  of the unchanged PDF confirmed readable text and intact layout.

### Browser blocker and remaining acceptance gate

No installed Chrome/Chromium executable was found. The bundled Playwright Node executable
could not execute in this environment; using the supported `PLAYWRIGHT_NODEJS_PATH`
override allowed the installer to start, but Chromium downloads failed with an invalid
or truncated ZIP. A direct installed-Chrome validation attempt reported **blocked,
zero executed checks and zero passed checks**. This is not browser acceptance.

`tests/browser_rendering_validation.py` prepares real-Chrome checks for all eight
comparison fields, paired response provenance, asynchronous same-origin rendering,
restricted requests, client navigation, script failures, DOM size rejection, a hanging
renderer deadline and desktop/mobile report overflow. It saves six normal viewport
screenshots. These checks and screenshots still require execution/review on Windows.
The accompanying Windows package uses an isolated copy, Python 3.12 explicitly and
verified source checksums; it does not touch an existing local project.

### Remaining limitations

This optional replay restricts resources and can differ from a normal authenticated
visit. Same-origin restriction includes scheme and port, not only hostname. Redirected
subresources, cross-origin CDNs/APIs, interactions, scrolling and shadow DOM are outside
this scope. Observed removals under a restricted/failed render are not proof of website
defects. Shared-response headers and selected meta directives do not establish actual
indexability or replace robots.txt/GSC checks.

DNS rebinding, a full browser/OS network sandbox, process-wide memory/CPU quotas and
public hosting security remain unresolved. A rejecting response chunk can exceed the
admitted-byte budget before rejection; the body is not retained. Sensitive URL query
values and content remain possible in evidence exports. No scoring change, new runtime
dependency, commit, push, PR, release or deployment is part of this development task.

**Acceptance status: implementation and local regression/report checks complete;
real Windows Chrome execution and visual screenshot review pending.**

Date: 7 October 2026. Source: the V6 files in the supplied SEO-Audit-Suite.zip.

## Passed

- 24 automated tests: robots fallback/precedence/exceptions/encoding, JSON-LD preservation,
  malformed JSON-LD, multiple meta robots tags, origin-based discovery, unknown robots handling,
  training-vs-search scoring, rendering-mode neutrality, source requirements, unknown keyword
  metrics, spreadsheet formula protection, HTML escaping, exports and Streamlit UI state.
- Changed app screens initialize in Streamlit AppTest. The Client Workspace form generates a pack
  using a controlled fixture; downloads retain the same snapshot across reruns.
- Python compilation across the delivered source.
- Real HTTP crawl of a controlled local two-page site: two pages fetched, body JSON-LD preserved,
  inner-page input fetches robots.txt from the origin.
- PDF and HTML report generation, evidence JSON and CSV exports.
- Sample PDF rendered with Poppler and visually reviewed after layout changes.
- Skill frontmatter/name, local reference paths and unfinished-placeholder checks.

## Not verified / environment limitations

- A browser-rendered integration run was attempted but Windows sandbox pipe access prevented
  Playwright from launching. JavaScript-rendered crawling must be checked on the normal local
  machine before selling audits that depend on it. HTTP fallback was tested successfully.
- Streamlit tests passed, but Python emitted a Windows permission warning while cleaning up a
  temporary directory after completion. It did not fail an assertion or alter the exported files.
- The standard skill-creator validator was attempted but requires PyYAML, which is absent here.
  The simpler frontmatter/reference checks above passed; no independent agent behavior test ran.
- Live client websites, paid APIs, Google PageSpeed service availability, and external ranking,
  backlink, GBP or AI-citation data were not tested in this session.
- This is a local consultant tool. Public multi-user hosting and a full security/performance audit
  are not included in this release.

## Changes that affect score comparison

Scores may differ from V6 because body JSON-LD is now retained, malformed blocks no longer count
as parsed coverage, training controls no longer reduce search access scores, and missing robots
evidence is excluded with a coverage note. Preserve the version and evidence snapshot when comparing
two audits. Do not attribute score changes caused by an engine upgrade to client SEO improvements.

## References checked

- [Google robots.txt interpretation](https://developers.google.com/crawling/docs/robots-txt/robots-txt-spec)
- [Google AI features and websites](https://developers.google.com/search/docs/appearance/ai-features)
- [OpenAI skills documentation](https://learn.chatgpt.com/docs/build-skills)

The robots parser is a URL-specific rule simulation, not a complete implementation of every vendor's
fetch, cache, redirect or availability behavior. It does not predict actual crawling or indexing.

## Sidebar follow-up

Added explicit grouped navigation for Overview and all 24 tools, an expanded initial sidebar,
and START-APP.bat. All registered pages were opened by the navigation regression test.
Browser UI verification confirmed the menu on Overview and after selecting Client Workspace.
Streamlit minimum is now 1.46 to support additive page configuration in the routed app.

## Phase 2 development validation - 11 October 2026

Baseline: `d33d9cb08b8778e973e93b307d2f509ab8ec4b0f`, confirmed against GitHub
`main`. Work resumed in the recovered isolated `phase2-development` checkout.
The older uploaded V6.1 ZIP was not used as the development baseline.

- Full automated suite: **104 tests passed; 0 failures; 0 errors; 0 skips** on
  Python 3.12.14. This includes 59 existing tests and 45 distinct Phase 2 tests.
  Command: `python -m unittest discover -s tests -v`.
- Parser/discovery tests cover namespace typing, index recursion/cycles,
  duplicate provenance, gzip/UTF-16 bytes, DTD/entity rejection, malformed/deep XML,
  URL validation, document/depth/page/root/child-queue/time limits, aggregate byte
  admission, malformed-document budget consumption and cached redirect history.
- Reconciliation tests cover occurrences vs unique referring pages, self-links,
  redirect aliases/conflicts/cycles/failures, seed depth, www/cross-host boundaries,
  incomplete/legacy/empty evidence, unavailable URLs and canonical review hints.
- Controlled real HTTP tests confirm sitemap URLs do not seed navigation and
  foreign document redirect destinations are stopped before being requested.
- Streamlit AppTest covers both changed screens and Client Workspace opt-in exports.
  Existing navigation and Phase 1 screen tests also pass. Deprecation warnings about
  `use_container_width` remain non-failing existing UI compatibility warnings.
- Compilation passed. Scoring functions, Phase 1 traversal/extraction/graph logic,
  strategy and `requirements.txt` are unchanged.
- Disabled-feature comparison against pinned baseline source confirmed identical
  audit/model data and all nine default export byte streams. PDF metadata was
  stabilized with ReportLab invariant mode only in the comparison harness.
- Synthetic PDF/HTML/JSON/CSV files were generated from the final implementation.
  The seven-page PDF was rendered using Poppler and visually inspected; HTML
  escaping, candidate labels, unknown values and ten-example cap are tested.

### Browser validation remains pending

No local Chromium/Chrome executable was found. Playwright Chromium installation
failed because the downloaded archive was truncated/invalid. Available cloud Chrome
could not reach the isolated loopback HTTP server (`ERR_CONNECTION_REFUSED`), and
its security policy rejected the synchronized report's `file:` URL. No workaround
or policy bypass was attempted. Real Chrome viewport rendering, screenshot review
and horizontal-overflow measurements were **not executed successfully**. Streamlit
AppTest and HTML source assertions do not replace those checks.

The review package includes an English browser verification script for a machine
with installed Chrome. Final visual acceptance requires its actual results and
review of desktop/mobile screenshots. Phase 1's earlier Windows/Chrome results do
not constitute Phase 2 browser validation.

### Remaining limitations

Candidates are limited sample evidence, not proven orphans or indexing results.
Sitemap and navigation coverage remain distinct; partial inventories can omit
candidates. Cross-host/CDN sitemap documents are excluded. Legacy caches without
raw bytes/history cannot prove original encoding or intermediate redirect scope.
Elapsed deadlines are best effort and do not constrain the entire audit workflow.
XML admission limits are not a process-wide memory/CPU quota. DNS rebinding,
resolved-private-address exposure, proxy routing, comprehensive browser network
isolation and public-hosting hardening are not fixed by this phase. Evidence URLs
and content can contain sensitive data. No live client site, paid API, GSC URL
reconciliation or production deployment was tested.

## Phase 3 Windows timeout correction (revision 2)

The supplied Windows log ran 153 tests in 23.633 seconds: 152 passed and one
Streamlit AppTest action exceeded its default 3-second timeout. The traceback
points to the button rerun in
`PhaseOneUITests.test_broken_link_screen_action_reuses_crawl`, not an assertion.
Only that AppTest now uses `default_timeout=20`, consistent with existing UI tests.
All mocks and assertions remain unchanged; application code was not changed for
this correction. The exact slow Windows component was not profiled.

After the correction, the affected test passed independently (1/1), and the full
local Python 3.12 suite passed (153/153; zero failures, errors or skips). This
supports a test timing issue; a corrected Windows run is still required to
confirm resolution on that machine. Chrome checks and screenshot acceptance
remain pending. The launcher still stops on any regression failure.

## V6.1.1 Phase A local validation — 12 October 2026

Baseline: `835227b06c781304b2b2955657c07fc5444e72a2`. Work is isolated and
uncommitted. This section supersedes no historical run; earlier Phase 3 Windows
153/153 automated and 28/28 Chrome results apply to the earlier R2 patch only.

- Current automated suite: **165 passed, 0 failures, 0 errors, 0 skips**
  (153 existing plus 12 focused Phase A regressions).
- Nine default export streams and all twelve Phase-2-enabled/Phase-3-disabled
  export streams are byte-identical to this baseline in the controlled harness.
  Timestamp/PDF metadata are fixed only in that harness. Scoring/crawl function
  ASTs, Phase 1/2 core modules, dependencies and Phase 3 network policy match.
- Controlled HTML/PDF samples generated. The updated five-page client PDF's
  comparison page was visually inspected: readable links/text, no observed
  clipping or overlapping values. AppTest verified both comparison screens.
- Installed Chrome launch attempted locally: **blocked, 0 checks executed**,
  executable `/opt/google/chrome/chrome` absent. No Windows verification is
  claimed. Windows launcher/PowerShell execution is pending.
- The Windows package retains the original 28 Chrome checks and adds 13 Phase A
  checks (41 expected), generating ten desktop/mobile viewport screenshots.
  All results and visual acceptance must be obtained from an actual new run.

Known limitations remain: same-origin constrained replay can produce thin DOM
snapshots; DNS rebinding and OS-level browser egress isolation are unresolved;
there are no process-tree CPU/RAM quotas. No public deployment is approved.


## Phase A R2 — mobile Complete Audit table containment

The standalone Complete Audit Crawled Pages table is contained in a keyboard-focusable, labeled horizontal scroll region. All eight columns and values remain available. The page is not cropped or globally overflow-hidden. Existing scores, default Client Workspace exports and network restrictions are unchanged.

The original Windows run verified 165 automated tests and 40 of 41 Chrome checks; mobile Complete Audit page overflow was the only failure. R2 adds one focused automated regression (166 total) and three Chrome checks (44 total), including reproduction of the original unwrapped table overflow and verification that the last column remains reachable. Four additional table screenshots bring the total to fourteen. R2 Windows acceptance remains pending until its own run succeeds and screenshots are reviewed.


## Phase C1 — local validation (2026-10-13)

Baseline: `9a4516440bd8c9ddddf0b0394b243bc097e56fa5`, detached isolated
`phase-c1-development` workspace. No commit, push or deployment performed.

- Full suite: **190 passed, 0 failures, 0 errors, 0 skips** under Python 3.12.
  This comprises 166 baseline tests and 24 C1 security tests. Controlled tests
  cover numeric-IP connection binding, mixed/private IPv4/IPv6 answers,
  ambiguous/IDNA encodings, redirects, TLS SNI/hostname/untrusted certificates,
  credential/proxy inheritance, gzip/decoded/wire/session byte limits, partial
  responses, DNS/slow-header/slow-body deadlines and blocked-as-unknown evidence.
- Real HTTP/TLS fixture tests run locally. Loopback access is allowed only by
  scoped test mocks; there is no production bypass or insecure TLS option.
- Compatibility harness: all nine default exports and twelve Phase-2-enabled
  exports byte-identical to the baseline, with timestamp/PDF metadata fixed
  only inside the harness. Scoring and crawler ASTs unchanged; requirements,
  Phase 1 identity/graph module, Phase 3 replay policy and comparison unchanged.
- Real Chrome bridge attempted: **blocked, zero checks executed**. Installed
  Chrome is absent in this environment. No Windows or browser acceptance is
  claimed. Windows Python 3.12 package must run the 190-test suite, 44 existing
  Chrome checks plus 5 C1 bridge checks, then review fourteen screenshots.
- The package contains exact source/patch hashes and separate local test logs;
  unexecuted or failed checks cannot become passed results.

C1 limits apply only to shared HTTP collectors and Phase 3's HTTP replay bridge.
Normal browser traffic and the fixed Google PageSpeed client are unchanged.
DNS workers may outlive deadlines (bounded to four); OS scheduling is not a
hard real-time guarantee. Failed replay requests reserve their full per-request
byte allowance conservatively; reported decoded bytes remain successfully
collected evidence, not network accounting. System TLS CA trust, anonymous GET,
gzip/identity-only and no cookie/proxy inheritance can reduce site compatibility.
C2 browser egress and C3 process/network/resource containment remain necessary
before any client-facing public deployment. Earlier historical Windows results
in this document do not constitute C1 verification.


## Phase C2A — local application-broker validation (2026-10-13)

Baseline: `3f30b18ae7b3bccc3cfcf6e7908cc54018fca8a1`; detached isolated workspace.
No commits, review branches, GitHub changes or deployment performed.

- Complete Python 3.12 regression: **224 passed**, zero failures/errors/skips,
  12.767 seconds. Includes all 194 baseline tests plus 30 C2A tests.
- Focused C2A run: **30 passed**, 4.257 seconds. Covers secure launch/context,
  TLS verification, credential environment filtering, WebSockets/popups/downloads,
  C1-backed public CDN resources, same-origin APIs, frames/workers/non-GET blocks,
  redirect preparation without native Location replay, mixed/private DNS,
  IDNA/default-port wire identity, unknown statuses, bounded evidence and budgets,
  HTTP fallback, partial-graph coverage and Complete Audit/report warnings.
- Controlled real HTTP collectors ran in the suite; existing C1 real TLS tests ran.
  Production transport has no test/private-network bypass.
- Default nine exports and twelve Phase-2-enabled exports remain byte-identical
  for controlled snapshots without browser_security data (fixed timestamp/PDF
  metadata in harness only). Scoring AST, C1 SafeSession, link analysis/identity,
  dependencies, Phase 3 ReplayRoutes/CSP/limits and compare_url lifecycle unchanged.
  New broker evidence intentionally adds JSON fields/scope warnings to affected
  browser runs; export filenames/count stay unchanged.
- Representative partial-render HTML, PDF and JSON generated. The PDF first page
  with the added scope warning was rendered and visually inspected: readable,
  no observed clipping/overlap. HTML content verified; Chrome viewport verification
  has NOT run locally.
- Secure Chrome/Chromium launch attempted: **blocked, zero browser checks**.
  Neither installed Chrome nor Playwright's configured Chromium executable exists
  at the inspected paths. No browser installation or Windows verification claimed.
- Windows package must pass 224 automated tests, 44 existing Chrome checks,
  5 C1 bridge checks and 26 C2A checks (75 total), followed by visual review of
  18 screenshots. Historical Windows runs do not accept this patch.

Navigation redirects are resolved manually through C1 before final-URL capture;
redirected subresources are blocked. This avoids relying on native redirected
requests being intercepted at every hop. POST/cross-origin APIs/cookies/workers,
frames, authenticated and streaming sites may yield partial evidence. Public CDN
assets remain supported when they return a bounded, direct anonymous GET response.
Response timing includes prefetch and extraction; scoring formulas are unchanged.

C2A does not add normal-crawler process isolation/deadlines or fix Phase 3 cleanup
(C2B). Sandbox/CSP/routes/deny-proxy are not a firewall or complete SSRF guarantee.
C3 must constrain browser/network/host access, CPU/RAM/PIDs and filesystem/secrets.
The loopback deny-proxy configuration assumes no usable service there; it cannot
establish host-network isolation. Rendering already allocates memory before the
existing DOM-size check. Public deployment remains on hold.


### C2A R2 local regression (2026-10-13 UTC)

228 automated tests passed (0 failures/errors/skips; Python 3.12; 18.539 s).
Four new regressions cover deferred popup closure while requests stay blocked,
already-closed popups, failed-launch progress with zero passes, and a genuinely
stalled subprocess retaining flushed progress before an outer timeout. The last
case uses a synthetic launch stall, not Chrome, and never marks it as passed
browser validation. C2A Windows stage timeout stays 240 seconds. No Windows or
real Chrome success is claimed. The popup callback wait risk is addressed; its
causal connection to the two reported Windows waits is not verified without
thread stacks. Scoring, nine default exports, C1 and Phase 3 restrictions remain.


### C2A R3 — Windows stack-supported correction

Supplied R2 run `20261014-122346-6019a762` repeatedly showed the browser/main thread
in Playwright's sync `_sync`/`wait_for_future`, called by `WebSocketRoute.close`
from `browser_isolation.py:56` inside `_on_web_socket_route`. The controlled server
thread was idle in `serve_forever`; the last `/attachment` progress entry was not
the blocked operation. The Playwright implementation invokes socket handlers
from asyncio directly; inline sync close waits on that same dispatcher loop.

R3 queues socket closure without a server connection and drains it from regular
capture control flow in both normal crawl and Phase 3. Two new regressions verify
that a handler running under asyncio never invokes sync close/connect, closure
happens once outside dispatch, and Phase 3 has no duplicate inline override.
Complete regression: 230 passed, 0 failures/errors/skips, Python 3.12.14, 20.900 s.
Existing dependencies were reused via PYTHONPATH because the old venv interpreter
symlink no longer resolved after runtime refresh; the runtime Node was used for
Playwright's driver. No dependencies or security restrictions were changed.
Scoring/default export compatibility remains verified. No real Chrome executable
is available locally; Windows R3 and all 75 checks/18 screenshots remain pending.
No timeout increase, GitHub operation or C2B/C3 expansion occurred.


## V6.1.1 Phase C2B — lifecycle validation (14 October 2026 UTC)

Baseline: `9439ff93d89854f6b207ad68057ae75e51fbedd2`. Isolated detached worktree;
no commits, GitHub writes or dependency changes.

- Focused lifecycle suite: 26 tests passed, including real Python worker and
  descendant cleanup on success, crash and timeout, including detached child
  groups that mirror Playwright Chrome launches; mocked interruption, Windows
  Job assignment order/failure, second communicate timeout, checkpoint integrity,
  partial links/depth/status evidence and nine-file exports.
- Existing browser unit fixtures now target `_crawl_site_local` to retain their
  deterministic injection; production `crawl_site` uses the supervisor. The C2B
  Chrome harness separately tests that public API across real worker boundaries.
- Complete regression suite: 256 tests passed (final exact run/time is recorded
  in the review package). No tests were skipped or assertions weakened.
- Compatibility comparison: default nine exports and twelve sitemap-enabled
  exports byte-identical for controlled baseline inputs; fixed metadata/timestamp
  used only by the comparator. Score ASTs and C1, sitemap, Phase A/discovery UI
  source unchanged. Phase 3 replay policy, limits and extraction semantics unchanged.
- Secure browser probe: blocked; 0 real-browser checks executed here. Neither
  Chrome nor bundled Chromium could be launched under the unchanged secure policy.
  No browser installation, insecure launch retry or public-site crawl was used.

Windows acceptance requires Python 3.12, installed Google Chrome, 256 regression
tests and 98 checks (44 existing rendering/report, 5 C1, 26 C2A, 23 C2B). Review
22 normal desktop/mobile report screenshots (18 existing plus 4 lifecycle reports).
The C2B checks cover rendered headings/links, alias/depth/scope/status evidence,
hard infinite-script deadlines, browser-close hangs, Chrome worker crashes,
interruption, Job Object tree cleanup and viewport overflow. Each count is actual;
unexecuted checks are blocked, never passed. Windows acceptance is pending.

Remaining C3 limits: no CPU/RAM/PID/egress/filesystem quotas, no container boundary,
no guarantee against a compromised process escaping a POSIX process group or an
OS stall. Abrupt parent death on POSIX requires an external supervisor; Windows
Job close is automatic but not yet verified on the user's machine. The unused
`browser_available` helper is a direct probe, not an audit execution entry point.
Public deployment remains on hold.


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


## V6.1.1 Phase C3A — local launch / worker environment validation

Baseline: `faa7a38337f1217953298794baf0137da2cfe5af`. A fresh isolated detached
worktree was used; unrelated C2B publication workspaces were preserved.

Focused regression scope:

- Both START-APP.bat interpreter branches bind to 127.0.0.1 and retain security
  configuration; no forwarded arguments can silently replace the binding.
- Explicit allowlist preserves Windows/Chrome, Python venv, temporary/cache and
  optional Playwright runtime paths, including Windows environment-key casing.
- Synthetic API keys, proxy values, tokens, passwords and Python/Node hooks are
  excluded from real child workers; fixed Python runtime settings are enforced.
- Parent environment and PageSpeed key remain intact. PageSpeed AppTest uses a
  mocked Google response and confirms the parent API request retains its key;
  no live API call, paid service or real credential is used.
- Real supervised workers start in the same venv, import project/browser modules
  with installed dependencies, and retain cleanup/unavailable failure behavior.

The review package records exact executed totals, timings, source hashes and
compatibility results. The full suite includes existing C1/C2A/C2B lifecycle
regressions. Windows Chrome validation must use the exact patched snapshot and
record the same 98 browser checks and 22 viewport screenshots, plus its complete
automated suite. Windows acceptance is pending until actually executed.

Manual Windows launch acceptance: run START-APP.bat from the isolated validation
project, inspect the running app's listening socket with Get-NetTCPConnection
(or netstat), and verify it listens only at 127.0.0.1 on the chosen port. Retain
that evidence without disabling CORS/XSRF. A successful local page alone does not
prove lack of LAN exposure. Native BAT execution cannot be certified on Linux.

No SEO scoring, default export names, dependencies, existing C1/C2A network
policy, C2B Job/lifecycle limits, firewall rules, Windows accounts or ACLs were
changed. Environment filtering does not prevent same-user filesystem access,
OS-level egress, resource exhaustion or a compromised interpreter/browser. C3B
and C3C remain separately scoped; no public deployment readiness is claimed.

## Phase C3B — resource-containment acceptance

Baseline: `36c98ecd4537cc421e0ffe08321f62a10b0bed36`. Exact local test totals,
source/patch checksums and package identity are in the C3B review package.

`tests/test_worker_resources.py` covers policy bounds, fail-closed configuration,
CPU/memory/process-cap setup and readback, no breakaway, API failure cleanup,
notification termination, output rejection, partial checkpoint/unknown HTTP
status, unavailable Phase 3 evidence, and bounded CSV inputs. API fakes are
explicitly not native Windows enforcement. Existing cancellation, crashes,
timeouts, worker environment, scoring and export regressions remain required.
The old membership-only Job fixture now stubs resource snapshots independently;
its PID/truncation/query assertions remain unchanged.

Windows acceptance uses Python 3.12 and installed Chrome in a new isolated
project, not an original local project. `tests/windows_c3b_validation.py` must
produce **16/16 actual native checks**: default-cap readback/start/cleanup,
real process refusal at four processes, real refused commit at 128 MiB, measured
CPU throttling at 2% against a 10% capped reference, owned Job cleanup and survival
of an unrelated harmless sentinel. Tight fixture limits are not app defaults.
Every stress worker uses the production supervisor with a 15-second hard deadline;
existing C2B 10-second infinite-script and cancellation checks remain unchanged.
A high-core-count machine or heavy competing workload can make CPU calibration
inconclusive; that is a failed acceptance gate, not a reason to skip or label it
passed. Preserve raw accounting, markers, requested/readback caps and cleanup
membership snapshots. Do not infer physical-RAM or whole-app containment.

Also require the complete regression suite, 98 real Chrome checks (44 existing,
5 C1, 26 C2A, 23 C2B) under the explicit low-resource validation profile and review all 22 desktop/mobile
screenshots. These validate controlled fixtures, not every real client site.
Calibrate limits separately for authorized representative JavaScript-heavy client
sites on the operator's hardware before regular use. Record selected caps and
incomplete evidence; never relax C1/C2 restrictions or deadlines to hide a failure.

The Windows launcher writes actual results, counts, source hashes, resource
configuration and checksummed evidence. Its final automated status still requires
visual acceptance. No historical pass certifies this C3B patch. Linux/Work cannot
verify Windows Job ABI, enforcement, OS accounting, nested Jobs, DFSS, firewall,
ACLs, native BAT execution or Chrome behavior on the operator's machine.
Whole-operation resource caps, concurrent-audit admission control, independent
watchdog, OS egress/filesystem isolation and C3C infrastructure remain unresolved.

### C3B R2 acceptance — guarded low-resource mode

R1 six native passes are historical partial evidence, not R2 acceptance. The
corrected package records actual run ID, exact aggregate/delta patches and source
hashes, measured host availability/CPU, marker states, per-fixture termination and
per-stage lifecycle-Job cleanup. It never substitutes a missing marker with success
or labels skipped/inconclusive checks passed. All original deadline/security
assertions remain. Native Windows stress fixtures were not executed on Linux.

Required R2 sequence: available-memory/commit/CPU preflight; serial full regression;
16 actual native checks with tight fixture budgets; 98 Chrome checks under the
explicit 32-process/1024-MiB/25% validation profile; review 22 screenshots. Resource
pressure, failed native measurement, unavailable telemetry, unsupported nested
Jobs, cleanup uncertainty or operator cancellation stop the affected stage and
produce NOT VERIFIED plus automatic evidence. No automatic retries or threshold
bypass are provided. Ctrl+C requests cleanup and evidence packaging; force-closing
the console cannot guarantee the final ZIP was written. Kill-on-close stage Jobs
provide a termination backstop, not a guarantee against OS failure.

Deterministic R2 regressions cover interrupted atomic replacement, legacy empty-file
reproduction, invalid/missing marker evidence, preserving termination diagnostics,
host thresholds, CPU accounting and pressure persistence/recovery, bounded single-
thread fixture design, validation-stage assignment failure and lifecycle cleanup.
Windows API fakes are wiring tests only. The supplied failed logs do not include
full source provenance or memory-worker evidence; do not claim that historical
memory/CPU enforcement or RAM shortage was verified. Real R2 Windows results are
pending. Default production resource settings remain unchanged and are not
certified for a 6-GB machine by these tests.
