"""
Overview: all-in-one dashboard.
Tabs: Summary | Debts | Shared Transactions
"""

from datetime import date, timedelta

import plotly.express as px
import streamlit as st

import db.queries as queries

st.title("Overview")

today = date.today()
year_month = f"{today.year}-{today.month:02d}"

tab_summary, tab_debts = st.tabs(["Summary", "Debts & Shared"])

# ============================================================================
# TAB 1 — SUMMARY
# ============================================================================
with tab_summary:

    # ── Sync strip ───────────────────────────────────────────────────────────
    sync_col, status_col = st.columns([1, 4])
    if sync_col.button("Sync now", type="primary", use_container_width=True):
        with st.spinner("Syncing…"):
            from sync.scheduler import trigger_manual_sync
            result = trigger_manual_sync()
        if "error" in result:
            st.error(f"Sync failed: {result['error']}")
        else:
            st.success(f"Done — {result['rows_upserted']} rows upserted.")
        st.rerun()

    from db.queries import get_last_sync
    last = get_last_sync()
    if last:
        status_col.caption(
            f"Last sync: {last['finished_at']}  ·  "
            f"{last['rows_upserted']} rows  ·  status: {last['status']}"
            + (f"  ·  ⚠ {last['error_message']}" if last.get("error_message") else "")
        )
    else:
        status_col.caption("No sync yet.")

    st.markdown("---")

    # ── Period selector ──────────────────────────────────────────────────────
    period = st.radio(
        "View period",
        ["Day", "Week", "Month", "Year"],
        index=2,
        horizontal=True,
        key="overview_period",
    )

    if period == "Day":
        from_date, to_date, group_by = str(today), str(today), "day"
        period_label = f"Today ({today.strftime('%d %b')})"
    elif period == "Week":
        week_start = today - timedelta(days=today.weekday())
        from_date = str(week_start)
        to_date, group_by = str(today), "day"
        period_label = f"Week of {week_start.strftime('%d %b')}"
    elif period == "Month":
        from_date = f"{today.year}-{today.month:02d}-01"
        to_date, group_by = str(today), "day"
        period_label = today.strftime("%B %Y")
    else:
        from_date = f"{today.year}-01-01"
        to_date, group_by = str(today), "month"
        period_label = str(today.year)

    # ── Bank filter ──────────────────────────────────────────────────────────
    accounts_df = queries.get_accounts()
    account_ids_filter = None

    if not accounts_df.empty:
        with st.expander("Filter by bank / account", expanded=False):
            cols = st.columns(min(len(accounts_df), 4))
            selected_ids = []
            for i, (_, acc) in enumerate(accounts_df.iterrows()):
                col = cols[i % len(cols)]
                col.markdown(
                    f'<span style="display:inline-block;width:100%;height:3px;border-radius:2px;'
                    f'background:{acc["bank_color"]};margin-bottom:4px;"></span>',
                    unsafe_allow_html=True,
                )
                if col.checkbox(acc["bank_name"], value=True, key=f"ov_acc_{acc['account_id']}"):
                    selected_ids.append(acc["account_id"])
            account_ids_filter = selected_ids or None

    # ── Spending capacity — all four windows ─────────────────────────────────
    cap = queries.get_all_spending_capacities()

    st.markdown("---")
    st.subheader("What You Can Spend")

    if cap["has_income"]:
        c1, c2, c3, c4 = st.columns(4)

        def _signed(value: float) -> str:
            return f"-£{abs(value):,.2f}" if value < 0 else f"£{value:,.2f}"

        def _cap_col(col, label, remaining, allowance, spend):
            actual = allowance - spend  # unclamped — can be negative
            col.metric(label, f"£{remaining:,.2f}", delta=_signed(actual), delta_color="normal")
            if allowance > 0:
                col.progress(
                    min(spend / allowance, 1.0),
                    text=f"£{spend:,.2f} / £{allowance:,.2f}",
                )

        _cap_col(c1, "Today",      cap["today"], cap["daily_allowance"],   cap["today_spend"])
        _cap_col(c2, "This Week",  cap["week"],  cap["weekly_allowance"],  cap["week_spend"])
        _cap_col(c3, "This Month", cap["month"], cap["monthly_allowance"], cap["month_spend"])
        _cap_col(c4, "This Year",  cap["year"],  cap["yearly_allowance"],  cap["year_spend"])

        period_spend   = {"Day": cap["today_spend"], "Week": cap["week_spend"],
                          "Month": cap["month_spend"], "Year": cap["year_spend"]}[period]
        period_allow   = {"Day": cap["daily_allowance"], "Week": cap["weekly_allowance"],
                          "Month": cap["monthly_allowance"], "Year": cap["yearly_allowance"]}[period]

        if period_spend > period_allow > 0:
            st.warning(
                f"You've spent **£{period_spend - period_allow:,.2f} over** your "
                f"{period_label.lower()} allowance."
            )
            st.page_link("pages/2_Transactions.py", label="Review transactions →", icon="💳")
    else:
        st.info("Set up your income on the **Budget** page to see spending targets.")
        st.page_link("pages/4_Budget.py", label="Set up income & goals →", icon="🎯")

    # ── Period KPIs ──────────────────────────────────────────────────────────
    st.markdown("---")
    summary = queries.get_summary_for_period(from_date, to_date)

    k1, k2, k3, k4 = st.columns(4)
    net = summary["net"]
    net_str = f"-£{abs(net):,.2f}" if net < 0 else f"£{net:,.2f}"
    k1.metric(f"Spent ({period_label})",  f"£{summary['spend']:,.2f}")
    k2.metric(f"Income ({period_label})", f"£{summary['income']:,.2f}")
    k3.metric("Net", net_str, delta=net_str, delta_color="normal")
    k4.metric(
        "Monthly savings contributions",
        f"£{queries.get_total_monthly_savings_contribution():,.2f}",
        help="Sum of all active savings goal contributions",
    )

    # ── Charts ───────────────────────────────────────────────────────────────
    st.markdown("---")
    col_left, col_right = st.columns(2)

    with col_left:
        h1, h2 = st.columns([3, 1])
        h1.subheader(f"Top Merchants — {period_label}")
        h2.page_link("pages/3_Habits.py", label="Full analysis →")
        merch_df = queries.get_top_merchants_for_period(from_date, to_date, limit=10)
        if not merch_df.empty:
            fig = px.pie(merch_df, names="merchant", values="total", hole=0.45)
            fig.update_traces(textposition="inside", textinfo="percent+label")
            fig.update_layout(showlegend=False, margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig, use_container_width=True)
        else:
            st.info("No spend data for this period.")

    with col_right:
        h1, h2 = st.columns([3, 1])
        h1.subheader(f"Spend Trend — {period_label}")
        h2.page_link("pages/3_Habits.py", label="Full analysis →")
        trend_df = queries.get_trend_for_period(from_date, to_date, group_by=group_by)
        if not trend_df.empty:
            import pandas as pd
            if group_by == "day":
                trend_df["period"] = pd.to_datetime(trend_df["period"]).dt.strftime("%a %d")
            elif group_by == "month":
                trend_df["period"] = pd.to_datetime(trend_df["period"] + "-01").dt.strftime("%b %Y")
            fig2 = px.bar(
                trend_df, x="period", y="total", color="category", barmode="stack",
                labels={"period": "", "total": "Spend (£)", "category": "Category"},
            )
            fig2.update_layout(margin=dict(t=10, b=10, l=10, r=10))
            st.plotly_chart(fig2, use_container_width=True)
        else:
            st.info("Not enough data for trend chart.")

    # ── Recent transactions ───────────────────────────────────────────────────
    st.markdown("---")
    h1, h2 = st.columns([3, 1])
    h1.subheader("Recent Transactions")
    h2.page_link("pages/2_Transactions.py", label="See all →")

    txn_df = queries.get_transactions(
        from_date=from_date, to_date=to_date, account_ids=account_ids_filter
    )
    if not txn_df.empty:
        display = txn_df[["timestamp", "description", "merchant_name", "amount", "category", "bank_name"]].head(15).copy()
        display["timestamp"] = display["timestamp"].str[:10]
        st.dataframe(
            display, use_container_width=True, hide_index=True,
            column_config={
                "amount":    st.column_config.NumberColumn("Amount", format="£%.2f"),
                "bank_name": st.column_config.TextColumn("Bank"),
            },
        )
    else:
        st.info("No transactions for this period.")

    # ── Savings goals snapshot ────────────────────────────────────────────────
    st.markdown("---")
    h1, h2 = st.columns([3, 1])
    h1.subheader("Savings Goals")
    h2.page_link("pages/4_Budget.py", label="Manage →")

    goals_df = queries.get_savings_goals()
    if not goals_df.empty:
        g_cols = st.columns(min(len(goals_df), 3))
        for i, (_, g) in enumerate(goals_df.iterrows()):
            pct = (
                min(float(g["current_amount"]) / float(g["target_amount"]), 1.0)
                if g["target_amount"] > 0 else 0.0
            )
            with g_cols[i % len(g_cols)]:
                st.markdown(
                    f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
                    f'background:{g["color"]};vertical-align:middle;margin-right:6px;"></span>'
                    f'**{g["name"]}**',
                    unsafe_allow_html=True,
                )
                st.progress(pct, text=f'£{g["current_amount"]:,.0f} / £{g["target_amount"]:,.0f}')
                st.caption(f'£{g["monthly_contribution"]:,.0f}/mo contribution')
    else:
        st.info("No savings goals set.")
        st.page_link("pages/4_Budget.py", label="Add a goal →")


