from __future__ import annotations

from datetime import datetime
from html import escape
from io import BytesIO
from urllib.parse import urlparse

REPORT_ENGINE_VERSION = "6.5-final-gui-report-polish"


def _safe(value, fallback=""):
    text = str(value or fallback).strip()
    return text


def _domain(url):
    try:
        return urlparse(url).netloc.lower().removeprefix("www.") or url
    except Exception:
        return url


def _priority_rank(priority):
    return {"HIGH": 0, "MEDIUM": 1, "OPPORTUNITY": 2, "INFO": 3}.get(priority, 9)


def _finding_library(signal):
    library = {
        "AEO readiness": {
            "why": "Clear question targeting and concise direct answers make important content easier to interpret for answer-oriented search experiences.",
            "action": "Strengthen question-led sections and concise answer-first responses on priority pages.",
        },
        "Entity clarity": {
            "why": "Consistent business and entity identity helps search and AI systems connect the brand, organization, location and site content.",
            "action": "Strengthen business/entity definition with consistent identity signals and appropriate structured data.",
        },
        "AI crawler accessibility": {
            "why": "Important content must remain technically accessible, indexable and canonically consistent before search or AI systems can evaluate it reliably.",
            "action": "Review crawler access, robots directives, canonical signals and indexability across important templates.",
        },
        "Structured data coverage": {
            "why": "Relevant structured data provides machine-readable context for entities and eligible content types.",
            "action": "Expand valid page-appropriate Schema.org coverage across priority templates and content types.",
        },
        "Content depth": {
            "why": "Useful intent-matched page content gives search and AI systems more evidence to interpret, summarize and answer from.",
            "action": "Strengthen thin priority pages with useful intent-matched information rather than filler text.",
        },
        "Internal architecture": {
            "why": "Clear contextual internal linking improves discovery, topical relationships and navigation between important pages.",
            "action": "Improve contextual internal linking between priority categories, products, services and supporting content.",
        },
        "Authority foundations": {
            "why": "Transparent identity, editorial ownership, source references and trust pages help users and machines understand who is responsible for the site and content.",
            "action": "Strengthen About, editorial ownership, citation and trust-policy signals across the site.",
        },
        "Reputation foundations": {
            "why": "Verifiable social proof and reputation evidence can reinforce trust and brand credibility.",
            "action": "Strengthen verifiable review, testimonial, profile and reputation evidence where appropriate.",
        },
    }
    return library.get(signal, {
        "why": "This signal contributes to the overall quality and interpretability of the audited website.",
        "action": "Review the signal and prioritize evidence-based improvements on important pages.",
    })


