"""
Habits: spending pattern analysis with flexible time period selector.
"""

from datetime import date, timedelta

import plotly.express as px
import streamlit as st

import db.queries as queries

st.title("Spending Habits")

# ---------------------------------------------------------------------------
# Time period selector
# ---------------------------------------------------------------------------
today = date.today()

col_period, col_group = st.columns([3, 1])

with col_period:
    period = st.radio(
        "Period",
        ["Last 30 Days", "Last 3 Months", "Last 6 Months", "Last 12 Months", "This Year", "Custom"],
        index=2,
        horizontal=True,
        key="habits_period",
    )

if period == "Last 30 Days":
    from_date = str(today - timedelta(days=30))
    to_date = str(today)
    default_group = "day"
elif period == "Last 3 Months":
    from_date = str(today - timedelta(days=91))
    to_date = str(today)
    default_group = "week"
elif period == "Last 6 Months":
    from_date = str(today - timedelta(days=182))
    to_date = str(today)
    default_group = "month"
elif period == "Last 12 Months":
    from_date = str(today - timedelta(days=365))
    to_date = str(today)
    default_group = "month"
elif period == "This Year":
    from_date = f"{today.year}-01-01"
    to_date = str(today)
    default_group = "month"
else:  # Custom
    c1, c2 = st.columns(2)
    from_date = str(c1.date_input("From", value=today - timedelta(days=90), key="habits_from"))
    to_date = str(c2.date_input("To", value=today, key="habits_to"))
    default_group = "week"

with col_group:
    group_by = st.selectbox(
        "Group by",
        ["day", "week", "month"],
        index=["day", "week", "month"].index(default_group),
        key="habits_group",
    )

# ---------------------------------------------------------------------------
# Bank filter
# ---------------------------------------------------------------------------
accounts_df = queries.get_accounts()
if not accounts_df.empty:
    selected_accounts = st.multiselect(
        "Banks / Accounts",
        options=accounts_df["account_id"].tolist(),
        default=accounts_df["account_id"].tolist(),
        format_func=lambda aid: accounts_df.loc[accounts_df["account_id"] == aid, "bank_name"].values[0],
        key="habits_banks",
    )
else:
    selected_accounts = []

# ---------------------------------------------------------------------------
# Category spend trend
# ---------------------------------------------------------------------------
st.subheader(f"Spend Trend — {period}")
trend_df = queries.get_trend_for_period(from_date, to_date, group_by=group_by)
if not trend_df.empty:
    fig = px.line(
        trend_df,
        x="period",
        y="total",
        color="category",
        markers=True,
        labels={"period": group_by.capitalize(), "total": "Spend (£)", "category": "Category"},
    )
    fig.update_layout(margin=dict(t=10, b=10, l=10, r=10))
    st.plotly_chart(fig, use_container_width=True)
else:
    st.info("Not enough transaction data for this period.")

# ---------------------------------------------------------------------------
# Top merchants bar + category donut + merchant donut
# ---------------------------------------------------------------------------
col_left, col_mid, col_right = st.columns(3)

with col_left:
    st.subheader("Top 10 Merchants")
    merch_df = queries.get_top_merchants_for_period(from_date, to_date, limit=10)
    if not merch_df.empty:
        fig2 = px.bar(
            merch_df,
            x="total",
            y="merchant",
            orientation="h",
            labels={"total": "Spend (£)", "merchant": ""},
        )
        fig2.update_layout(yaxis={"categoryorder": "total ascending"}, margin=dict(t=10, b=10))
        st.plotly_chart(fig2, use_container_width=True)
    else:
        st.info("No merchant data for this period.")

with col_mid:
    st.subheader("Category Breakdown")
    cat_df = queries.get_category_totals_for_period(from_date, to_date)
    if not cat_df.empty:
        fig3 = px.pie(cat_df, names="category", values="total", hole=0.4)
        fig3.update_traces(textposition="inside", textinfo="percent+label")
        fig3.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig3, use_container_width=True)
    else:
        st.info("No category data for this period.")

with col_right:
    st.subheader("Merchant Breakdown")
    if not merch_df.empty:
        fig4 = px.pie(merch_df, names="merchant", values="total", hole=0.4)
        fig4.update_traces(textposition="inside", textinfo="percent+label")
        fig4.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
        st.plotly_chart(fig4, use_container_width=True)
    else:
        st.info("No merchant data for this period.")

# ---------------------------------------------------------------------------
# Day-of-week average spend
# ---------------------------------------------------------------------------
st.subheader("Average Spend by Day of Week (all time)")
dow_df = queries.get_day_of_week_spend()
if not dow_df.empty:
    fig4 = px.bar(
        dow_df,
        x="day_of_week",
        y="avg_spend",
        labels={"day_of_week": "Day", "avg_spend": "Average Spend (£)"},
        category_orders={"day_of_week": ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]},
    )
    fig4.update_layout(margin=dict(t=10, b=10))
    st.plotly_chart(fig4, use_container_width=True)
else:
    st.info("Not enough data for day-of-week analysis.")
