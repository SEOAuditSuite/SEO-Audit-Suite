import re
from collections import Counter


QUESTION_STARTERS = (
    "what", "why", "how", "when", "where", "who",
    "which", "can", "could", "should", "is", "are",
    "do", "does", "will"
)


def clean_text(text):
    """Normalize whitespace and return clean readable text."""
    if not text:
        return ""

    return re.sub(r"\s+", " ", str(text)).strip()

def body_text_to_segments(body_text):
    """
    Convert V5 rendered body text into smaller analysis-friendly
    segments while filtering obvious navigation/UI noise.
    """
    text = clean_text(body_text)

    if not text:
        return []

    sentences = re.split(r"(?<=[.!?])\s+", text)

    segments = []

    noise_phrases = (
        "select your order type",
        "please select your location",
        "use current location",
        "please select city",
        "change location",
    )

    for sentence in sentences:
        sentence = clean_text(sentence)

        if not sentence:
            continue

        lower_sentence = sentence.lower()

        if any(
            noise in lower_sentence
            for noise in noise_phrases
        ):
            continue

        word_count = len(
            re.findall(r"\b\w+\b", sentence)
        )

        # Ignore tiny UI/navigation fragments
        if word_count < 5:
            continue

        # Avoid treating giant merged page sections
        # as concise direct answers.
        if word_count > 80:
            continue

        segments.append(sentence)

    return segments


def is_question(text):
    """Detect whether a text string looks like a question."""
    text = clean_text(text)

    if not text:
        return False

    lower = text.lower()

    if text.endswith("?"):
        return True

    return any(
        lower.startswith(starter + " ")
        for starter in QUESTION_STARTERS
    )


def discover_questions(headings, paragraphs):
    """
    Discover explicit and question-style content from headings
    and paragraph text.
    """
    questions = []

    for item in headings:
        text = clean_text(item)

        if is_question(text):
            questions.append(text)

    for paragraph in paragraphs:
        paragraph = clean_text(paragraph)

        if not paragraph:
            continue

        sentences = re.split(r"(?<=[?.!])\s+", paragraph)

        for sentence in sentences:
            sentence = clean_text(sentence)

            if is_question(sentence):
                questions.append(sentence)

    return list(dict.fromkeys(questions))


def detect_direct_answers(questions, paragraphs):
    """
    Detect whether a discovered question has a separate,
    concise and relevant answer-like text segment.

    The question itself is never counted as its own answer.
    """

    results = []

    clean_paragraphs = [
        clean_text(p)
        for p in paragraphs
        if clean_text(p)
    ]

    for question in questions:

        normalized_question = clean_text(question).lower().rstrip("?")

        question_words = {
            word.lower()
            for word in re.findall(r"\b[a-zA-Z]{3,}\b", question)
            if word.lower() not in QUESTION_STARTERS
        }

        best_answer = ""
        best_score = 0

        for paragraph in clean_paragraphs:

            normalized_paragraph = (
                clean_text(paragraph)
                .lower()
                .rstrip("?")
            )

            # Never allow the question itself
            # to become its own answer.
            if normalized_paragraph == normalized_question:
                continue

            # A direct answer should normally contain
            # meaningful explanatory text.
            word_count = len(
                re.findall(r"\b\w+\b", paragraph)
            )

            if word_count < 5:
                continue

            if len(paragraph) > 600:
                continue

            paragraph_words = {
                word.lower()
                for word in re.findall(
                    r"\b[a-zA-Z]{3,}\b",
                    paragraph,
                )
            }

            overlap = len(
                question_words.intersection(
                    paragraph_words
                )
            )

            # Require stronger relevance than before.
            if overlap >= 2 and overlap > best_score:
                best_score = overlap
                best_answer = paragraph

        results.append(
            {
                "question": question,
                "answer_found": bool(best_answer),
                "answer": best_answer,
            }
        )

    return results


def detect_content_formats(lists, tables):
    """Analyze answer-friendly structured content using V5 audit counts."""

    list_count = lists if isinstance(lists, int) else len(lists or [])
    table_count = tables if isinstance(tables, int) else len(tables or [])

    return {
        "lists_found": list_count,
        "tables_found": table_count,
        "has_lists": list_count > 0,
        "has_tables": table_count > 0,
    }


