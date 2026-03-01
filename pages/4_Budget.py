"""
Budget: multiple income sources, fixed outgoings, savings goals, category spend limits.
"""

from datetime import date

import streamlit as st

import db.queries as queries
from db.queries import PREDEFINED_CATEGORIES

st.title("Budget")

today = date.today()
year_month = f"{today.year}-{today.month:02d}"

# ---------------------------------------------------------------------------
# Summary strip at the top
# ---------------------------------------------------------------------------
total_income = queries.get_total_monthly_income()
total_fixed = queries.get_total_monthly_outgoings()
total_savings = queries.get_total_monthly_savings_contribution()
disposable = total_income - total_fixed - total_savings
summary = queries.get_monthly_summary(year_month)
actual_spend = summary["spend"]
remaining = disposable - actual_spend

c1, c2, c3, c4, c5 = st.columns(5)
c1.metric("Monthly Income", f"£{total_income:,.2f}", help="Sum of all active income sources")
c2.metric("Fixed Outgoings", f"£{total_fixed:,.2f}", help="Sum of all active fixed expenses")
c3.metric("Savings set aside", f"£{total_savings:,.2f}", help="Sum of savings goal contributions")
c4.metric("Disposable", f"£{disposable:,.2f}", help="Income − outgoings − savings")
c5.metric(
    "Remaining this month",
    f"£{max(remaining, 0):,.2f}",
    delta=f"£{remaining:,.2f}",
    delta_color="normal",
)

st.markdown("---")

# ---------------------------------------------------------------------------
# Three-column layout: Income | Fixed Outgoings | Savings Goals
# ---------------------------------------------------------------------------
col_inc, col_out, col_sav = st.columns(3)

FREQ_LABELS = {
    "daily":   "/ day",
    "weekly":  "/ week",
    "monthly": "/ month",
    "yearly":  "/ year",
}
FREQ_TO_MONTHLY = {
    "daily":   365 / 12,
    "weekly":  52 / 12,
    "monthly": 1,
    "yearly":  1 / 12,
}

# ── Income Sources ──────────────────────────────────────────────────────────
with col_inc:
    st.subheader("Income Sources")
    income_df = queries.get_income_sources()

    if not income_df.empty:
        for _, row in income_df.iterrows():
            freq = row.get("frequency") or "monthly"
            monthly_equiv = float(row["amount"]) * FREQ_TO_MONTHLY.get(freq, 1)
            r1, r2, r3 = st.columns([3, 3, 1])
            r1.write(f"**{row['name']}**")
            freq_label = FREQ_LABELS.get(freq, "/ month")
            equiv_str = f" (£{monthly_equiv:,.2f}/mo)" if freq != "monthly" else ""
            r2.write(f"£{row['amount']:,.2f} {freq_label}{equiv_str}")
            if r3.button("✕", key=f"del_inc_{row['id']}", help="Remove"):
                queries.delete_income_source(int(row["id"]))
                st.rerun()
    else:
        st.caption("No income sources yet.")

    st.markdown(f"**Total: £{total_income:,.2f} / month**")

    with st.form("add_income_form"):
        st.caption("Add income source")
        inc_name   = st.text_input("Name", placeholder="e.g. Salary, Freelance")
        inc_freq   = st.selectbox(
            "Frequency",
            options=["daily", "weekly", "monthly", "yearly"],
            index=2,
            format_func=lambda f: f.capitalize(),
            key="inc_freq",
        )
        inc_amount = st.number_input(
            f"Amount (£ per {inc_freq})", min_value=0.01, step=50.0, key="inc_amt"
        )
        if st.form_submit_button("Add"):
            if inc_name.strip():
                queries.add_income_source(inc_name.strip(), inc_amount, inc_freq)
                st.rerun()
            else:
                st.warning("Name required.")

# ── Fixed Outgoings ─────────────────────────────────────────────────────────
with col_out:
    st.subheader("Fixed Outgoings")
    outgoing_df = queries.get_fixed_outgoings()

    if not outgoing_df.empty:
        for _, row in outgoing_df.iterrows():
            r1, r2, r3 = st.columns([3, 2, 1])
            label = f"**{row['name']}**"
            if row.get("category"):
                label += f" _{row['category']}_"
            r1.markdown(label)
            r2.write(f"£{row['amount']:,.2f} / mo")
            if r3.button("✕", key=f"del_out_{row['id']}", help="Remove"):
                queries.delete_fixed_outgoing(int(row["id"]))
                st.rerun()
    else:
        st.caption("No fixed outgoings yet.")

    st.markdown(f"**Total: £{total_fixed:,.2f} / month**")

    with st.form("add_outgoing_form"):
        st.caption("Add fixed outgoing")
        out_name = st.text_input("Name", placeholder="e.g. Rent, Netflix, Gym")
        out_amount = st.number_input("Monthly amount (£)", min_value=0.01, step=10.0, key="out_amt")
        out_cat = st.selectbox("Category (optional)", [""] + PREDEFINED_CATEGORIES, key="out_cat")
        if st.form_submit_button("Add"):
            if out_name.strip():
                queries.add_fixed_outgoing(out_name.strip(), out_amount, out_cat)
                st.rerun()
            else:
                st.warning("Name required.")

