"""
Transactions: filterable + sortable table with multi-select bulk edit,
click-to-edit single row, and persistent sort/filter state.
"""

from datetime import date, timedelta

import streamlit as st

import db.queries as queries
from db.queries import PREDEFINED_CATEGORIES

st.title("Transactions")


def all_category_options() -> list[str]:
    db_cats = queries.get_distinct_categories()
    merged = list(PREDEFINED_CATEGORIES)
    for c in db_cats:
        if c not in merged:
            merged.append(c)
    return merged


# ---------------------------------------------------------------------------
# Filters
# ---------------------------------------------------------------------------
today = date.today()
accounts_df = queries.get_accounts()

with st.expander("Filters", expanded=True):
    col_from, col_to, col_cat, col_bank, col_search = st.columns([2, 2, 2, 2, 3])

    from_date = col_from.date_input("From", value=today - timedelta(days=30), key="txn_from")
    to_date   = col_to.date_input("To",   value=today, key="txn_to")

    cat_opts = ["All"] + all_category_options()
    category = col_cat.selectbox("Category", cat_opts, key="txn_cat")

    # ── Bank / Account ───────────────────────────────────────────────────────
    if not accounts_df.empty:
        bank_options: dict[str, list | None] = {"All banks & accounts": None}
        for _, acc in accounts_df.iterrows():
            label = f"{acc['bank_name']}  —  {acc['account_name']}"
            bank_options[label] = [acc["account_id"]]

        selected_bank_label = col_bank.selectbox(
            "Bank / Account", list(bank_options.keys()), key="txn_bank"
        )
        account_ids_filter = bank_options[selected_bank_label]

        if account_ids_filter:
            aid = account_ids_filter[0]
            r = accounts_df[accounts_df["account_id"] == aid].iloc[0]
            col_bank.markdown(
                f'<span style="display:inline-block;width:100%;height:3px;border-radius:2px;'
                f'background:{r["bank_color"]};"></span>',
                unsafe_allow_html=True,
            )
    else:
        account_ids_filter = None
        col_bank.caption("No accounts found — sync first.")

    search = col_search.text_input("Search", placeholder="merchant / description…", key="txn_search")

    direction = st.radio(
        "Show", ["All", "Outgoing", "Incoming"], horizontal=True, key="txn_direction"
    )

direction_filter = None if direction == "All" else direction.lower()

# ---------------------------------------------------------------------------
# Load transactions
# ---------------------------------------------------------------------------
df = queries.get_transactions(
    from_date=str(from_date),
    to_date=str(to_date),
    category=category if category != "All" else None,
    account_ids=account_ids_filter,
    direction=direction_filter,
    search=search or None,
)

if df.empty:
    st.info("No transactions match the current filters.")
    st.stop()

# ---------------------------------------------------------------------------
# Sort controls — stored in session_state so they survive reruns
# ---------------------------------------------------------------------------
SORT_COLS = {
    "Date":        "timestamp",
    "Amount":      "amount",
    "Description": "description",
    "Category":    "category",
    "Bank":        "bank_name",
}

sc1, sc2 = st.columns([3, 1])
sort_label = sc1.selectbox("Sort by", list(SORT_COLS.keys()), key="txn_sort_col")
sort_dir   = sc2.radio("Order", ["Descending", "Ascending"], horizontal=True, key="txn_sort_dir")

sort_col = SORT_COLS[sort_label]
sort_asc = sort_dir == "Ascending"
df = df.sort_values(sort_col, ascending=sort_asc)

# ---------------------------------------------------------------------------
# Transactions table — multi-row selection
# ---------------------------------------------------------------------------
display_cols = ["timestamp", "description", "merchant_name", "amount", "category",
                "bank_name", "is_shared", "is_excluded", "notes"]
display_df = df[display_cols].copy()
display_df["timestamp"] = display_df["timestamp"].str[:10]
display_df["is_shared"]   = display_df["is_shared"].map({0: "", 1: "✓"})
display_df["is_excluded"] = display_df["is_excluded"].map({0: "", 1: "Excluded"})

