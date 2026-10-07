# Validation - V6.1 client delivery edition

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
