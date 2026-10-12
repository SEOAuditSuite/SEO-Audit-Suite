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
