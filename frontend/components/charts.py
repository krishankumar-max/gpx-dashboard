"""
Plotly chart components for the analytics dashboard.

Charts rendered:
1. Revenue Trend (line chart by date)
2. Top Offers by Revenue (horizontal bar)
3. Top Goals by Revenue (horizontal bar)
4. Valid vs Invalid Conversions (donut chart)
5. Revenue by Advertiser (treemap / bar)
"""

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import streamlit as st

# ── Shared theme ──────────────────────────────────────────────────────────────
_TEMPLATE = "plotly_dark"
_COLORS = px.colors.qualitative.Bold
_HEIGHT = 380


def _no_data_msg(title: str) -> None:
    st.info(f"No data available for: **{title}**")


# ── 1. Revenue Trend ──────────────────────────────────────────────────────────

def render_revenue_trend(df: pd.DataFrame) -> None:
    """Daily revenue line chart."""
    if df.empty:
        _no_data_msg("Revenue Trend")
        return

    daily = (
        df.groupby("date", as_index=False)
        .agg(revenue=("revenue", "sum"), payout=("payout", "sum"))
        .sort_values("date")
    )
    daily["margin"] = daily["revenue"] - daily["payout"]

    fig = go.Figure()
    fig.add_trace(go.Scatter(
        x=daily["date"].astype(str),
        y=daily["revenue"],
        mode="lines+markers",
        name="Revenue",
        line=dict(color="#00CC96", width=2),
        marker=dict(size=6),
    ))
    fig.add_trace(go.Scatter(
        x=daily["date"].astype(str),
        y=daily["payout"],
        mode="lines+markers",
        name="Payout",
        line=dict(color="#EF553B", width=2, dash="dot"),
        marker=dict(size=6),
    ))
    fig.add_trace(go.Scatter(
        x=daily["date"].astype(str),
        y=daily["margin"],
        mode="lines+markers",
        name="Margin",
        line=dict(color="#636EFA", width=2, dash="dash"),
        marker=dict(size=6),
    ))

    fig.update_layout(
        title="Revenue, Payout & Margin Trend",
        xaxis_title="Date",
        yaxis_title="Amount ($)",
        template=_TEMPLATE,
        height=_HEIGHT,
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1),
        hovermode="x unified",
    )
    st.plotly_chart(fig, use_container_width=True)


# ── 2. Top Offers by Revenue ──────────────────────────────────────────────────

def render_top_offers(df: pd.DataFrame, top_n: int = 15) -> None:
    """Horizontal bar chart of top N offers by revenue."""
    if df.empty:
        _no_data_msg("Top Offers")
        return

    top = (
        df.groupby("offerName", as_index=False)
        .agg(revenue=("revenue", "sum"))
        .nlargest(top_n, "revenue")
        .sort_values("revenue")
    )

    fig = px.bar(
        top,
        x="revenue",
        y="offerName",
        orientation="h",
        title=f"Top {top_n} Offers by Revenue",
        labels={"revenue": "Revenue ($)", "offerName": "Offer"},
        color="revenue",
        color_continuous_scale="Tealgrn",
        template=_TEMPLATE,
        height=max(_HEIGHT, top_n * 26),
        text_auto=".2s",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(coloraxis_showscale=False, yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)


# ── 3. Top Goals by Revenue ───────────────────────────────────────────────────

def render_top_goals(df: pd.DataFrame, top_n: int = 15) -> None:
    """Horizontal bar chart of top N goals by revenue."""
    if df.empty:
        _no_data_msg("Top Goals")
        return

    top = (
        df.groupby("goal", as_index=False)
        .agg(revenue=("revenue", "sum"))
        .nlargest(top_n, "revenue")
        .sort_values("revenue")
    )

    fig = px.bar(
        top,
        x="revenue",
        y="goal",
        orientation="h",
        title=f"Top {top_n} Goals by Revenue",
        labels={"revenue": "Revenue ($)", "goal": "Goal"},
        color="revenue",
        color_continuous_scale="Purp",
        template=_TEMPLATE,
        height=max(_HEIGHT, top_n * 26),
        text_auto=".2s",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(coloraxis_showscale=False, yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)


# ── 4. Valid vs Invalid Conversions ──────────────────────────────────────────

def render_valid_vs_invalid(df: pd.DataFrame) -> None:
    """Donut chart showing valid vs invalid conversion split."""
    if df.empty:
        _no_data_msg("Valid vs Invalid")
        return

    total = int(df["conversions"].sum())
    valid = int(df["valid_conversions"].sum())
    invalid = total - valid

    if total == 0:
        _no_data_msg("Valid vs Invalid (zero conversions)")
        return

    fig = go.Figure(data=[go.Pie(
        labels=["Valid", "Invalid"],
        values=[valid, invalid],
        hole=0.55,
        marker=dict(colors=["#00CC96", "#EF553B"]),
        textinfo="label+percent+value",
        hovertemplate="%{label}: %{value:,} (%{percent})<extra></extra>",
    )])
    fig.update_layout(
        title="Valid vs Invalid Conversions",
        template=_TEMPLATE,
        height=_HEIGHT,
        showlegend=True,
        annotations=[dict(
            text=f"{valid/total*100:.1f}%<br>Valid",
            x=0.5, y=0.5,
            font_size=16,
            showarrow=False,
        )],
    )
    st.plotly_chart(fig, use_container_width=True)


# ── 5. Revenue by Advertiser ──────────────────────────────────────────────────

def render_revenue_by_advertiser(df: pd.DataFrame, top_n: int = 10) -> None:
    """
    Treemap of revenue broken down by partner → advertiser.
    Falls back to a bar chart if the 'advertiserName' column is missing in
    the aggregated table (it's not always present).
    """
    # The agg table groups by partner/offerName/goal — use offerName as proxy
    if df.empty:
        _no_data_msg("Revenue by Partner")
        return

    by_partner = (
        df.groupby("partner", as_index=False)
        .agg(revenue=("revenue", "sum"), conversions=("conversions", "sum"))
        .nlargest(top_n, "revenue")
        .sort_values("revenue")
    )

    fig = px.bar(
        by_partner,
        x="revenue",
        y="partner",
        orientation="h",
        title=f"Top {top_n} Partners by Revenue",
        labels={"revenue": "Revenue ($)", "partner": "Partner"},
        color="revenue",
        color_continuous_scale="Blues",
        template=_TEMPLATE,
        height=max(_HEIGHT, top_n * 28),
        text_auto=".2s",
    )
    fig.update_traces(textposition="outside")
    fig.update_layout(coloraxis_showscale=False, yaxis_title="")
    st.plotly_chart(fig, use_container_width=True)