# ── Savings Goals ────────────────────────────────────────────────────────────
with col_sav:
    st.subheader("Savings Goals")
    goals_df = queries.get_savings_goals()

    if not goals_df.empty:
        for _, g in goals_df.iterrows():
            target = float(g["target_amount"])
            current = float(g["current_amount"])
            contribution = float(g["monthly_contribution"])
            pct = min(current / target, 1.0) if target > 0 else 0
            months_left = (
                int((target - current) / contribution)
                if contribution > 0 and current < target else None
            )

            g_col1, g_col2 = st.columns([4, 1])
            g_col1.markdown(
                f'<span style="display:inline-block;width:10px;height:10px;border-radius:50%;'
                f'background:{g["color"]};vertical-align:middle;margin-right:6px;"></span>'
                f'**{g["name"]}**',
                unsafe_allow_html=True,
            )
            if g_col2.button("✕", key=f"del_goal_{g['id']}", help="Archive goal"):
                queries.delete_savings_goal(int(g["id"]))
                st.rerun()

            st.progress(pct, text=f"£{current:,.0f} / £{target:,.0f} ({pct*100:.0f}%)")
            extra = f"  ·  ~{months_left}m to go" if months_left else ""
            st.caption(f"Saving £{contribution:,.0f}/mo{extra}")

            # Quick "add money" button
            with st.popover(f"Update saved amount"):
                with st.form(f"update_goal_{g['id']}"):
                    new_current = st.number_input(
                        "Amount saved so far (£)",
                        min_value=0.0,
                        max_value=float(target),
                        value=current,
                        step=10.0,
                    )
                    if st.form_submit_button("Save"):
                        queries.update_savings_goal(
                            int(g["id"]),
                            name=g["name"],
                            target_amount=target,
                            monthly_contribution=contribution,
                            current_amount=new_current,
                            deadline=g.get("deadline"),
                            color=g["color"],
                        )
                        st.rerun()
            st.markdown("")
    else:
        st.caption("No savings goals yet.")

    st.markdown(f"**Total saving: £{total_savings:,.2f} / month**")

    with st.form("add_goal_form"):
        st.caption("Add savings goal")
        g_name = st.text_input("Goal name", placeholder="e.g. Holiday, Emergency fund")
        g_target = st.number_input("Target amount (£)", min_value=1.0, step=100.0, key="g_target")
        g_contribution = st.number_input("Monthly contribution (£)", min_value=0.0, step=10.0, key="g_contrib")
        g_current = st.number_input("Already saved (£)", min_value=0.0, step=10.0, key="g_current")
        g_deadline = st.date_input("Target date (optional)", value=None, key="g_deadline")
        g_color = st.color_picker("Colour", value="#4A90D9", key="g_color")
        if st.form_submit_button("Add Goal"):
            if g_name.strip():
                queries.add_savings_goal(
                    g_name.strip(),
                    g_target,
                    g_contribution,
                    g_current,
                    str(g_deadline) if g_deadline else None,
                    g_color,
                )
                st.rerun()
            else:
                st.warning("Goal name required.")

# ---------------------------------------------------------------------------
# Category spend limits
# ---------------------------------------------------------------------------
st.markdown("---")

month_col, _ = st.columns([2, 4])
with month_col:
    budget_month = st.selectbox(
        "Month for category budgets",
        options=[f"{today.year}-{m:02d}" for m in range(today.month, 0, -1)],
        index=0,
        key="budget_month_sel",
    )

st.subheader(f"Category Budgets — {budget_month}")
queries.get_or_create_budget_month(budget_month)
budget_vs_actual = queries.get_budget_vs_actual(budget_month)

if not budget_vs_actual.empty:
    for _, row in budget_vs_actual.iterrows():
        limit = float(row["spend_limit"])
        actual = float(row["actual_spend"])
        pct = min(actual / limit, 1.0) if limit > 0 else 0.0
        over = actual > limit

        bc1, bc2, bc3 = st.columns([2, 4, 1])
        bc1.write(f"**{row['category']}**")
        bc1.caption(f"£{actual:,.2f} / £{limit:,.2f}")
        bar_text = f"{'⚠️ OVER  ' if over else ''}£{actual:.2f} / £{limit:.2f}"
        bc2.progress(pct, text=bar_text)
        if bc3.button("✕", key=f"del_bcat_{budget_month}_{row['category']}", help="Remove"):
            conn = queries.get_connection()
            with conn:
                conn.execute(
                    "DELETE FROM budget_categories WHERE year_month = ? AND category = ?",
                    (budget_month, row["category"]),
                )
            conn.close()
            st.rerun()
else:
    st.info("No category budgets set for this month. Add one below.")

with st.form("add_cat_budget"):
    st.caption("Add / update a category spend limit")
    bc1, bc2, bc3 = st.columns([3, 2, 1])
    cat_options = queries.get_distinct_categories()
    cat = bc1.selectbox("Category", cat_options if cat_options else PREDEFINED_CATEGORIES)
    limit_val = bc2.number_input("Limit (£)", min_value=0.01, step=10.0)
    if bc3.form_submit_button("Add"):
        if cat:
            queries.set_category_budget(budget_month, cat, limit_val)
            st.rerun()
