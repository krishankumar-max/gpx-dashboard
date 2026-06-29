"""
KPI card row component.

Renders 6 metric tiles across the top of the dashboard:
  Revenue | Payout | Margin | Conversions | Valid Conversions | Valid %
"""

import pandas as pd
import streamlit as st


def render_kpis(df: pd.DataFrame) -> None:
    """
    Render KPI cards from a *filtered* summary DataFrame.
    Expects columns: revenue, payout, conversions, valid_conversions.
    """
    if df.empty:
        st.info("No data for the selected filters.")
        return

    revenue = df["revenue"].sum()
    payout = df["payout"].sum()
    margin = revenue - payout
    conversions = int(df["conversions"].sum())
    valid_conversions = int(df["valid_conversions"].sum())
    valid_pct = (valid_conversions / conversions * 100) if conversions > 0 else 0.0

    # Margin colour: green if positive, red if negative
    margin_delta = f"{'↑' if margin >= 0 else '↓'} {abs(margin):,.2f}"

    col1, col2, col3, col4, col5, col6 = st.columns(6)

    with col1:
        st.metric(
            label="💰 Revenue",
            value=f"${revenue:,.2f}",
        )
    with col2:
        st.metric(
            label="💸 Payout",
            value=f"${payout:,.2f}",
        )
    with col3:
        st.metric(
            label="📈 Margin",
            value=f"${margin:,.2f}",
            delta=margin_delta,
            delta_color="normal",
        )
    with col4:
        st.metric(
            label="🔁 Conversions",
            value=f"{conversions:,}",
        )
    with col5:
        st.metric(
            label="✅ Valid Conv.",
            value=f"{valid_conversions:,}",
        )
    with col6:
        st.metric(
            label="📊 Valid %",
            value=f"{valid_pct:.1f}%",
        )