st.caption(f"{len(df)} transaction(s)  —  select one to edit, or multiple for bulk actions")

event = st.dataframe(
    display_df,
    use_container_width=True,
    hide_index=True,
    on_select="rerun",
    selection_mode="multi-row",
    column_config={
        "amount":      st.column_config.NumberColumn("Amount (£)", format="£%.2f"),
        "bank_name":   st.column_config.TextColumn("Bank"),
        "is_shared":   st.column_config.TextColumn("Shared"),
        "is_excluded": st.column_config.TextColumn("Excluded"),
        "notes":       st.column_config.TextColumn("Notes"),
    },
)

selected_rows = event.selection.rows if event.selection else []

if not selected_rows:
    st.info("Select one row to edit it, or multiple rows for bulk actions.", icon="👆")
    st.stop()

st.divider()

# ---------------------------------------------------------------------------
# BULK EDIT — multiple rows selected
# ---------------------------------------------------------------------------
if len(selected_rows) > 1:
    st.subheader(f"Bulk Edit — {len(selected_rows)} transactions selected")

    bc1, bc2, bc3, bc4 = st.columns([3, 2, 2, 1])
    bulk_cat    = bc1.selectbox(
        "Set category", ["(no change)"] + all_category_options(), key="bulk_cat"
    )
    bulk_shared = bc2.selectbox(
        "Mark as shared", ["(no change)", "Yes", "No"], key="bulk_shared"
    )
    bulk_exclude = bc3.selectbox(
        "Exclude from calculations",
        ["(no change)", "Yes — exclude", "No — include"],
        key="bulk_exclude",
        help="Excluded transactions are hidden from all spend totals, charts, and budgets.",
    )

    if bc4.button("Apply to all", type="primary"):
        for i in selected_rows:
            tid = df.iloc[i]["transaction_id"]
            kwargs: dict = {}
            if bulk_cat != "(no change)":
                kwargs["category"] = bulk_cat or None
            if bulk_shared != "(no change)":
                kwargs["is_shared"] = bulk_shared == "Yes"
            if bulk_exclude != "(no change)":
                kwargs["is_excluded"] = bulk_exclude == "Yes — exclude"
            if kwargs:
                queries.update_transaction(tid, **kwargs)
        st.success(f"Updated {len(selected_rows)} transactions.")
        st.rerun()

    st.stop()

# ---------------------------------------------------------------------------
# SINGLE EDIT — one row selected
# ---------------------------------------------------------------------------
selected             = df.iloc[selected_rows[0]]
txn_id               = selected["transaction_id"]
txn_amount           = abs(float(selected.get("amount", 0)))
current_is_shared    = bool(selected.get("is_shared", 0))
current_is_excluded  = bool(selected.get("is_excluded", 0))

meta_col, edit_col = st.columns([1, 2])

with meta_col:
    st.subheader("Selected Transaction")
    st.write(f"**{selected.get('description', '')}**")
    merchant = selected.get("merchant_name", "")
    if merchant:
        st.caption(f"Merchant: {merchant}")
    dir_label = "Incoming" if float(selected.get("amount", 0)) > 0 else "Outgoing"
    st.write(f"Amount: `£{float(selected.get('amount', 0)):,.2f}` ({dir_label})")
    st.write(f"Date:    `{str(selected.get('timestamp', ''))[:10]}`")
    st.write(f"Account: `{selected.get('account_name', '')}`")
    bank_color = selected.get("bank_color", "#4A90D9")
    st.markdown(
        f'<span style="display:inline-block;width:12px;height:12px;border-radius:2px;'
        f'background:{bank_color};vertical-align:middle;margin-right:6px;"></span>'
        f'{selected.get("bank_name", "")}',
        unsafe_allow_html=True,
    )