def detect_intents(questions):
    """Classify discovered questions into simple search-intent groups."""
    intents = []

    for question in questions:
        q = question.lower().strip()

        if q.startswith(("how ", "how do", "how can")):
            intent = "How-to"

        elif q.startswith(("what ", "who ", "where ", "when ", "why ")):
            intent = "Informational"

        elif any(
            word in q
            for word in (
                "best", "compare", "vs", "versus",
                "price", "cost", "buy", "order"
            )
        ):
            intent = "Commercial"

        else:
            intent = "General Question"

        intents.append(
            {
                "question": question,
                "intent": intent,
            }
        )

    return intents


def calculate_aeo_score(
    questions,
    direct_answers,
    formats,
    faq_present=False,
):
    """
    Calculate an application-defined AEO readiness score.
    This is not an official search-engine or AI-platform score.
    """
    score = 0

    # Question targeting — 25 points
    if len(questions) >= 5:
        score += 25
    elif len(questions) >= 3:
        score += 20
    elif len(questions) >= 1:
        score += 12

    # Direct answers — 35 points
    if direct_answers:
        answered = sum(
            1 for item in direct_answers
            if item["answer_found"]
        )

        answer_ratio = answered / len(direct_answers)
        score += round(answer_ratio * 35)

    # Structured answer formats — 20 points
    if formats["has_lists"]:
        score += 10

    if formats["has_tables"]:
        score += 10

    # FAQ signals — 20 points
    if faq_present:
        score += 20

    return min(score, 100)


def build_opportunities(
    questions,
    direct_answers,
    formats,
    faq_present=False,
):
    """Generate service-oriented AEO improvement opportunities."""
    opportunities = []

    if not questions:
        opportunities.append(
            {
                "priority": "HIGH",
                "finding": "No clear question-focused content detected.",
                "service_area": "AEO Content Strategy",
            }
        )

    unanswered = [
        item["question"]
        for item in direct_answers
        if not item["answer_found"]
    ]

    if unanswered:
        opportunities.append(
            {
                "priority": "HIGH",
                "finding": (
                    f"{len(unanswered)} detected question(s) "
                    "lack a clear answer signal."
                ),
                "service_area": "Direct Answer Optimization",
            }
        )

    if not faq_present:
        opportunities.append(
            {
                "priority": "MEDIUM",
                "finding": "No strong FAQ signal detected.",
                "service_area": "FAQ & Answer Optimization",
            }
        )

    if not formats["has_lists"]:
        opportunities.append(
            {
                "priority": "OPPORTUNITY",
                "finding": "No answer-friendly list structure detected.",
                "service_area": "Content Structure Optimization",
            }
        )

    if not formats["has_tables"]:
        opportunities.append(
            {
                "priority": "OPPORTUNITY",
                "finding": "No tabular answer format detected.",
                "service_area": "Structured Content Optimization",
            }
        )

    return opportunities


def run_aeo_analysis(
    headings,
    paragraphs,
    lists,
    tables,
    faq_present=False,
):
    """Run the complete AEO Intelligence 2.0 analysis pipeline."""

    questions = discover_questions(headings, paragraphs)

    direct_answers = detect_direct_answers(
        questions,
        paragraphs,
    )

    formats = detect_content_formats(
        lists,
        tables,
    )

    intents = detect_intents(
        questions,
    )

    score = calculate_aeo_score(
        questions,
        direct_answers,
        formats,
        faq_present,
    )

    opportunities = build_opportunities(
        questions,
        direct_answers,
        formats,
        faq_present,
    )

    intent_counts = Counter(
        item["intent"]
        for item in intents
    )

    return {
        "score": score,
        "questions": questions,
        "question_count": len(questions),
        "direct_answers": direct_answers,
        "formats": formats,
        "intents": intents,
        "intent_summary": dict(intent_counts),
        "faq_present": faq_present,
        "opportunities": opportunities,
    }

