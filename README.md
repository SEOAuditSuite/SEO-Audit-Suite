# SEO Audit Suite Pro V5

A browser-rendered Python/Streamlit SEO audit suite designed for modern JavaScript websites and client reporting.

## V5 highlights
- JavaScript/browser rendering using installed Chrome when available
- Same-domain crawl up to 50 pages
- One shared crawl dataset across the Complete Audit and evidence tables
- Technical SEO, on-page SEO, Schema, Image SEO, Social Metadata and AEO readiness scores
- Overall SEO Health score calculated by this application
- Page-level and site-wide Schema coverage
- Rendered internal-link and anchor-text inventory
- Conservative broken-link classification: 4xx responses from external platforms are flagged for verification rather than automatically called confirmed broken
- HTML client report export
- Google Search Console CSV performance import (separate from the audit score)

## Important scoring note
SEO Audit Suite scores are application-defined audit measurements. They are **not official Google ranking scores** and should not be presented as such.

AEO Readiness is a heuristic checklist. It is **not a Google, ChatGPT, or AI-search ranking score**.

Performance in the main audit is based on crawl-response timing. For Core Web Vitals/Lighthouse data, use the PageSpeed module with a Google PageSpeed Insights API key.

## Run on Windows
```text
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

The crawler first attempts to use the Chrome installation already on the computer, so a separate `playwright install chromium` download is not required when Chrome is available.

## Client-service workflow
The Complete Audit is designed to support an SEO professional's client workflow: identify evidence-backed findings, explain why they matter, assign an application-defined priority, and surface relevant SEO service areas. Client reports intentionally use **Recommended SEO Action** rather than step-by-step DIY implementation instructions.