def build_client_report_model(audit, plan, client_name="", prepared_by="SEO Audit Suite Pro", report_title="SEO + AI Search Audit Report"):
    """Create a presentation-safe report model from an AI Search Audit and strategy."""
    if not audit or audit.get("error"):
        raise ValueError("A valid AI Search Audit result is required.")

    url = audit.get("url", "")
    raw = audit.get("raw", {})
    seo = raw.get("seo", {}) or {}

    findings = []
    for item in audit.get("findings", []):
        signal = item.get("signal", "Audit signal")
        copy = _finding_library(signal)
        findings.append({
            "priority": item.get("priority", "MEDIUM"),
            "finding": item.get("finding", ""),
            "why_it_matters": copy["why"],
            "recommended_action": copy["action"],
            "service_area": item.get("service_area", signal),
            "score": item.get("score", 0),
            "weight": item.get("weight", 0),
        })
    findings.sort(key=lambda x: (_priority_rank(x["priority"]), x.get("score", 0)))

    executive_points = []
    weak = [x for x in findings if x["priority"] == "HIGH"]
    medium = [x for x in findings if x["priority"] == "MEDIUM"]
    strong_components = [
        name for name, (score, _weight) in audit.get("components", {}).items()
        if score >= 80
    ]
    if weak:
        executive_points.append(
            f"Highest-priority improvement areas: {', '.join(x['service_area'] for x in weak[:3])}."
        )
    if strong_components:
        executive_points.append(
            f"Strong current foundations: {', '.join(strong_components[:4])}."
        )
    if medium:
        executive_points.append(
            f"Secondary improvement areas include {', '.join(x['service_area'] for x in medium[:3])}."
        )
    executive_points.append(
        "The 30/60-day roadmap prioritizes observable technical, content, entity, authority and reputation signals; rankings and AI citations should be tracked separately."
    )

    scorecards = []
    overall_seo = seo.get("Overall SEO Health")
    if overall_seo is not None:
        scorecards.append(("Overall SEO Health", overall_seo))
    scorecards.extend([
        ("AI Search Audit", audit.get("score", 0)),
        ("AEO Intelligence 2.0", raw.get("aeo", {}).get("score", 0)),
        ("GEO", raw.get("geo", {}).get("score", 0)),
        ("Entity", raw.get("entity", {}).get("score", 0)),
        ("Crawler Access", raw.get("crawler", {}).get("score", 0)),
        ("Authority", raw.get("authority", {}).get("score", 0)),
        ("Reputation", raw.get("reputation", {}).get("score", 0)),
    ])

    traditional = []
    traditional_labels = {
        "AEO Readiness": "Legacy AEO Checklist",
    }
    for key in (
        "Technical SEO", "On-Page SEO", "Performance", "Schema",
        "Image SEO", "Social Metadata", "AEO Readiness",
    ):
        if key in seo:
            traditional.append((traditional_labels.get(key, key), seo[key]))

    return {
        "report_title": _safe(report_title, "SEO + AI Search Audit Report"),
        "client_name": _safe(client_name),
        "prepared_by": _safe(prepared_by, "SEO Audit Suite Pro"),
        "website": url,
        "domain": _domain(url),
        "generated_at": datetime.now().strftime("%Y-%m-%d %H:%M"),
        "readiness": audit.get("readiness", "Weak"),
        "ai_search_score": audit.get("score", 0),
        "pages_crawled": audit.get("pages_crawled", 0),
        "crawl_errors": audit.get("crawl_errors", 0),
        "schema_coverage": audit.get("evidence", {}).get("schema_coverage_percent", 0),
        "average_words": audit.get("evidence", {}).get("average_words", 0),
        "internal_destinations": audit.get("evidence", {}).get("unique_internal_destinations", 0),
        "scorecards": scorecards,
        "traditional_scores": traditional,
        "components": audit.get("components", {}),
        "executive_points": executive_points,
        "findings": findings,
        "first_30_days": plan.get("first_30_days", []) if plan else [],
        "days_31_60": plan.get("days_31_60", []) if plan else [],
        "strategy_summary": plan.get("summary", {}) if plan else {},
        "audit_disclaimer": audit.get("disclaimer", ""),
        "strategy_disclaimer": plan.get("disclaimer", "") if plan else "",
        "engine": REPORT_ENGINE_VERSION,
    }