def analyze_answer_completeness(direct_answers):
    """
    Evaluate the quality and completeness of DOM-verified answers.

    This is an application-defined AEO heuristic and is not an
    official search-engine or AI-platform quality score.
    """

    analysis = []

    for item in direct_answers:
        question = clean_text(
            item.get("question", "")
        )

        answer = clean_text(
            item.get("answer", "")
        )

        answer_found = bool(
            item.get("answer_found")
        )

        answer_type = item.get(
            "answer_type",
            ""
        )

        # ---------------------------------
        # No verified nearby answer
        # ---------------------------------

        if not answer_found or not answer:
            analysis.append(
                {
                    "question": question,
                    "answer_found": False,
                    "answer": "",
                    "answer_type": "",
                    "word_count": 0,
                    "quality": "Weak",
                    "completeness_score": 0,
                    "finding": (
                        "No clear nearby direct answer "
                        "was detected."
                    ),
                    "recommendation": (
                        "Add a concise explanatory answer "
                        "immediately after the question."
                    ),
                    "priority": "HIGH",
                }
            )

            continue

        # ---------------------------------
        # Analyze verified answer
        # ---------------------------------

        words = re.findall(
            r"\b[\w'-]+\b",
            answer,
            flags=re.UNICODE,
        )

        word_count = len(words)

        score = 0

        # Useful answer length — max 45
        if 20 <= word_count <= 80:
            score += 45
        elif 10 <= word_count < 20:
            score += 32
        elif 5 <= word_count < 10:
            score += 18
        elif 80 < word_count <= 120:
            score += 32
        elif word_count > 120:
            score += 18

        # Answer format — max 25
        if answer_type == "paragraph":
            score += 25
        elif answer_type == "list":
            score += 25
        elif answer_type == "content block":
            score += 18
        else:
            score += 10

        # Explanatory signal — max 20
        explanatory_signals = (
            "because",
            "means",
            "includes",
            "offers",
            "provides",
            "helps",
            "allows",
            "known for",
            "designed to",
            "used for",
        )

        lower_answer = answer.lower()

        if any(
            signal in lower_answer
            for signal in explanatory_signals
        ):
            score += 20
        elif word_count >= 15:
            score += 12
        elif word_count >= 8:
            score += 6

        # Readability / concision — max 10
        if 8 <= word_count <= 80:
            score += 10
        elif word_count <= 120:
            score += 5

        score = min(score, 100)

        # ---------------------------------
        # Quality classification
        # ---------------------------------

        if score >= 80:
            quality = "Strong"
            priority = "OPPORTUNITY"
            finding = (
                "A clear and well-structured direct "
                "answer was detected."
            )
            recommendation = (
                "Maintain the concise answer structure "
                "and strengthen it where useful with "
                "supporting detail or structured data."
            )

        elif score >= 55:
            quality = "Moderate"
            priority = "MEDIUM"
            finding = (
                "A direct answer was detected, but its "
                "completeness could be improved."
            )
            recommendation = (
                "Improve clarity, completeness and "
                "answer-first formatting."
            )

        else:
            quality = "Weak"
            priority = "HIGH"
            finding = (
                "A nearby answer exists, but it is not "
                "strong enough as a concise direct answer."
            )
            recommendation = (
                "Rewrite the response as a clear, concise "
                "and self-contained answer."
            )

        analysis.append(
            {
                "question": question,
                "answer_found": True,
                "answer": answer,
                "answer_type": answer_type,
                "word_count": word_count,
                "quality": quality,
                "completeness_score": score,
                "finding": finding,
                "recommendation": recommendation,
                "priority": priority,
            }
        )

    return analysis


