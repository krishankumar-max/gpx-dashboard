"""
Sidebar filter component.

Returns a FilterState dataclass that the main app uses to slice data.
Filters are cascading:
  - Partner list uses full dataset
  - Offer list changes based on date range + partner
  - Goal list changes based on date range + partner + offer
"""

import datetime as dt
from dataclasses import dataclass, field

import pandas as pd
import streamlit as st


@dataclass
class FilterState:
    from_date: dt.date
    to_date: dt.date
    partners: list[str]
    offers: list[str]
    goals: list[str]


def render_filters(df: pd.DataFrame) -> FilterState:
    """
    Render sidebar filters and return the current FilterState.
    *df* is the full daily_summary DataFrame.
    """
    st.sidebar.header("🔍 Filters")

    # ── Date range ────────────────────────────────────────────────────────────
    all_dates = sorted(df["date"].unique()) if not df.empty else []
    min_date = all_dates[0] if all_dates else dt.date.today() - dt.timedelta(days=7)
    max_date = all_dates[-1] if all_dates else dt.date.today()

    st.sidebar.subheader("Date Range")
    from_date: dt.date = st.sidebar.date_input(
        "From Date",
        value=max_date - dt.timedelta(days=6),
        min_value=min_date,
        max_value=max_date,
        key="from_date",
    )  # type: ignore[assignment]

    to_date: dt.date = st.sidebar.date_input(
        "To Date",
        value=max_date,
        min_value=min_date,
        max_value=max_date,
        key="to_date",
    )  # type: ignore[assignment]

    if from_date > to_date:
        st.sidebar.error("From Date must be ≤ To Date.")
        from_date = to_date

    # Slice by date first — used for cascading
    date_filtered = df[
        (df["date"] >= from_date) & (df["date"] <= to_date)
    ]

    # ── Partner ───────────────────────────────────────────────────────────────
    st.sidebar.subheader("Partner")
    all_partners = sorted(date_filtered["partner"].dropna().unique().tolist())
    selected_partners: list[str] = st.sidebar.multiselect(
        "Partner",
        options=all_partners,
        default=[],
        placeholder="All partners",
        key="partner_filter",
        label_visibility="collapsed",
    )

    partner_filtered = (
        date_filtered[date_filtered["partner"].isin(selected_partners)]
        if selected_partners
        else date_filtered
    )

    # ── Offer ─────────────────────────────────────────────────────────────────
    st.sidebar.subheader("Offer")
    all_offers = sorted(partner_filtered["offerName"].dropna().unique().tolist())
    selected_offers: list[str] = st.sidebar.multiselect(
        "Offer",
        options=all_offers,
        default=[],
        placeholder="All offers",
        key="offer_filter",
        label_visibility="collapsed",
    )

    offer_filtered = (
        partner_filtered[partner_filtered["offerName"].isin(selected_offers)]
        if selected_offers
        else partner_filtered
    )

    # ── Goal ──────────────────────────────────────────────────────────────────
    st.sidebar.subheader("Goal")
    all_goals = sorted(offer_filtered["goal"].dropna().unique().tolist())
    selected_goals: list[str] = st.sidebar.multiselect(
        "Goal",
        options=all_goals,
        default=[],
        placeholder="All goals",
        key="goal_filter",
        label_visibility="collapsed",
    )

    st.sidebar.divider()
    st.sidebar.caption(
        f"Data available: {min_date} → {max_date}\n\n"
        f"Showing: {from_date} → {to_date}"
    )

    return FilterState(
        from_date=from_date,
        to_date=to_date,
        partners=selected_partners,
        offers=selected_offers,
        goals=selected_goals,
    )


def apply_filters(df: pd.DataFrame, filters: FilterState) -> pd.DataFrame:
    """Apply a FilterState to a DataFrame and return the sliced result."""
    mask = (df["date"] >= filters.from_date) & (df["date"] <= filters.to_date)

    if filters.partners:
        mask &= df["partner"].isin(filters.partners)
    if filters.offers:
        mask &= df["offerName"].isin(filters.offers)
    if filters.goals:
        mask &= df["goal"].isin(filters.goals)

    return df[mask].copy()