def build_client_report_pdf(model):
    """Return professional PDF bytes for a report model."""
    try:
        from reportlab.lib import colors
        from reportlab.lib.enums import TA_CENTER, TA_LEFT
        from reportlab.lib.pagesizes import A4
        from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
        from reportlab.lib.units import mm
        from reportlab.platypus import (
            SimpleDocTemplate, Paragraph, Spacer, Table, TableStyle,
            PageBreak, KeepTogether,
        )
    except ImportError as exc:
        raise RuntimeError("PDF generation requires reportlab. Install project requirements and try again.") from exc

    buffer = BytesIO()
    doc = SimpleDocTemplate(
        buffer,
        pagesize=A4,
        rightMargin=15 * mm,
        leftMargin=15 * mm,
        topMargin=16 * mm,
        bottomMargin=16 * mm,
        title=model.get("report_title", "SEO + AI Search Audit Report"),
        author=model.get("prepared_by", "SEO Audit Suite Pro"),
    )

    styles = getSampleStyleSheet()
    styles.add(ParagraphStyle(
        name="ReportTitle", parent=styles["Title"], fontName="Helvetica-Bold",
        fontSize=22, leading=26, alignment=TA_LEFT, spaceAfter=7,
        textColor=colors.HexColor("#172033"),
    ))
    styles.add(ParagraphStyle(
        name="SubTitle", parent=styles["Normal"], fontSize=10.5, leading=15,
        textColor=colors.HexColor("#586273"), spaceAfter=4,
    ))
    styles.add(ParagraphStyle(
        name="Section", parent=styles["Heading2"], fontName="Helvetica-Bold",
        fontSize=14, leading=18, textColor=colors.HexColor("#172033"),
        spaceBefore=8, spaceAfter=8,
    ))
    styles.add(ParagraphStyle(
        name="Small", parent=styles["Normal"], fontSize=8.5, leading=12,
        textColor=colors.HexColor("#586273"),
    ))
    styles.add(ParagraphStyle(
        name="Body2", parent=styles["Normal"], fontSize=9.5, leading=14,
        textColor=colors.HexColor("#263143"),
    ))
    styles.add(ParagraphStyle(
        name="FindingTitle", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=10.2, leading=14, textColor=colors.HexColor("#172033"),
        spaceAfter=3,
    ))
    styles.add(ParagraphStyle(
        name="CenterScore", parent=styles["Normal"], fontName="Helvetica-Bold",
        fontSize=15, leading=18, alignment=TA_CENTER, textColor=colors.HexColor("#172033"),
    ))
    styles.add(ParagraphStyle(
        name="CenterLabel", parent=styles["Normal"], fontSize=7.8, leading=10,
        alignment=TA_CENTER, textColor=colors.HexColor("#586273"),
    ))

    story = []
    story.append(Paragraph(escape(model["report_title"]), styles["ReportTitle"]))
    story.append(Paragraph("Professional client report generated from browser-rendered SEO and AI-search audit evidence.", styles["SubTitle"]))
    meta_lines = [
        f"<b>Website:</b> {escape(model['website'])}",
        f"<b>Audit date:</b> {escape(model['generated_at'])}",
        f"<b>Prepared by:</b> {escape(model['prepared_by'])}",
    ]
    if model.get("client_name"):
        meta_lines.insert(1, f"<b>Client:</b> {escape(model['client_name'])}")
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph("<br/>".join(meta_lines), styles["Body2"]))
    story.append(Spacer(1, 7 * mm))

    score_cells = []
    for name, score in model.get("scorecards", [])[:8]:
        score_cells.append(Table([
            [Paragraph(f"{score}/100", styles["CenterScore"])],
            [Paragraph(escape(name), styles["CenterLabel"])],
        ], colWidths=[42 * mm], rowHeights=[10 * mm, 9 * mm]))
    while len(score_cells) % 4:
        score_cells.append("")
    score_rows = [score_cells[i:i+4] for i in range(0, len(score_cells), 4)]
    score_table = Table(score_rows, colWidths=[43 * mm] * 4, hAlign="LEFT")
    score_table.setStyle(TableStyle([
        ("VALIGN", (0,0), (-1,-1), "MIDDLE"),
        ("BOX", (0,0), (-1,-1), 0.5, colors.HexColor("#D7DEE8")),
        ("INNERGRID", (0,0), (-1,-1), 0.5, colors.HexColor("#E7EBF0")),
        ("BACKGROUND", (0,0), (-1,-1), colors.HexColor("#F8FAFC")),
        ("LEFTPADDING", (0,0), (-1,-1), 3),
        ("RIGHTPADDING", (0,0), (-1,-1), 3),
        ("TOPPADDING", (0,0), (-1,-1), 4),
        ("BOTTOMPADDING", (0,0), (-1,-1), 4),
    ]))
    story.append(score_table)
    story.append(Spacer(1, 6 * mm))

    story.append(Paragraph("Executive Summary", styles["Section"]))
    story.append(Paragraph(
        f"The audited site achieved an <b>AI Search Audit Score of {model['ai_search_score']}/100</b> with <b>{escape(model['readiness'])}</b> readiness. "
        f"The crawl covered {model['pages_crawled']} page(s), with {model['schema_coverage']}% structured-data coverage, "
        f"an average of {model['average_words']} rendered words per page and {model['internal_destinations']} unique internal destinations.",
        styles["Body2"],
    ))
    story.append(Spacer(1, 2 * mm))
    for point in model.get("executive_points", []):
        story.append(Paragraph(f"- {escape(point)}", styles["Body2"]))
    story.append(Spacer(1, 5 * mm))

    story.append(Paragraph("AI Search Signal Breakdown", styles["Section"]))
    component_rows = [["Signal", "Score", "Weight"]]
    for name, (score, weight) in model.get("components", {}).items():
        component_rows.append([name, f"{score}/100", f"{weight}%"])
    component_table = Table(component_rows, colWidths=[100 * mm, 32 * mm, 28 * mm], repeatRows=1)
    component_table.setStyle(TableStyle([
        ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EEF2F7")),
        ("TEXTCOLOR", (0,0), (-1,0), colors.HexColor("#172033")),
        ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
        ("FONTNAME", (0,1), (-1,-1), "Helvetica"),
        ("FONTSIZE", (0,0), (-1,-1), 8.5),
        ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D7DEE8")),
        ("VALIGN", (0,0), (-1,-1), "TOP"),
        ("TOPPADDING", (0,0), (-1,-1), 5),
        ("BOTTOMPADDING", (0,0), (-1,-1), 5),
    ]))
    story.append(component_table)

    if model.get("traditional_scores"):
        story.append(Spacer(1, 4 * mm))
        trad_rows = [["Category", "Score"]] + [[name, f"{score}/100"] for name, score in model["traditional_scores"]]
        trad_table = Table(trad_rows, colWidths=[120 * mm, 40 * mm], repeatRows=1)
        trad_table.setStyle(TableStyle([
            ("BACKGROUND", (0,0), (-1,0), colors.HexColor("#EEF2F7")),
            ("FONTNAME", (0,0), (-1,0), "Helvetica-Bold"),
            ("FONTSIZE", (0,0), (-1,-1), 8.5),
            ("GRID", (0,0), (-1,-1), 0.4, colors.HexColor("#D7DEE8")),
            ("TOPPADDING", (0,0), (-1,-1), 5),
            ("BOTTOMPADDING", (0,0), (-1,-1), 5),
        ]))
        story.append(KeepTogether([Paragraph("Traditional SEO Scorecard (legacy checklist components)", styles["Section"]), trad_table]))

    story.append(Spacer(1, 5 * mm))
    story.append(Paragraph("Prioritized Findings", styles["Section"]))
    if not model.get("findings"):
        story.append(Paragraph("No major weak components were detected by the current AI Search Audit model.", styles["Body2"]))
    else:
        for idx, item in enumerate(model["findings"], start=1):
            block = [
                Paragraph(f"{idx}. {escape(item['priority'])} - {escape(item['service_area'])}", styles["FindingTitle"]),
                Paragraph(f"<b>Finding:</b> {escape(item['finding'])}", styles["Body2"]),
                Paragraph(f"<b>Why it matters:</b> {escape(item['why_it_matters'])}", styles["Body2"]),
                Paragraph(f"<b>Recommended SEO Action:</b> {escape(item['recommended_action'])}", styles["Body2"]),
                Paragraph(f"<b>Audit evidence:</b> {item['score']}/100 signal score; {item['weight']}% weight in the AI Search Audit model.", styles["Small"]),
                Spacer(1, 4 * mm),
            ]
            story.append(KeepTogether(block))

    def roadmap_section(title, items):
        story.append(Paragraph(title, styles["Section"]))
        if not items:
            story.append(Paragraph("No specific actions were generated for this period.", styles["Body2"]))
            return
        for idx, item in enumerate(items, start=1):
            block = [
                Paragraph(f"{idx}. Strategy Priority: {escape(item.get('priority',''))} - {escape(item.get('service_area',''))}", styles["FindingTitle"]),
                Paragraph(f"<b>Recommended SEO Action:</b> {escape(item.get('recommended_action',''))}", styles["Body2"]),
                Paragraph(f"<b>Why it matters:</b> {escape(item.get('why_it_matters',''))}", styles["Body2"]),
                Paragraph(f"<b>Success signal:</b> {escape(item.get('success_signal',''))}", styles["Small"]),
                Spacer(1, 4 * mm),
            ]
            story.append(KeepTogether(block))

    story.append(PageBreak())
    roadmap_section("First 30 Days - Foundation & Critical Gaps", model.get("first_30_days", []))
    roadmap_section("Days 31-60 - Expansion, Authority & Validation", model.get("days_31_60", []))

    story.append(Paragraph("Scope & Methodology", styles["Section"]))
    story.append(Paragraph(
        "This report is generated from the SEO Audit Suite Pro browser-rendered crawl and its application-defined SEO/AEO/GEO/entity/crawler/authority/reputation models. "
        "Scores summarize observable signals in this run and are designed for prioritization and client communication.",
        styles["Body2"],
    ))
    story.append(Spacer(1, 2 * mm))
    story.append(Paragraph(
        "The report does not represent an official Google, OpenAI, Bing, Perplexity, Moz, Ahrefs or Semrush score. It does not guarantee rankings, traffic, conversions or AI citations. "
        "External performance, backlink, review and ranking data should be validated in the relevant third-party platforms.",
        styles["Small"],
    ))
    story.append(Spacer(1, 4 * mm))
    story.append(Paragraph(f"Report engine: {escape(model.get('engine',''))}", styles["Small"]))

    def footer(canvas, doc_obj):
        canvas.saveState()
        canvas.setFont("Helvetica", 7.5)
        canvas.setFillColor(colors.HexColor("#7A8494"))
        canvas.drawString(15 * mm, 9 * mm, _safe(model.get("domain"), "SEO Audit Suite Pro"))
        canvas.drawRightString(A4[0] - 15 * mm, 9 * mm, f"Page {doc_obj.page}")
        canvas.restoreState()

    doc.build(story, onFirstPage=footer, onLaterPages=footer)
    return buffer.getvalue()


