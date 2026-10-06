import streamlit as st

from ui import apply_global_ui

from common import crawl_site, normalize_url
from aeo_engine import (
    body_text_to_segments,
    run_aeo_analysis,
    analyze_answer_completeness,
    calculate_aeo_score_v2,
)


st.set_page_config(
    page_title="AEO Intelligence | SEO Audit Suite Pro",
    page_icon="🧠",
    layout="wide",
)
apply_global_ui()

st.title("🧠 AEO Intelligence 2.0")

st.markdown(
    """
    Analyze how clearly a webpage is structured to provide direct,
    useful and machine-readable answers for search engines and
    AI-powered answer systems.
    """
)

st.info(
    "AEO Intelligence uses an application-defined readiness score. "
    "It is not an official Google, ChatGPT, Bing, Perplexity or "
    "other AI-platform ranking score."
)

url = st.text_input(
    "Enter URL",
    placeholder="https://example.com",
)

analyze = st.button(
    "Run AEO Intelligence",
    type="primary",
    use_container_width=True,
)


if analyze:
    if not url.strip():
        st.warning("Please enter a URL to begin the analysis.")

    else:
        try:
            target_url = normalize_url(url.strip())

            with st.spinner(
                "Rendering webpage and running AEO Intelligence..."
            ):
                crawl = crawl_site(
                    target_url,
                    limit=1,
                    prefer_browser=True,
                )

            pages = crawl.get("pages", [])

            if not pages:
                st.error("The page could not be analyzed.")

                browser_error = crawl.get("browser_error")

                if browser_error:
                    st.caption(
                        f"Browser crawler message: {browser_error}"
                    )

            else:
                page = pages[0]

                # ---------------------------------
                # Prepare rendered V5 audit data
                # ---------------------------------

                headings = (
                    list(page.h1 or [])
                    + list(page.h2 or [])
                    + list(page.h3 or [])
                )

                paragraphs = body_text_to_segments(
                    page.body_text or ""
                )

                heading_text = " ".join(headings).lower()

                faq_heading_signal = any(
                    phrase in heading_text
                    for phrase in (
                        "faq",
                        "faqs",
                        "frequently asked questions",
                        "common questions",
                    )
                )

                faq_schema_signal = any(
                    str(schema_type).lower() == "faqpage"
                    for schema_type in (page.schema_types or [])
                )

                faq_present = (
                    faq_heading_signal
                    or faq_schema_signal
                )

                # ---------------------------------
                # Run base V6 AEO analysis
                # ---------------------------------

                result = run_aeo_analysis(
                    headings=headings,
                    paragraphs=paragraphs,
                    lists=page.lists,
                    tables=page.tables,
                    faq_present=faq_present,
                )

                # ---------------------------------
                # Prefer rendered DOM Q&A evidence
                # ---------------------------------

                dom_answers = getattr(
                    page,
                    "aeo_question_answers",
                    [],
                )

                if dom_answers:
                    dom_questions = [
                        item.get("question", "")
                        for item in dom_answers
                        if item.get("question")
                    ]

                    result["questions"] = dom_questions
                    result["question_count"] = len(dom_questions)
                    result["direct_answers"] = dom_answers

                    answered_count = sum(
                        1
                        for item in dom_answers
                        if item.get("answer_found")
                    )

                    question_count = len(dom_questions)

                    
                # ---------------------------------
                # Rebuild opportunities using
                # final DOM-based answer evidence
                # ---------------------------------

                opportunities = []

                if result["question_count"] == 0:
                    opportunities.append(
                        {
                            "priority": "HIGH",
                            "finding": (
                                "No clear question-focused "
                                "content detected."
                            ),
                            "service_area": (
                                "AEO Content Strategy"
                            ),
                        }
                    )

                unanswered_count = sum(
                    1
                    for item in result["direct_answers"]
                    if not item.get("answer_found")
                )

                if unanswered_count:
                    opportunities.append(
                        {
                            "priority": "HIGH",
                            "finding": (
                                f"{unanswered_count} detected "
                                "question(s) lack a nearby "
                                "direct-answer signal."
                            ),
                            "service_area": (
                                "Direct Answer Optimization"
                            ),
                        }
                    )

                if not faq_present:
                    opportunities.append(
                        {
                            "priority": "MEDIUM",
                            "finding": (
                                "No strong FAQ signal detected."
                            ),
                            "service_area": (
                                "FAQ & Answer Optimization"
                            ),
                        }
                    )

                if not result["formats"]["has_lists"]:
                    opportunities.append(
                        {
                            "priority": "OPPORTUNITY",
                            "finding": (
                                "No answer-friendly list "
                                "structure detected."
                            ),
                            "service_area": (
                                "Content Structure Optimization"
                            ),
                        }
                    )

                if not result["formats"]["has_tables"]:
                    opportunities.append(
                        {
                            "priority": "OPPORTUNITY",
                            "finding": (
                                "No tabular answer format detected."
                            ),
                            "service_area": (
                                "Structured Content Optimization"
                            ),
                        }
                    )

                result["opportunities"] = opportunities

                # ---------------------------------
                # Rebuild intent mapping using
                # final detected questions
                # ---------------------------------

                intent_summary = {}

                for question in result["questions"]:
                    q = question.lower().strip()

                    if q.startswith(
                        ("how ", "how do", "how can")
                    ):
                        intent = "How-to"

                    elif any(
                        word in q
                        for word in (
                            "best",
                            "compare",
                            " vs ",
                            "versus",
                            "price",
                            "cost",
                            "buy",
                            "order",
                        )
                    ):
                        intent = "Commercial"

                    elif q.startswith(
                        (
                            "what ",
                            "who ",
                            "where ",
                            "when ",
                            "why ",
                        )
                    ):
                        intent = "Informational"

                    else:
                        intent = "General Question"

                    intent_summary[intent] = (
                        intent_summary.get(intent, 0) + 1
                    )

                result["intent_summary"] = intent_summary

                # ---------------------------------
                # Answer completeness analysis
                # ---------------------------------

                answer_quality = analyze_answer_completeness(
                    result["direct_answers"]
                )

                result["answer_quality"] = answer_quality

                # ---------------------------------
                # AEO Readiness Score 2.0
                # ---------------------------------

                aeo_v2 = calculate_aeo_score_v2(
                    questions=result["questions"],
                    direct_answers=result["direct_answers"],
                    answer_quality=answer_quality,
                    formats=result["formats"],
                    faq_present=faq_present,
                    schema_types=page.schema_types or [],
                )

                result["score"] = aeo_v2["score"]
                result["readiness"] = aeo_v2["readiness"]
                result["score_breakdown"] = aeo_v2["breakdown"]
                result["score_evidence"] = aeo_v2["evidence"]

                # ---------------------------------
                # Display results
                # ---------------------------------

                st.success(
                    "AEO Intelligence analysis completed."
                )

                if page.browser_rendered:
                    st.caption(
                        "✓ Browser-rendered DOM analyzed"
                    )
                else:
                    st.caption(
                        "Browser rendering was unavailable; "
                        "HTTP-rendered content was analyzed."
                    )

                answered_count = sum(
                    1
                    for item in result["direct_answers"]
                    if item.get("answer_found")
                )

                col1, col2, col3, col4 = st.columns(4)

                col1.metric(
                    "AEO Score",
                    f"{result['score']}/100",
                )

                col1.caption(
                    f"Readiness: {result['readiness']}"
                )

                col2.metric(
                    "Questions",
                    result["question_count"],
                )

                col3.metric(
                    "Direct Answers",
                    answered_count,
                )

                col4.metric(
                    "FAQ Signal",
                    (
                        "Found"
                        if result["faq_present"]
                        else "Not Found"
                    ),
                )

                st.divider()

                # ---------------------------------
                # AEO Score 2.0 breakdown
                # ---------------------------------

                st.subheader("AEO Score Breakdown")

                breakdown = result["score_breakdown"]

                b1, b2, b3 = st.columns(3)

                b1.metric(
                    "Question Targeting",
                    f"{breakdown['question_targeting']['score']}/20",
                )

                b2.metric(
                    "Direct Answer Coverage",
                    f"{breakdown['direct_answer_coverage']['score']}/25",
                )

                b3.metric(
                    "Answer Quality",
                    f"{breakdown['answer_quality']['score']}/20",
                )

                b4, b5, b6 = st.columns(3)

                b4.metric(
                    "FAQ Readiness",
                    f"{breakdown['faq_readiness']['score']}/15",
                )

                b5.metric(
                    "Answer Structure",
                    f"{breakdown['answer_friendly_structure']['score']}/10",
                )

                b6.metric(
                    "Structured Data",
                    f"{breakdown['structured_data']['score']}/10",
                )

                with st.expander("AEO Score Evidence"):
                    evidence = result["score_evidence"]

                    st.write(
                        f"**Questions Found:** "
                        f"{evidence['questions_found']}"
                    )

                    st.write(
                        f"**Verified Direct Answers:** "
                        f"{evidence['answers_found']}"
                    )

                    st.write(
                        f"**Answer Coverage:** "
                        f"{evidence['answer_coverage_percent']}%"
                    )

                    st.write(
                        f"**Average Answer Quality:** "
                        f"{evidence['average_answer_quality']}/100"
                    )

                    st.write(
                        "**FAQ Signal:** "
                        + (
                            "Yes"
                            if evidence["faq_signal"]
                            else "No"
                        )
                    )

                    st.write(
                        "**FAQ Schema:** "
                        + (
                            "Yes"
                            if evidence["faq_schema"]
                            else "No"
                        )
                    )

                    useful_schema = (
                        ", ".join(
                            evidence["useful_schema_types"]
                        )
                        if evidence["useful_schema_types"]
                        else "None"
                    )

                    st.write(
                        f"**Useful Structured Data:** "
                        f"{useful_schema}"
                    )

                st.caption(
                    "AEO Score 2.0 is an application-defined "
                    "readiness model based on observable page signals. "
                    "It is not an official ranking score from Google, "
                    "OpenAI or another AI platform."
                )

                st.divider()

                # ---------------------------------
                # Content structure
                # ---------------------------------

                st.subheader(
                    "Answer-Friendly Content Structure"
                )

                c1, c2, c3 = st.columns(3)

                c1.metric(
                    "Lists",
                    result["formats"]["lists_found"],
                )

                c2.metric(
                    "Tables",
                    result["formats"]["tables_found"],
                )

                c3.metric(
                    "Rendered Words",
                    page.word_count,
                )

                # ---------------------------------
                # Question discovery
                # ---------------------------------

                st.subheader("Question Discovery")

                if result["questions"]:
                    for question in result["questions"]:
                        st.write(f"• {question}")
                else:
                    st.warning(
                        "No clear question-focused content "
                        "was detected on this page."
                    )

                # ---------------------------------
                # Direct answer analysis
                # ---------------------------------

                st.subheader("Direct Answer Analysis")

                if result["direct_answers"]:
                    for item in result["direct_answers"]:
                        question = item.get(
                            "question",
                            "Detected Question",
                        )

                        answer = item.get(
                            "answer",
                            "",
                        )

                        if item.get("answer_found"):
                            st.markdown(
                                f"**✓ {question}**"
                            )

                            st.write(answer)

                            answer_type = item.get(
                                "answer_type",
                                "",
                            )

                            if answer_type:
                                st.caption(
                                    "Nearby rendered answer "
                                    f"element: {answer_type}"
                                )

                        else:
                            st.markdown(
                                f"**⚠ {question}**"
                            )

                            st.caption(
                                "No sufficiently clear nearby "
                                "direct-answer signal was detected."
                            )

                else:
                    st.caption(
                        "Direct-answer analysis requires "
                        "question-focused content."
                    )

                # ---------------------------------
                # Answer quality & completeness
                # ---------------------------------

                st.subheader(
                    "Answer Quality & Completeness"
                )

                if result["answer_quality"]:

                    for item in result["answer_quality"]:

                        question = item["question"]
                        quality = item["quality"]
                        score = item["completeness_score"]
                        priority = item["priority"]

                        st.markdown(
                            f"**{question}**"
                        )

                        q1, q2, q3 = st.columns(3)

                        q1.metric(
                            "Answer Quality",
                            quality,
                        )

                        q2.metric(
                            "Completeness",
                            f"{score}/100",
                        )

                        q3.metric(
                            "Answer Words",
                            item["word_count"],
                        )

                        if priority == "HIGH":
                            st.error(
                                f"HIGH — {item['finding']}"
                            )

                        elif priority == "MEDIUM":
                            st.warning(
                                f"MEDIUM — {item['finding']}"
                            )

                        else:
                            st.success(
                                item["finding"]
                            )

                        st.caption(
                            "Recommended SEO Action: "
                            + item["recommendation"]
                        )

                        if item["answer_found"]:
                            answer_type = (
                                item["answer_type"]
                                or "content"
                            )

                            st.caption(
                                "Detected Answer Format: "
                                + answer_type
                            )

                        st.divider()

                else:
                    st.caption(
                        "No question-answer content was "
                        "available for completeness analysis."
                    )

                # ---------------------------------
                # Search intent
                # ---------------------------------

                st.subheader("Search Intent Mapping")

                if result["intent_summary"]:
                    intent_cols = st.columns(
                        len(result["intent_summary"])
                    )

                    for column, item in zip(
                        intent_cols,
                        result["intent_summary"].items(),
                    ):
                        intent, count = item

                        column.metric(
                            intent,
                            count,
                        )

                else:
                    st.caption(
                        "No question-based search intents "
                        "were detected."
                    )

                # ---------------------------------
                # AEO opportunities
                # ---------------------------------

                st.subheader("AEO Opportunities")

                if result["opportunities"]:
                    for opportunity in result["opportunities"]:
                        priority = opportunity["priority"]
                        finding = opportunity["finding"]
                        service = opportunity["service_area"]

                        if priority == "HIGH":
                            st.error(
                                f"HIGH — {finding}"
                            )

                        elif priority == "MEDIUM":
                            st.warning(
                                f"MEDIUM — {finding}"
                            )

                        else:
                            st.info(
                                f"OPPORTUNITY — {finding}"
                            )

                        st.caption(
                            f"Service Area: {service}"
                        )

                else:
                    st.success(
                        "No major AEO content-structure "
                        "opportunities were detected."
                    )

                # ---------------------------------
                # Technical context
                # ---------------------------------

                with st.expander(
                    "Technical Analysis Context"
                ):
                    st.write(
                        f"**Requested URL:** {page.url}"
                    )

                    st.write(
                        f"**Final URL:** {page.final_url}"
                    )

                    st.write(
                        f"**HTTP Status:** {page.status}"
                    )

                    st.write(
                        "**Browser Rendered:** "
                        + (
                            "Yes"
                            if page.browser_rendered
                            else "No"
                        )
                    )

                    st.write(
                        f"**H1:** {len(page.h1 or [])}"
                    )

                    st.write(
                        f"**H2:** {len(page.h2 or [])}"
                    )

                    st.write(
                        f"**H3:** {len(page.h3 or [])}"
                    )

                    schema_text = (
                        ", ".join(page.schema_types)
                        if page.schema_types
                        else "None"
                    )

                    st.write(
                        f"**Schema Types:** {schema_text}"
                    )

        except Exception as exc:
            st.error(
                "AEO Intelligence could not complete "
                "the analysis."
            )

            st.exception(exc)
