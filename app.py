"""
Entry point for the Streamlit Personal Finance Dashboard.
Run with: streamlit run app.py
"""

import streamlit as st

from db.schema import create_tables
from db.queries import get_tokens, get_all_connections, delete_connection, get_accounts, update_account_bank_info, backfill_merchant_names, backfill_categories, backfill_transaction_dates, get_last_sync

st.set_page_config(
    page_title="Money Saver",
    page_icon="💰",
    layout="wide",
    initial_sidebar_state="expanded",
)


# ---------------------------------------------------------------------------
# Bootstrap
# ---------------------------------------------------------------------------

def bootstrap() -> None:
    create_tables()

    if "bootstrapped" not in st.session_state:
        st.session_state["bootstrapped"] = True

    tokens = get_tokens()
    if tokens and "sync_started" not in st.session_state:
        from sync.scheduler import start_background_sync
        start_background_sync(interval_seconds=300)
        st.session_state["sync_started"] = True

    # Run silently after every sync to catch any new uncleaned transactions
    last = get_last_sync()
    last_id = last["id"] if last else 0
    if st.session_state.get("last_cleaned_sync_id") != last_id:
        backfill_transaction_dates()
        backfill_merchant_names()
        backfill_categories()
        st.session_state["last_cleaned_sync_id"] = last_id


# ---------------------------------------------------------------------------
# Auth flow
# ---------------------------------------------------------------------------

def show_auth_flow() -> None:
    st.title("Connect Your Bank")
    st.markdown(
        "This dashboard uses **TrueLayer** to securely read your bank transactions. "
        "Click the button below to authorise access — you'll be redirected to your bank."
    )

    bank_label = st.text_input("Bank name", value="My Bank", placeholder="e.g. Monzo, Barclays")

    if st.button("Connect Bank", type="primary"):
        with st.spinner("Opening browser for authorisation…"):
            from sync.truelayer import run_oauth_flow
            success = run_oauth_flow(bank_label.strip() or "My Bank")

        if success:
            st.session_state["sync_started"] = False
            st.success("Bank connected! Loading your data…")
            st.rerun()
        else:
            st.error("Authorisation failed or timed out. Please try again.")


# ---------------------------------------------------------------------------
# Sidebar: bank management
# ---------------------------------------------------------------------------

def show_sidebar() -> None:
    with st.sidebar:
        # ── Connected banks ───────────────────────────────────────────────────
        st.subheader("Connected Banks")
        connections = get_all_connections()
        for c in connections:
            c1, c2 = st.columns([3, 1])
            c1.write(f"**{c['label']}**")
            with c2.popover("✕", help="Disconnect this bank"):
                st.warning(
                    f"This will permanently delete **{c['label']}** and all its "
                    "transactions from your data. You will need to re-authorise to reconnect."
                )
                if st.button(
                    "Yes, delete everything", type="primary", key=f"confirm_disc_{c['id']}"
                ):
                    delete_connection(int(c["id"]))
                    st.rerun()

        st.markdown("")
        with st.expander("Add another bank"):
            new_label = st.text_input(
                "Bank name", placeholder="e.g. Barclays", key="new_bank_label"
            )
            if st.button("Connect", type="primary", key="connect_new_bank"):
                if new_label.strip():
                    with st.spinner(f"Connecting {new_label.strip()}…"):
                        from sync.truelayer import run_oauth_flow
                        success = run_oauth_flow(new_label.strip())
                    if success:
                        st.success(f"{new_label.strip()} connected!")
                        st.rerun()
                    else:
                        st.error("Connection failed or timed out.")
                else:
                    st.warning("Enter a bank name first.")

        # ── Account display settings ──────────────────────────────────────────
        st.markdown("---")
        st.subheader("Account Settings")
        accounts_df = get_accounts()

        if accounts_df.empty:
            st.caption("No accounts found — sync data first.")
        else:
            with st.expander("Set display names & colours", expanded=False):
                for _, row in accounts_df.iterrows():
                    st.markdown(f"**{row['account_name']}** `{row['account_type']}`")
                    col_name, col_color = st.columns([2, 1])
                    new_bank_name = col_name.text_input(
                        "Display name",
                        value=row["bank_name"],
                        key=f"bname_{row['account_id']}",
                        label_visibility="collapsed",
                        placeholder="e.g. Monzo",
                    )
                    new_color = col_color.color_picker(
                        "Colour",
                        value=row["bank_color"],
                        key=f"bcolor_{row['account_id']}",
                        label_visibility="collapsed",
                    )
                    if st.button("Save", key=f"bsave_{row['account_id']}"):
                        update_account_bank_info(row["account_id"], new_bank_name, new_color)
                        st.success(f"Saved {new_bank_name}")
                        st.rerun()
                    st.markdown("---")


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

bootstrap()

pages = [
    st.Page("pages/1_Overview.py",     title="Overview"),
    st.Page("pages/2_Transactions.py", title="Transactions"),
    st.Page("pages/3_Habits.py",       title="Habits"),
    st.Page("pages/4_Budget.py",       title="Budget"),
]

if not get_all_connections():
    show_auth_flow()
else:
    show_sidebar()
    pg = st.navigation(pages)
    pg.run()
