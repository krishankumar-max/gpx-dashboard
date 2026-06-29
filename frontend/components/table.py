"""
Raw data table component.

Loads raw Parquet files for the filtered date range (not the aggregated
summary) so the user sees row-level detail.

Features:
- Column search / sort via st.dataframe
- CSV download button
- Pagination controls (configurable rows per page)
"""

import datetime as dt
import io

import pandas as pd
import streamlit as st

from backend.storage import load_date_range
from frontend.components.filters import FilterState


# Columns to display in the detail table
_DISPLAY_COLS = [
    "time",
    "partner",
    "offerName",
    "goal",
    "revenue",
    "payout",
    "valid",
    "partnerValid",
    "errors",
    "country",
    "city",
]


def _load_raw(filters: FilterState) -> pd.DataFrame:
    """Load raw rows for the filtered date range."""
    df = load_date_range(filters.from_date, filters.to_date)

    if df.empty:
        return df

    # Apply partner / offer / goal filters
    if filters.partners:
        df = df[df["partner"].isin(filters.partners)]
    if filters.offers:
        df = df[df["offerName"].isin(filters.offers)]
    if filters.goals:
        df = df[df["goal"].isin(filters.goals)]

    # Keep only display columns that actually exist
    cols = [c for c in _DISPLAY_COLS if c in df.columns]
    df = df[cols].copy()

    # Format errors list as a readable string
    if "errors" in df.columns:
        df["errors"] = df["errors"].apply(
            lambda v: ", ".join(v) if isinstance(v, list) and v else ""
        )

    # Format booleans as Yes/No for readability
    for col in ("valid", "partnerValid"):
        if col in df.columns:
            df[col] = df[col].map({True: "✅", False: "❌", None: "—"})

    # Parse time to a nicer format
    if "time" in df.columns:
        df["time"] = pd.to_datetime(df["time"], errors="coerce").dt.strftime(
            "%Y-%m-%d %H:%M:%S"
        )

    return df.reset_index(drop=True)


def render_raw_table(filters: FilterState) -> None:
    """Render the searchable raw data table with a CSV download button."""
    st.subheader("📋 Raw Data")

    with st.spinner("Loading raw data…"):
        df = _load_raw(filters)

    if df.empty:
        st.info("No raw data available for the selected filters.")
        return

    # ── Row count info ────────────────────────────────────────────────────────
    total_rows = len(df)
    st.caption(f"{total_rows:,} rows matching current filters.")

    # ── Search / filter ───────────────────────────────────────────────────────
    search_term = st.text_input(
        "🔎 Search in table",
        placeholder="Type to filter any column…",
        key="raw_table_search",
    )
    if search_term:
        mask = df.apply(
            lambda col: col.astype(str).str.contains(search_term, case=False, na=False)
        ).any(axis=1)
        df = df[mask]
        st.caption(f"{len(df):,} rows after search.")

    # ── Pagination ────────────────────────────────────────────────────────────
    rows_per_page = st.selectbox(
        "Rows per page",
        options=[100, 250, 500, 1000],
        index=0,
        key="rows_per_page",
    )
    total_pages = max(1, (len(df) - 1) // rows_per_page + 1)
    page = st.number_input(
        f"Page (1 – {total_pages})",
        min_value=1,
        max_value=total_pages,
        value=1,
        step=1,
        key="raw_table_page",
    )
    start = (page - 1) * rows_per_page
    page_df = df.iloc[start : start + rows_per_page]

    # ── Display ───────────────────────────────────────────────────────────────
    st.dataframe(
        page_df,
        use_container_width=True,
        height=500,
    )

    # ── CSV download ──────────────────────────────────────────────────────────
    csv_buffer = io.StringIO()
    df.to_csv(csv_buffer, index=False)
    st.download_button(
        label="⬇️ Download CSV (filtered)",
        data=csv_buffer.getvalue().encode("utf-8"),
        file_name=(
            f"sapphyre_postbacks_"
            f"{filters.from_date.isoformat()}_to_{filters.to_date.isoformat()}.csv"
        ),
        mime="text/csv",
    )
