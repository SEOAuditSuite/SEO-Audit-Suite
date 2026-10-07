# SEO Audit Suite V6.1

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
