from collections import Counter

import streamlit as st

from ui import apply_global_ui

from common import crawl_site, word_tokens

st.title("🔑 Keywords, Headings & Content")
st.caption(
    "Analyzes browser-rendered page content. Keyword density is descriptive "
    "and is not a ranking recommendation."
)

url = st.text_input(
    "Website URL",
    placeholder="https://example.com",
)

if st.button("Analyze", type="primary"):
    crawl = crawl_site(
        url,
        limit=1,
        prefer_browser=True,
    )

    if not crawl["pages"]:
        st.error("Could not render the page.")
        st.stop()

    page = crawl["pages"][0]

    if page.browser_rendered:
        st.success("✓ Browser-rendered DOM analyzed")
    elif crawl.get("browser_error"):
        st.warning(
            "Browser rendering was unavailable, so the request-based "
            "HTML fallback was analyzed."
        )

    # Use the same rendered body text and tokenization as the shared crawler.
    # This keeps the content count aligned with Complete Audit instead of
    # falling back to the initial/non-rendered HTML response.
    words = word_tokens(page.body_text)

    stop_words = set(
        "the and for are but not you your with this that from have has was "
        "were into about can will our their they http https www com page "
        "home more here where what when which who how a an to of in on at "
        "by as is it or be we us".split()
    )

    keyword_counts = Counter(
        word
        for word in words
        if word not in stop_words
    )

    analyzed_word_count = len(words)

    st.subheader("Page Content Signals")

    metrics = st.columns(4)
    metrics[0].metric(
        "Analyzed words",
        analyzed_word_count,
    )
    metrics[1].metric(
        "H1 tags",
        len(page.h1),
    )
    metrics[2].metric(
        "H2 tags",
        len(page.h2),
    )
    metrics[3].metric(
        "H3 tags",
        len(page.h3),
    )

    st.write("**Title:**", page.title or "Missing")

    st.subheader("Heading Structure")

    heading_rows = []

    for level, values in (
        ("H1", page.h1),
        ("H2", page.h2),
        ("H3", page.h3),
    ):
        for position, text in enumerate(values, start=1):
            heading_rows.append(
                {
                    "Heading": level,
                    "Position": position,
                    "Text": text,
                }
            )

    if heading_rows:
        st.dataframe(
            heading_rows,
            use_container_width=True,
            hide_index=True,
        )
    else:
        st.info("No H1-H3 headings were detected in the rendered DOM.")

    st.subheader("Keyword Frequency")

    if keyword_counts and analyzed_word_count:
        keyword_rows = [
            {
                "Keyword": keyword,
                "Count": count,
                "Approx. density": (
                    f"{(count / analyzed_word_count) * 100:.2f}%"
                ),
            }
            for keyword, count in keyword_counts.most_common(30)
        ]

        st.dataframe(
            keyword_rows,
            use_container_width=True,
            hide_index=True,
        )

        st.caption(
            "Approx. density = keyword occurrences ÷ all analyzed rendered "
            "word tokens. Stop words are excluded from the keyword list, "
            "but not from the density denominator."
        )
    else:
        st.info("No meaningful rendered text was available for keyword analysis.")