def calculate_aeo_score_v2(
    questions,
    direct_answers,
    answer_quality,
    formats,
    faq_present=False,
    schema_types=None,
):
    """
    Calculate the SEO Audit Suite Pro AEO Readiness Score 2.0.

    This is an application-defined heuristic score designed to
    evaluate answer-engine readiness signals. It is not an official
    Google, OpenAI, Bing, Perplexity or other platform ranking score.

    Score areas:
        Question Targeting          20 points
        Direct Answer Coverage      25 points
        Answer Quality              20 points
        FAQ Readiness               15 points
        Answer-Friendly Structure   10 points
        Structured Data             10 points

    Total                          100 points
    """

    schema_types = schema_types or []

    questions = questions or []
    direct_answers = direct_answers or []
    answer_quality = answer_quality or []

    # ---------------------------------
    # 1. Question targeting — 20 points
    # ---------------------------------

    question_count = len(questions)

    if question_count >= 5:
        question_score = 20

    elif question_count >= 3:
        question_score = 16

    elif question_count >= 2:
        question_score = 12

    elif question_count == 1:
        question_score = 8

    else:
        question_score = 0

    # ---------------------------------
    # 2. Direct answer coverage
    #    — 25 points
    # ---------------------------------

    if question_count > 0:

        answered_count = sum(
            1
            for item in direct_answers
            if item.get("answer_found")
        )

        answer_coverage_ratio = min(
            answered_count / question_count,
            1.0,
        )

        direct_answer_score = round(
            answer_coverage_ratio * 25
        )

    else:
        answered_count = 0
        answer_coverage_ratio = 0
        direct_answer_score = 0

    # ---------------------------------
    # 3. Answer quality — 20 points
    # ---------------------------------

    quality_scores = [
        item.get("completeness_score", 0)
        for item in answer_quality
    ]

    if quality_scores:

        average_quality = (
            sum(quality_scores)
            / len(quality_scores)
        )

        answer_quality_score = round(
            (average_quality / 100) * 20
        )

    else:
        average_quality = 0
        answer_quality_score = 0

    # ---------------------------------
    # 4. FAQ readiness — 15 points
    # ---------------------------------

    normalized_schema_types = {
        str(schema_type).lower()
        for schema_type in schema_types
    }

    faq_schema_present = (
        "faqpage" in normalized_schema_types
    )

    if faq_present and faq_schema_present:
        faq_score = 15

    elif faq_present:
        faq_score = 10

    elif faq_schema_present:
        faq_score = 8

    else:
        faq_score = 0

    # ---------------------------------
    # 5. Answer-friendly structure
    #    — 10 points
    # ---------------------------------

    structure_score = 0

    if formats.get("has_lists"):
        structure_score += 5

    if formats.get("has_tables"):
        structure_score += 5

    # ---------------------------------
    # 6. Structured data — 10 points
    # ---------------------------------

    useful_schema_types = {
        "faqpage",
        "howto",
        "article",
        "newsarticle",
        "blogposting",
        "product",
        "organization",
        "localbusiness",
        "website",
        "webpage",
    }

    detected_useful_schema = (
        normalized_schema_types
        .intersection(useful_schema_types)
    )

    if len(detected_useful_schema) >= 3:
        structured_data_score = 10

    elif len(detected_useful_schema) == 2:
        structured_data_score = 7

    elif len(detected_useful_schema) == 1:
        structured_data_score = 4

    else:
        structured_data_score = 0

    # ---------------------------------
    # Final score
    # ---------------------------------

    total_score = (
        question_score
        + direct_answer_score
        + answer_quality_score
        + faq_score
        + structure_score
        + structured_data_score
    )

    total_score = min(
        round(total_score),
        100,
    )

    # ---------------------------------
    # Readiness classification
    # ---------------------------------

    if total_score >= 80:
        readiness = "Strong"

    elif total_score >= 60:
        readiness = "Good"

    elif total_score >= 40:
        readiness = "Developing"

    else:
        readiness = "Weak"

    # ---------------------------------
    # Return score + evidence breakdown
    # ---------------------------------

    return {
        "score": total_score,
        "readiness": readiness,

        "breakdown": {
            "question_targeting": {
                "score": question_score,
                "max_score": 20,
            },

            "direct_answer_coverage": {
                "score": direct_answer_score,
                "max_score": 25,
            },

            "answer_quality": {
                "score": answer_quality_score,
                "max_score": 20,
            },

            "faq_readiness": {
                "score": faq_score,
                "max_score": 15,
            },

            "answer_friendly_structure": {
                "score": structure_score,
                "max_score": 10,
            },

            "structured_data": {
                "score": structured_data_score,
                "max_score": 10,
            },
        },

        "evidence": {
            "questions_found": question_count,
            "answers_found": answered_count,
            "answer_coverage_percent": round(
                answer_coverage_ratio * 100
            ),
            "average_answer_quality": round(
                average_quality
            ),
            "faq_signal": bool(faq_present),
            "faq_schema": faq_schema_present,
            "lists_found": formats.get(
                "lists_found",
                0,
            ),
            "tables_found": formats.get(
                "tables_found",
                0,
            ),
            "useful_schema_types": sorted(
                detected_useful_schema
            ),
        },
    }