# ============================================================================
# TAB 2 — DEBTS & SHARED TRANSACTIONS
# ============================================================================
with tab_debts:

    debts_df   = queries.get_debts(include_settled=False)
    splits_df  = queries.get_shared_splits(settled_filter="unsettled")

    # Outstanding shared-split totals (always money others owe you)
    shared_total = float(splits_df["their_share_amount"].sum()) if not splits_df.empty else 0.0

    they_owe_debts = (
        debts_df[debts_df["direction"] == "they_owe"] if not debts_df.empty else debts_df
    )
    i_owe_debts = (
        debts_df[debts_df["direction"] == "i_owe"] if not debts_df.empty else debts_df
    )
    they_owe_total = float(they_owe_debts["amount"].sum()) if not they_owe_debts.empty else 0.0
    i_owe_total    = float(i_owe_debts["amount"].sum())    if not i_owe_debts.empty    else 0.0

    # Top-line summary
    s1, s2, s3 = st.columns(3)
    s1.metric("They owe me (debts)",   f"£{they_owe_total:,.2f}")
    s2.metric("They owe me (splits)",  f"£{shared_total:,.2f}")
    s3.metric("I owe them",            f"£{i_owe_total:,.2f}")

    st.divider()

    # ── Two-column layout ────────────────────────────────────────────────────
    col_they, col_i = st.columns(2)

    # ── LEFT: They Owe Me (debts + splits) ───────────────────────────────────
    with col_they:
        st.subheader(f"They Owe Me  —  £{they_owe_total + shared_total:,.2f}")

        # Manual debts
        if not they_owe_debts.empty:
            st.caption("Manual debts")
            for _, row in they_owe_debts.iterrows():
                c1, c2, c3 = st.columns([3, 2, 1])
                desc = f" — {row['description']}" if row.get("description") else ""
                c1.write(f"**{row['person_name']}**{desc}")
                c2.write(f"£{row['amount']:,.2f}")
                if c3.button("Settle", key=f"settle_debt_{row['id']}"):
                    queries.settle_debt(int(row["id"]))
                    st.rerun()

        # Shared splits
        if not splits_df.empty:
            st.caption("Shared transaction splits")
            for _, sp in splits_df.iterrows():
                c1, c2, c3 = st.columns([3, 3, 1])
                label = sp["description"] or sp["merchant_name"] or sp["transaction_id"]
                c1.write(f"**{sp['person_name']}** — {str(sp['timestamp'])[:10]}")
                c2.write(f"{sp['their_share_pct']:.0f}% of {label[:24]}… = £{sp['their_share_amount']:.2f}")
                if c3.button("Settle", key=f"settle_split_{sp['id']}"):
                    queries.settle_shared_split(int(sp["id"]))
                    st.rerun()

        if they_owe_debts.empty and splits_df.empty:
            st.caption("Nothing outstanding.")

        # Add manual debt form
        st.markdown("")
        with st.form("add_they_owe"):
            st.caption("Add manual debt — they owe me")
            p = st.text_input("Person",               key="they_person")
            a = st.number_input("Amount (£)", min_value=0.01, step=0.01, key="they_amount")
            d = st.text_input("Description (optional)", key="they_desc")
            if st.form_submit_button("Add debt"):
                if p and a:
                    queries.add_debt("they_owe", p.strip(), a, d.strip())
                    st.rerun()
                else:
                    st.warning("Name and amount required.")

        # Add shared split
        st.markdown("")
        st.caption("Add shared transaction split")
        all_txns = queries.get_transactions(direction="outgoing")
        if not all_txns.empty:
            txn_options: dict[str, str] = {}
            for _, r in all_txns.head(200).iterrows():
                lbl = (
                    f"{str(r['timestamp'])[:10]}  "
                    f"{r['description'] or r['merchant_name'] or ''}  "
                    f"£{abs(r['amount']):.2f}"
                )
                txn_options[lbl] = r["transaction_id"]

            sel_lbl   = st.selectbox("Transaction", list(txn_options.keys()), key="shared_txn_sel")
            sel_txn_id = txn_options[sel_lbl]
            sel_row   = all_txns[all_txns["transaction_id"] == sel_txn_id].iloc[0]
            txn_amt   = abs(float(sel_row["amount"]))

            sp_person = st.text_input("Who are you splitting with?", placeholder="e.g. Alice", key="shared_person")
            sp_mode   = st.radio("Enter as", ["Percentage", "Fixed amount"], horizontal=True, key="shared_mode")

            if sp_mode == "Percentage":
                sp_pct    = st.slider("Their share (%)", 1, 99, 50, key="shared_pct")
                sp_amount = txn_amt * sp_pct / 100
            else:
                sp_amount = st.number_input(
                    "Their share (£)", min_value=0.01,
                    max_value=float(txn_amt) if txn_amt > 0 else 1.0,
                    value=round(txn_amt / 2, 2), step=0.01, key="shared_amt",
                )
                sp_pct = (sp_amount / txn_amt * 100) if txn_amt > 0 else 0

            st.metric("They owe you", f"£{sp_amount:.2f}", delta=f"{sp_pct:.1f}%")

            if st.button("Add split", type="primary", key="shared_add"):
                if sp_person.strip():
                    queries.update_transaction(sel_txn_id, is_shared=True)
                    queries.add_shared_split(sel_txn_id, sp_person.strip(), sp_pct, sp_amount)
                    st.success(f"{sp_person.strip()} owes £{sp_amount:.2f}")
                    st.rerun()
                else:
                    st.warning("Enter a person's name.")
        else:
            st.caption("No outgoing transactions — sync first.")

    # ── RIGHT: I Owe Them ─────────────────────────────────────────────────────
    with col_i:
        st.subheader(f"I Owe Them  —  £{i_owe_total:,.2f}")

        if not i_owe_debts.empty:
            for _, row in i_owe_debts.iterrows():
                c1, c2, c3 = st.columns([3, 2, 1])
                desc = f" — {row['description']}" if row.get("description") else ""
                c1.write(f"**{row['person_name']}**{desc}")
                c2.write(f"£{row['amount']:,.2f}")
                if c3.button("Settle", key=f"settle_iowe_{row['id']}"):
                    queries.settle_debt(int(row["id"]))
                    st.rerun()
        else:
            st.caption("Nothing outstanding.")

        st.markdown("")
        with st.form("add_i_owe"):
            st.caption("Add debt — I owe them")
            p = st.text_input("Person",               key="i_person")
            a = st.number_input("Amount (£)", min_value=0.01, step=0.01, key="i_amount")
            d = st.text_input("Description (optional)", key="i_desc")
            if st.form_submit_button("Add debt"):
                if p and a:
                    queries.add_debt("i_owe", p.strip(), a, d.strip())
                    st.rerun()
                else:
                    st.warning("Name and amount required.")

    # ── Settled history ───────────────────────────────────────────────────────
    st.divider()
    with st.expander("Settled history"):
        hist_col1, hist_col2 = st.columns(2)

        with hist_col1:
            st.caption("Debts")
            all_debts = queries.get_debts(include_settled=True)
            if not all_debts.empty:
                settled_debts = all_debts[all_debts["is_settled"] == 1]
                if not settled_debts.empty:
                    d = settled_debts[["person_name", "direction", "amount", "description", "settled_at"]].copy()
                    d["amount"] = d["amount"].map(lambda x: f"£{x:,.2f}")
                    st.dataframe(d, use_container_width=True, hide_index=True)
                else:
                    st.caption("None yet.")
            else:
                st.caption("None yet.")

        with hist_col2:
            st.caption("Splits")
            all_splits = queries.get_shared_splits(settled_filter="settled")
            if not all_splits.empty:
                s = all_splits[["person_name", "timestamp", "description", "their_share_amount", "settled_at"]].copy()
                s["timestamp"] = s["timestamp"].str[:10]
                s["their_share_amount"] = s["their_share_amount"].map(lambda x: f"£{x:.2f}")
                st.dataframe(s, use_container_width=True, hide_index=True)
            else:
                st.caption("None yet.")
