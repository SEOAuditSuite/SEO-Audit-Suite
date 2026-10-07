"""Explicit, ordered page registry."""
PAGE_GROUPS = {
    "Start": [
        ("overview.py", "Overview"),
        ("pages/23_Client_Workspace.py", "Client Workspace"),
    ],
    "Technical & On-Page SEO": [
        ("pages/0_Complete_Audit.py", "Complete Audit"),
        ("pages/1_Broken_Links.py", "Broken Links"),
        ("pages/2_Sitemap_Robots.py", "Sitemap & Robots"),
        ("pages/3_PageSpeed.py", "PageSpeed"),
        ("pages/4_Keywords_Headings.py", "Keywords & Headings"),
        ("pages/6_Meta_Canonical.py", "Meta & Canonical"),
        ("pages/7_Image_SEO.py", "Image SEO"),
        ("pages/8_Schema_Inspector.py", "Schema Inspector"),
        ("pages/9_Redirect_Checker.py", "Redirect Checker"),
        ("pages/10_Internal_Links.py", "Internal Links"),
        ("pages/11_Google_Search_Console.py", "Google Search Console"),
    ],
    "AI Search": [
        ("pages/5_AEO_AI_Readiness.py", "Legacy AEO Checklist"),
        ("pages/12_AEO_Intelligence.py", "AEO Intelligence"),
        ("pages/13_GEO_Intelligence.py", "GEO Intelligence"),
        ("pages/14_Entity_Intelligence.py", "Entity Intelligence"),
        ("pages/15_AI_Crawler_Accessibility.py", "AI Crawler Accessibility"),
        ("pages/20_AI_Search_Audit.py", "AI Search Audit"),
    ],
    "Trust & Competition": [
        ("pages/16_Authority_Intelligence.py", "Authority Intelligence"),
        ("pages/17_Reputation_Intelligence.py", "Reputation Intelligence"),
        ("pages/18_External_Mentions.py", "External Mentions"),
        ("pages/19_Competitive_Intelligence.py", "Competitive Intelligence"),
    ],
    "Strategy & Reports": [
        ("pages/21_30_60_Day_Strategy.py", "30/60-Day Strategy"),
        ("pages/22_Client_Report_PDF.py", "Client Report & PDF"),
    ],
}
