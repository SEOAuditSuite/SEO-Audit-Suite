import streamlit as st
import pandas as pd

st.title("📈 Google Search Performance")
st.caption("Actual Google Search Console performance data can be viewed here. This is separate from the SEO Audit Suite score.")
st.info("Google does not provide a single official 0–100 SEO score. This page is for Search Console performance metrics such as clicks, impressions, CTR and average position.")

file=st.file_uploader("Upload a Google Search Console Performance export (CSV)",type=["csv"])
if file:
    try:
        df=pd.read_csv(file)
        st.success(f"Loaded {len(df):,} rows.")
        st.dataframe(df.head(100),use_container_width=True,hide_index=True)
        numeric={c.lower().strip():c for c in df.columns}
        cols=st.columns(4)
        def pick(name): return numeric.get(name)

        clicks_col = pick("clicks")
        impressions_col = pick("impressions")
        ctr_col = pick("ctr")
        position_col = pick("position")

        def to_number(series):
            # Handles both numeric CSV fields and values such as "3.44%".
            return pd.to_numeric(
                series.astype(str).str.replace("%", "", regex=False).str.replace(",", "", regex=False).str.strip(),
                errors="coerce"
            )

        clicks = to_number(df[clicks_col]).fillna(0) if clicks_col else pd.Series(dtype=float)
        impressions = to_number(df[impressions_col]).fillna(0) if impressions_col else pd.Series(dtype=float)

        total_clicks = clicks.sum() if clicks_col else None
        total_impressions = impressions.sum() if impressions_col else None

        # Aggregate CTR is total clicks / total impressions, not the arithmetic
        # mean of row-level CTR values. This matches the standard CTR definition.
        aggregate_ctr = (total_clicks / total_impressions * 100) if total_impressions else None

        # Average position is impression-weighted when impressions are available.
        aggregate_position = None
        if position_col:
            positions = to_number(df[position_col])
            valid = positions.notna() & impressions.gt(0) if impressions_col else positions.notna()
            if valid.any():
                if impressions_col and impressions[valid].sum() > 0:
                    aggregate_position = (positions[valid] * impressions[valid]).sum() / impressions[valid].sum()
                else:
                    aggregate_position = positions[valid].mean()

        values = [total_clicks, total_impressions, aggregate_ctr, aggregate_position]
        labels = ["Clicks", "Impressions", "CTR", "Position"]
        formats = ["{:,.2f}", "{:,.2f}", "{:.2f}%", "{:.2f}"]
        for col, label, value, fmt in zip(cols, labels, values, formats):
            if value is not None:
                col.metric(label, fmt.format(value))

        st.caption("Search Console export formats vary. Clicks and impressions are summed; CTR is calculated as total clicks ÷ total impressions; position is impression-weighted when impressions are available. These metrics are separate from the SEO audit score.")
    except Exception as exc:
        st.error(f"Could not read the CSV: {exc}")
else:
    st.write("For now, export the relevant Performance report from Google Search Console as CSV and upload it here. Direct OAuth/API connection can be added later without changing the audit-score definitions.")
