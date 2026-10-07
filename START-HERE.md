# SEO Audit Suite V6.1 - client delivery edition

## Roman Urdu quick start

1. Is folder ko apni working location par extract karein. Purane V5/V6 ki backup copy rakhein.
2. Terminal mein isi folder ko open karein aur neeche diye commands run karein.
3. App ke sidebar se **Client Workspace** kholein. Website, client name, apna naam, market aur goal fill karein.
4. Pehle 5-10 pages ka sample run karein. Complete pack download karein.
5. Codex mein yeh project folder open karein. Downloaded client evidence pack dein aur likhein:
   `Use $seo-client-delivery. Review this evidence and prepare a prioritized client SEO action plan.`
6. Report aur priority findings manually verify karke client ko deliver karein. Sirf app ka score dekh
   kar ranking, AI citation ya leads ki guarantee na dein.

Skill project ke `.agents/skills/seo-client-delivery` folder mein bundled hai. Yeh Streamlit ke andar
GPT API nahi chalati. Codex ko project open karne par skill discover karni chahiye; agar naam na aaye,
new chat kholein aur exact SKILL.md file read karne ko kahein. Kisi doosre assistant mein file aur
references upload/read karwana hoga; sirf ZIP dene ko permanent model training na samjhein.

## Sidebar fix

Poora folder extract karein: `app.py`, `navigation.py`, `overview.py` aur `pages/` saath hone chahiye.
Dependencies install/update karne ke baad **START-APP.bat** double-click karein. Yeh main app kholta hai.
`pages/` ki kisi individual file ko direct launch na karein. Sidebar mein Overview aur tamam 24 tools
categories mein registered hain; neeche ke tools ke liye menu scroll karein. Chhoti screen par sidebar
content ke upar khul sakta hai; page select karke top-left arrow se menu band/khol sakte hain.

## Run locally

Python 3.11+ is recommended; this release was tested with Python 3.14 on Windows.

```powershell
python -m venv .venv
.\.venv\Scripts\python.exe -m pip install -r requirements.txt
.\.venv\Scripts\python.exe -m playwright install chromium
.\.venv\Scripts\python.exe -m streamlit run app.py
```

Existing Chrome may also work. If rendering is unavailable, the app uses HTTP HTML and reports that
limitation. Keep this as a local consultant tool; public multi-user hosting requires a separate review
of URL fetching, access control and resource limits.

## What changed

- JSON-LD in the body survives text extraction.
- robots.txt and default sitemap lookup use the website origin, including when auditing an inner URL.
- URL-specific robots evaluation includes wildcard fallback, specific groups, merged groups,
  path exceptions, longest-match selection and Allow-on-tie.
- Unknown robots data is marked unverified; training controls do not lower search access scores.
- Word-count components are labeled as content-length proxies.
- Client Workspace exports reports, traceable issue log, page inventory, evidence JSON and AI handoff
  from one saved run. Downloads survive UI reruns.
- Keyword CSV import requires a source for supplied volume/rank and retains unknown data explicitly.
- New project skill guides manual review, content briefs, local SEO and 30/60/90-day planning.

## Using the package commercially

Start with the scoped offers in `UPWORK-SERVICE-KIT.md`. They sell analysis and an action plan, with
implementation agreed separately. The demonstration report uses synthetic pages and is labeled as a
sample, not a successful client case study. Add genuine project outcomes only after measuring them.

The original Beyond SEO package is not redistributed here. This release has a newly written skill
specific to this toolkit. No paid scraping account or GPT API key is required for the built-in audit.

## Updating GitHub

Copy these source files into your existing repository on a new branch, including the hidden `.agents`
folder. Review changes, run tests, then commit and push using your normal workflow. This delivered
folder excludes your old `.git` history and credentials. No GitHub push or Upwork publication was made.

## Verification

```powershell
python -m unittest discover -s tests -v
python -m compileall -q .
```

Read `VALIDATION.md` for the actual checks and remaining limits. Dependency versions remain minimum
bounds from your original project; other machines may need compatible versions or browser setup.
