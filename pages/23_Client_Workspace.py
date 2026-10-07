from urllib.parse import urlsplit
import streamlit as st
from ui import apply_global_ui
from common import normalize_url
from client_workflow import build_delivery, delivery_files, zip_files, csv_bytes, parse_keyword_csv, KEYWORD_COLUMNS

st.set_page_config(page_title="Client Workspace", page_icon="📁", layout="wide")
apply_global_ui()
st.title("Client Workspace")
st.write("Create a client evidence pack from one audit run, then use the included SEO skill to develop the strategy.")
st.caption("Start with a scoped sample of up to 15 pages. Keyword research and business recommendations need supplied data and human review.")
with st.form("client_scope"):
    website = st.text_input("Website")
    client = st.text_input("Client / project name")
    prepared = st.text_input("Prepared by", value="SEO Audit Suite")
    goal = st.text_input("Business goal", placeholder="Example: more qualified enquiries for a priority service")
    location = st.text_input("Target location / market")
    limit = st.slider("Maximum pages in this sample", 1, 15, 10)
    keywords = st.file_uploader("Optional keyword map CSV", type=['csv'])
    submitted = st.form_submit_button("Build client evidence pack", type="primary")

st.download_button("Download keyword map template", csv_bytes([], KEYWORD_COLUMNS), 'keyword-map-template.csv', 'text/csv')
if submitted:
    try:
        target = normalize_url(website)
        if not target or not urlsplit(target).hostname or urlsplit(target).scheme not in ('http','https'):
            raise ValueError("Enter a valid HTTP or HTTPS website URL.")
        rows = parse_keyword_csv(keywords.getvalue()) if keywords else []
        with st.spinner("Collecting evidence and building client deliverables..."):
            delivery = build_delivery(target, client, prepared, goal, location, limit, rows)
            files = delivery_files(delivery)
        st.session_state['client_delivery'] = delivery
        st.session_state['client_files'] = files
        st.session_state['client_zip'] = zip_files(files)
    except Exception as exc:
        st.error(f"Evidence pack could not be generated: {exc}")

if 'client_delivery' in st.session_state:
    delivery = st.session_state['client_delivery']
    st.subheader("Saved audit run")
    st.write(f"{delivery['model']['website']} · {delivery['model']['generated_at']}")
    st.caption("Downloads below remain tied to this saved run until you successfully build another pack.")
    a, b, c = st.columns(3)
    a.metric("Pages sampled", len(delivery['inventory']))
    b.metric("Evidence issues", len(delivery['issues']))
    c.metric("Keyword rows supplied", len(delivery['keywords']))
    st.info(delivery['model']['scope_note'])
    st.dataframe(delivery['issues'], use_container_width=True, hide_index=True)
    st.download_button("Download complete client pack", st.session_state['client_zip'], 'seo-client-pack.zip', 'application/zip', type='primary')
    for name, data in st.session_state['client_files'].items():
        st.download_button(f"Download {name}", data, name)
    with st.expander("Use the SEO skill with this evidence"):
        st.write("Open this project in Codex and request $seo-client-delivery with the downloaded evidence pack. The skill is bundled in .agents/skills/seo-client-delivery. Other assistants can read SKILL.md and its references as instructions if file access is supported.")
        st.code(delivery['handoff'], language='markdown')