def build_client_report_html(model):
    """Return a portable HTML client report for preview/download."""
    def score_cards():
        return "".join(
            f"<div class='score'><div class='n'>{escape(str(score))}/100</div><div class='l'>{escape(name)}</div></div>"
            for name, score in model.get("scorecards", [])
        )

    findings = "".join(
        f"<article class='finding'><span class='pill {escape(item['priority'].lower())}'>{escape(item['priority'])}</span>"
        f"<h3>{escape(item['service_area'])}</h3>"
        f"<p><b>Finding:</b> {escape(item['finding'])}</p>"
        f"<p><b>Why it matters:</b> {escape(item['why_it_matters'])}</p>"
        f"<p><b>Recommended SEO Action:</b> {escape(item['recommended_action'])}</p>"
        f"<small>Evidence: {item['score']}/100; weight {item['weight']}%</small></article>"
        for item in model.get("findings", [])
    ) or "<p>No major weak components were detected by the current model.</p>"

    def roadmap(items):
        return "".join(
            f"<article class='road'><b>Strategy Priority: {escape(item.get('priority',''))} - {escape(item.get('service_area',''))}</b>"
            f"<p>{escape(item.get('recommended_action',''))}</p>"
            f"<small>Success signal: {escape(item.get('success_signal',''))}</small></article>"
            for item in items
        )

    component_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{score}/100</td><td>{weight}%</td></tr>"
        for name, (score, weight) in model.get("components", {}).items()
    )
    traditional_rows = "".join(
        f"<tr><td>{escape(name)}</td><td>{score}/100</td></tr>"
        for name, score in model.get("traditional_scores", [])
    )
    exec_points = "".join(f"<li>{escape(p)}</li>" for p in model.get("executive_points", []))

    return f"""<!doctype html>
<html><head><meta charset='utf-8'><meta name='viewport' content='width=device-width,initial-scale=1'>
<title>{escape(model['report_title'])}</title>
<style>
body{{font-family:Arial,Helvetica,sans-serif;background:#f3f5f8;color:#172033;margin:0;line-height:1.5}}
main{{max-width:1100px;margin:auto;padding:28px}} .hero,.card{{background:#fff;border:1px solid #dce2ea;border-radius:16px;padding:24px;margin-bottom:18px}}
h1{{margin:0 0 8px;font-size:30px}} h2{{margin-top:0}} .muted{{color:#657083}} .scores{{display:grid;grid-template-columns:repeat(4,1fr);gap:10px;margin-top:18px}}
.score{{border:1px solid #dce2ea;border-radius:12px;padding:14px;background:#f9fbfd}} .score .n{{font-size:22px;font-weight:700}} .score .l{{font-size:12px;color:#657083}}
table{{width:100%;border-collapse:collapse}} td,th{{padding:9px;border:1px solid #dce2ea;text-align:left}} th{{background:#edf2f7}}
.finding,.road{{border:1px solid #e0e5ec;border-radius:12px;padding:15px;margin:12px 0}} .pill{{font-size:11px;font-weight:700;border-radius:999px;padding:4px 8px;background:#eef2f7}}
.pill.high{{background:#fde8e8;color:#9b1c1c}} .pill.medium{{background:#fff2d8;color:#845400}} .pill.opportunity{{background:#e8f5ea;color:#256b34}}
small,.note{{color:#657083}} @media(max-width:800px){{.scores{{grid-template-columns:repeat(2,1fr)}}}}
</style></head><body><main>
<section class='hero'><h1>{escape(model['report_title'])}</h1><div class='muted'>Professional SEO + AI Search client report</div>
<p><b>Website:</b> {escape(model['website'])}<br>{f"<b>Client:</b> {escape(model['client_name'])}<br>" if model.get('client_name') else ''}<b>Prepared by:</b> {escape(model['prepared_by'])}<br><b>Audit date:</b> {escape(model['generated_at'])}</p>
<div class='scores'>{score_cards()}</div></section>
<section class='card'><h2>Executive Summary</h2><p>AI Search Audit Score: <b>{model['ai_search_score']}/100</b> - {escape(model['readiness'])} readiness.</p><ul>{exec_points}</ul></section>
<section class='card'><h2>AI Search Signal Breakdown</h2><table><thead><tr><th>Signal</th><th>Score</th><th>Weight</th></tr></thead><tbody>{component_rows}</tbody></table></section>
<section class='card'><h2>Traditional SEO Scorecard <span class='muted'>(legacy checklist components)</span></h2><p class='note'>Legacy AEO Checklist is the older Complete Audit heuristic; AEO Intelligence 2.0 is the dedicated AI-search readiness model shown above.</p><table><thead><tr><th>Category</th><th>Score</th></tr></thead><tbody>{traditional_rows}</tbody></table></section>
<section class='card'><h2>Prioritized Audit Findings</h2>{findings}</section>
<section class='card'><h2>First 30 Days</h2>{roadmap(model.get('first_30_days', []))}</section>
<section class='card'><h2>Days 31-60</h2>{roadmap(model.get('days_31_60', []))}</section>
<section class='card'><h2>Scope & Methodology</h2><p>{escape(model.get('audit_disclaimer',''))}</p><p>{escape(model.get('strategy_disclaimer',''))}</p><small>Engine: {escape(model.get('engine',''))}</small></section>
</main></body></html>"""