with edit_col:
    is_shared = st.checkbox(
        "Shared — someone owes me part of this",
        value=current_is_shared,
        key=f"shared_chk_{txn_id}",
    )
    is_excluded = st.checkbox(
        "Exclude from calculations (failed payment, refund, etc.)",
        value=current_is_excluded,
        key=f"excl_chk_{txn_id}",
        help="When ticked, this transaction is hidden from all spend totals, charts, and budgets.",
    )

    with st.form(f"edit_txn_{txn_id}"):
        cat_options = [""] + all_category_options()
        current_cat = selected.get("category", "") or ""
        try:
            cat_idx = cat_options.index(current_cat)
        except ValueError:
            cat_idx = 0
        new_cat   = st.selectbox("Category", cat_options, index=cat_idx)
        new_notes = st.text_area("Notes", value=selected.get("notes", "") or "")

        if st.form_submit_button("Save Details", type="primary"):
            is_shared_val   = st.session_state.get(f"shared_chk_{txn_id}", current_is_shared)
            is_excluded_val = st.session_state.get(f"excl_chk_{txn_id}", current_is_excluded)
            queries.update_transaction(
                txn_id,
                category=new_cat or None,
                is_shared=is_shared_val,
                notes=new_notes or None,
                is_excluded=is_excluded_val,
            )
            st.success("Saved.")
            st.rerun()

# ---------------------------------------------------------------------------
# Shared split — NO st.form so sliders update the amount display live
# ---------------------------------------------------------------------------
if is_shared:
    st.markdown("---")
    split_col, existing_col = st.columns([1, 1])

    with split_col:
        st.subheader("Add Split")
        st.caption(f"Transaction total: **£{txn_amount:.2f}**")

        person = st.text_input(
            "Who are you splitting with?",
            placeholder="e.g. Alice",
            key=f"sp_person_{txn_id}",
        )
        split_mode = st.radio(
            "Enter split as",
            ["Percentage", "Fixed amount"],
            horizontal=True,
            key=f"sp_mode_{txn_id}",
        )

        if split_mode == "Percentage":
            pct = st.slider(
                "Their share (%)", min_value=1, max_value=99, value=50,
                key=f"sp_pct_{txn_id}",
            )
            share_amount = txn_amount * pct / 100
        else:
            share_amount = st.number_input(
                "Their share (£)",
                min_value=0.01,
                max_value=float(txn_amount) if txn_amount > 0 else 1.0,
                value=round(txn_amount / 2, 2),
                step=0.01,
                key=f"sp_amt_{txn_id}",
            )
            pct = (share_amount / txn_amount * 100) if txn_amount > 0 else 0

        st.metric("They owe you", f"£{share_amount:.2f}", delta=f"{pct:.1f}% of the total")

        if st.button("Add Split", type="primary", key=f"sp_add_{txn_id}"):
            if person.strip():
                queries.update_transaction(txn_id, is_shared=True)
                queries.add_shared_split(txn_id, person.strip(), pct, share_amount)
                st.success(f"Added — {person.strip()} owes you £{share_amount:.2f}")
                st.rerun()
            else:
                st.warning("Enter the person's name first.")

    with existing_col:
        existing_splits = queries.get_splits_for_transaction(txn_id)
        st.subheader("Existing Splits")
        if not existing_splits.empty:
            for _, sp in existing_splits.iterrows():
                settled = bool(sp["is_settled"])
                c1, c2, c3 = st.columns([3, 3, 1])
                c1.write(f"**{sp['person_name']}**")
                c2.write(
                    f"{sp['their_share_pct']:.0f}% = £{sp['their_share_amount']:.2f}  "
                    + ("✅" if settled else "⏳")
                )
                if not settled:
                    if c3.button("Settle", key=f"settle_sp_{sp['id']}"):
                        queries.settle_shared_split(int(sp["id"]))
                        st.rerun()
        else:
            st.caption("No splits yet for this transaction.")
