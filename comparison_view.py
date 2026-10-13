"""Presentation only: retain the original bounded comparison evidence unchanged."""
import json


def _entry(value):
    if not isinstance(value, str):
        return str(value)
    try:
        link = json.loads(value)
    except (ValueError, TypeError):
        return value
    if isinstance(link, dict) and 'url' in link and 'anchor' in link:
        rel = ', '.join(str(v) for v in link.get('rel', [])) or 'none'
        return f"{link['anchor'] or '(empty anchor)'} → {link['url']} (rel: {rel})"
    return value


def readable_value(value):
    """Format field snapshots or added/removed lists without changing semantics."""
    try:
        data = json.loads(value)
    except (ValueError, TypeError):
        return 'Evidence could not be formatted; inspect structured evidence.'
    if isinstance(data, dict) and isinstance(data.get('values'), list):
        summary = f"{data.get('count', len(data['values']))} observed entries"
        if 'characters' in data:
            summary += f"; {data['characters']} text characters"
        if data.get('truncated'):
            summary += '; extraction truncated — not fully assessed'
        if data.get('excerpt_shortened'):
            summary += '; excerpt shortened'
        return summary + '\n' + ('\n'.join(_entry(v) for v in data['values']) or '(None observed in this snapshot)')
    if isinstance(data, list):
        return '\n'.join(_entry(v) for v in data) or '(No entry-level difference recorded)'
    return 'Evidence could not be formatted; inspect structured evidence.'


def readable_rows(rows):
    return [{**row, **{key: readable_value(row[key]) for key in ('Raw', 'Rendered', 'Added', 'Removed')}} for row in rows]


def show_comparison(result):
    import streamlit as st
    st.caption('Observed snapshot differences only. Missing content under replay restrictions is not proof of a website defect. Repeated entries retain their occurrence counts.')
    st.dataframe(readable_rows(result['rows']), use_container_width=True, hide_index=True)
    with st.expander('Structured comparison evidence'):
        st.json(result['rows'])
