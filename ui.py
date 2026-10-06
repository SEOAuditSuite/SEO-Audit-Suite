import streamlit as st


def apply_global_ui():
    """Apply the shared V6 visual system without changing audit logic."""
    st.markdown(
        """
        <style>
        :root {
            --v6-bg: #0b0d10;
            --v6-panel: #12161d;
            --v6-panel-2: #171c25;
            --v6-border: rgba(255,255,255,.09);
            --v6-text: #f5f7fb;
            --v6-muted: #9ba6b7;
            --v6-accent: #8b5cf6;
            --v6-accent-2: #22d3ee;
            --v6-good: #34d399;
            --v6-warn: #fbbf24;
        }

        .stApp { background: var(--v6-bg); }
        .block-container { max-width: 1440px; padding-top: 1.8rem; padding-bottom: 3rem; }

        h1, h2, h3 { letter-spacing: -0.02em; }
        h1 { font-weight: 800 !important; }
        h2, h3 { font-weight: 750 !important; }
        p, label, .stCaption, [data-testid="stCaptionContainer"] { color: var(--v6-muted); }

        [data-testid="stSidebar"] {
            background: linear-gradient(180deg, #0f131a 0%, #0b0d10 100%);
            border-right: 1px solid var(--v6-border);
        }
        [data-testid="stSidebar"]::before {
            content: "SEO AUDIT SUITE V6\\A AI SEARCH INTELLIGENCE";
            white-space: pre;
            display: block;
            padding: 1.15rem 1rem .75rem 1rem;
            color: #f8fafc;
            font-weight: 800;
            font-size: .86rem;
            line-height: 1.45;
            letter-spacing: .06em;
        }
        [data-testid="stSidebarNav"] a {
            border-radius: 10px;
            margin: 2px 8px;
            padding-top: .56rem;
            padding-bottom: .56rem;
        }
        [data-testid="stSidebarNav"] a:hover { background: rgba(139,92,246,.12); }
        [data-testid="stSidebarNav"] a[aria-current="page"] {
            background: linear-gradient(90deg, rgba(139,92,246,.20), rgba(34,211,238,.07));
            border: 1px solid rgba(139,92,246,.28);
        }

        [data-testid="stMetric"] {
            background: linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.018));
            border: 1px solid var(--v6-border);
            border-radius: 16px;
            padding: 1rem 1.05rem;
            min-height: 116px;
            box-shadow: 0 10px 26px rgba(0,0,0,.16);
        }
        [data-testid="stMetricLabel"] { color: var(--v6-muted); }
        [data-testid="stMetricValue"] { font-weight: 800; letter-spacing: -.03em; }

        [data-testid="stDataFrame"], [data-testid="stTable"] {
            border: 1px solid var(--v6-border);
            border-radius: 14px;
            overflow: hidden;
        }
        [data-testid="stExpander"] {
            border: 1px solid var(--v6-border);
            border-radius: 14px;
            background: rgba(255,255,255,.02);
        }
        [data-testid="stAlert"] { border-radius: 14px; }

        .stButton > button, .stDownloadButton > button {
            border-radius: 12px;
            min-height: 2.8rem;
            font-weight: 700;
            border: 1px solid rgba(139,92,246,.28);
        }
        .stButton > button[kind="primary"] {
            background: linear-gradient(135deg, #7c3aed, #8b5cf6 55%, #6d5dfc);
            border: none;
            box-shadow: 0 8px 20px rgba(124,58,237,.25);
        }
        .stTextInput input, .stTextArea textarea, [data-baseweb="select"] > div {
            border-radius: 11px !important;
        }
        hr { border-color: var(--v6-border) !important; }

        .v6-hero {
            position: relative;
            overflow: hidden;
            border: 1px solid var(--v6-border);
            border-radius: 24px;
            padding: 30px 32px;
            background:
                radial-gradient(circle at 90% 10%, rgba(34,211,238,.13), transparent 28%),
                radial-gradient(circle at 70% 0%, rgba(139,92,246,.20), transparent 34%),
                linear-gradient(135deg, #121722, #0f131a 65%, #10151f);
            box-shadow: 0 18px 42px rgba(0,0,0,.24);
            margin-bottom: 1.25rem;
        }
        .v6-eyebrow { color: #b9a8ff; font-weight: 800; font-size: .78rem; letter-spacing: .13em; text-transform: uppercase; }
        .v6-hero h1 { margin: .35rem 0 .5rem; font-size: clamp(2.15rem, 4vw, 3.5rem); line-height: 1.03; }
        .v6-hero p { max-width: 850px; font-size: 1.02rem; line-height: 1.65; }
        .v6-pill {
            display: inline-block; margin: .35rem .38rem 0 0; padding: .38rem .7rem;
            border: 1px solid rgba(255,255,255,.10); border-radius: 999px;
            background: rgba(255,255,255,.045); color: #dbe3ef; font-size: .78rem; font-weight: 650;
        }
        .v6-grid { display:grid; grid-template-columns:repeat(3,minmax(0,1fr)); gap:14px; margin: 1rem 0 1.35rem; }
        .v6-card {
            border:1px solid var(--v6-border); border-radius:18px; padding:18px 18px 17px;
            background:linear-gradient(180deg, rgba(255,255,255,.035), rgba(255,255,255,.018));
            min-height:152px; box-shadow:0 10px 26px rgba(0,0,0,.13);
        }
        .v6-card .icon { font-size:1.35rem; }
        .v6-card h3 { margin:.45rem 0 .3rem; font-size:1.02rem; }
        .v6-card p { margin:0; font-size:.88rem; line-height:1.55; }
        .v6-section-label { color:#a78bfa; font-weight:800; letter-spacing:.08em; text-transform:uppercase; font-size:.74rem; margin-top:1.1rem; }
        .v6-status { display:inline-flex; align-items:center; gap:.45rem; color:#c8f7e5; background:rgba(52,211,153,.08); border:1px solid rgba(52,211,153,.22); border-radius:999px; padding:.38rem .68rem; font-size:.78rem; font-weight:700; }
        .v6-dot { width:7px; height:7px; border-radius:50%; background:#34d399; box-shadow:0 0 12px rgba(52,211,153,.8); }
        @media (max-width: 900px) { .v6-grid { grid-template-columns:1fr; } .v6-hero { padding:24px 22px; } }
        </style>
        """,
        unsafe_allow_html=True,
    )
