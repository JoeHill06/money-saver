"""
All database read/write functions. Pages never use raw SQL — they call these.
"""

import calendar
import re
import time
from datetime import date, timedelta
from typing import Optional

import pandas as pd

from db.schema import get_connection

# ---------------------------------------------------------------------------
# Merchant name normalisation
# ---------------------------------------------------------------------------

_APPLE_PAY_SUFFIX = re.compile(
    r'\s*\(VIA APPLE PAY\),?\s*ON\s+\d{2}-\d{2}-\d{4}', re.IGNORECASE
)
_ON_DATE_SUFFIX  = re.compile(r'\s+ON\s+\d{2}[-/]\d{2}[-/]\d{4}.*$', re.IGNORECASE)
_CARD_PREFIX     = re.compile(r'^CARD PAYMENT TO\s+', re.IGNORECASE)
_PAYMENT_PREFIX  = re.compile(r'^(SUMUP\s*\*|SQ\s*\*|SP\s+|UNVRS\*\s*)', re.IGNORECASE)
_TRAILING_JUNK       = re.compile(r'[\s,\-]+$')
_PURCHASE_DATE_RE    = re.compile(r'\bON\s+(\d{2})-(\d{2})-(\d{4})', re.IGNORECASE)

# Known brand aliases: (pattern, clean name)
_MERCHANT_ALIASES = [
    (re.compile(r"SAINSBURY", re.I),            "Sainsbury's"),
    (re.compile(r"^UBR\*",    re.I),            "Uber"),
    (re.compile(r"WM MORRISON", re.I),          "Morrisons"),
    (re.compile(r"CO.?OP GROUP FOOD", re.I),    "Co-op"),
    (re.compile(r"TESCO STORES", re.I),         "Tesco"),
    (re.compile(r"MCDONALDS", re.I),            "McDonald's"),
    (re.compile(r"FIRST WEST YORKSHIRE", re.I), "First Bus"),
    (re.compile(r"APPLE\.COM", re.I),           "Apple"),
    (re.compile(r"OPENAI", re.I),               "OpenAI"),
    (re.compile(r"CLAUDE\.AI", re.I),           "Claude.ai"),
    (re.compile(r"JD WETHERSPOON", re.I),       "Wetherspoons"),
]


def normalize_merchant(description: str) -> str:
    """Return a clean merchant name extracted from a raw bank description."""
    name = description or ""
    name = _APPLE_PAY_SUFFIX.sub("", name)
    name = _CARD_PREFIX.sub("", name)
    name = _ON_DATE_SUFFIX.sub("", name)
    name = _PAYMENT_PREFIX.sub("", name)
    name = _TRAILING_JUNK.sub("", name).strip()

    for pattern, alias in _MERCHANT_ALIASES:
        if pattern.search(name):
            return alias

    # Title-case if the name is all-uppercase (most raw bank descriptions are)
    if name and name == name.upper():
        name = name.title()

    return name


# ---------------------------------------------------------------------------
# Auto-categorisation rules
# Matched against the cleaned merchant name (or raw description as fallback).
# Order matters — first match wins.
# ---------------------------------------------------------------------------
_CATEGORY_RULES: list[tuple[re.Pattern, str]] = [
    # Food & Groceries
    (re.compile(r"sainsbury",           re.I), "Food & Groceries"),
    (re.compile(r"tesco",               re.I), "Food & Groceries"),
    (re.compile(r"morrison",            re.I), "Food & Groceries"),
    (re.compile(r"co.?op",              re.I), "Food & Groceries"),
    (re.compile(r"aldi",                re.I), "Food & Groceries"),
    (re.compile(r"lidl",                re.I), "Food & Groceries"),
    (re.compile(r"waitrose",            re.I), "Food & Groceries"),
    (re.compile(r"asda",                re.I), "Food & Groceries"),
    (re.compile(r"marks.?&.?spencer|m&s food", re.I), "Food & Groceries"),
    # Transport
    (re.compile(r"uber|ubr\*",          re.I), "Transport"),
    (re.compile(r"first.?bus|first west yorkshire", re.I), "Transport"),
    (re.compile(r"mfg lyceum",          re.I), "Transport"),  # petrol
    (re.compile(r"trainline|thetrainline", re.I), "Transport"),
    (re.compile(r"national rail",       re.I), "Transport"),
    (re.compile(r"tfl|transport for london", re.I), "Transport"),
    # Eating Out
    (re.compile(r"royal park hotel",    re.I), "Eating Out"),
    (re.compile(r"bragg",               re.I), "Eating Out"),
    (re.compile(r"esther simpson",      re.I), "Eating Out"),
    (re.compile(r"the library",         re.I), "Eating Out"),
    (re.compile(r"wetherspoon",         re.I), "Eating Out"),
    (re.compile(r"whitelocks",          re.I), "Eating Out"),
    (re.compile(r"ice scoop",           re.I), "Eating Out"),
    (re.compile(r"tre cafe",            re.I), "Eating Out"),
    (re.compile(r"edit room",           re.I), "Eating Out"),
    (re.compile(r"bakery 164",          re.I), "Eating Out"),
    (re.compile(r"caffe nero",          re.I), "Eating Out"),
    (re.compile(r"pho leeds",           re.I), "Eating Out"),
    (re.compile(r"domino.?s",           re.I), "Eating Out"),
    (re.compile(r"mcdonalds|mcdonald.s",re.I), "Eating Out"),
    (re.compile(r"mythos",              re.I), "Eating Out"),
    (re.compile(r"coffee on the",       re.I), "Eating Out"),
    (re.compile(r"terrace leeds",       re.I), "Eating Out"),
    (re.compile(r"flames",              re.I), "Eating Out"),
    (re.compile(r"little snack bar",    re.I), "Eating Out"),
    (re.compile(r"pitza cano|cano bar", re.I), "Eating Out"),
    (re.compile(r"mr su",               re.I), "Eating Out"),
    (re.compile(r"tattu",               re.I), "Eating Out"),
    (re.compile(r"skyrack",             re.I), "Eating Out"),
    (re.compile(r"the royalty",         re.I), "Eating Out"),
    (re.compile(r"hugo",                re.I), "Eating Out"),
    (re.compile(r"ls2 store",           re.I), "Eating Out"),
    (re.compile(r"warehouse",           re.I), "Eating Out"),
    (re.compile(r"broderick vend",      re.I), "Eating Out"),
    (re.compile(r"hyde park hotel",     re.I), "Eating Out"),
    # Entertainment
    (re.compile(r"brudenell",           re.I), "Entertainment"),
    (re.compile(r"belgrave music",      re.I), "Entertainment"),
    (re.compile(r"fixr",                re.I), "Entertainment"),
    (re.compile(r"leeds.?uni.?union|leeds uu", re.I), "Entertainment"),
    (re.compile(r"venues",              re.I), "Entertainment"),
    # Subscriptions
    (re.compile(r"apple\.com|apple\.com/bill", re.I), "Subscriptions"),
    (re.compile(r"openai|chatgpt",      re.I), "Subscriptions"),
    (re.compile(r"claude\.ai",          re.I), "Subscriptions"),
    (re.compile(r"spotify",             re.I), "Subscriptions"),
    (re.compile(r"netflix",             re.I), "Subscriptions"),
    (re.compile(r"amazon prime",        re.I), "Subscriptions"),
    (re.compile(r"miro",                re.I), "Subscriptions"),
    # Personal Care
    (re.compile(r"boots",               re.I), "Personal Care"),
    (re.compile(r"barber|hendo",        re.I), "Personal Care"),
    (re.compile(r"superdrug",           re.I), "Personal Care"),
    # Shopping
    (re.compile(r"fat face",            re.I), "Shopping"),
    (re.compile(r"moleskine",           re.I), "Shopping"),
    (re.compile(r"amazon(?!.*prime)",   re.I), "Shopping"),
    # Travel
    (re.compile(r"wasteland ski",       re.I), "Travel"),
    (re.compile(r"booking\.com",        re.I), "Travel"),
    (re.compile(r"airbnb",              re.I), "Travel"),
]


def auto_categorize(merchant: str, description: str = "") -> str:
    """Return a category for a transaction based on merchant name / description."""
    for text in (merchant, description):
        if not text:
            continue
        for pattern, category in _CATEGORY_RULES:
            if pattern.search(text):
                return category
    return ""


def backfill_categories() -> int:
    """
    Auto-categorise transactions where category is blank.
    Never overwrites a category the user has already set.
    Returns number of rows updated.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT transaction_id, merchant_name, description FROM transactions "
            "WHERE category IS NULL OR category = ''"
        ).fetchall()
        updated = 0
        with conn:
            for row in rows:
                cat = auto_categorize(row["merchant_name"] or "", row["description"] or "")
                if cat:
                    conn.execute(
                        "UPDATE transactions SET category = ? WHERE transaction_id = ?",
                        (cat, row["transaction_id"]),
                    )
                    updated += 1
        return updated
    finally:
        conn.close()


def backfill_merchant_names() -> int:
    """
    Normalise merchant_name for all transactions where it is blank.
    Returns the number of rows updated.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT transaction_id, description FROM transactions "
            "WHERE merchant_name IS NULL OR merchant_name = ''"
        ).fetchall()
        updated = 0
        with conn:
            for row in rows:
                name = normalize_merchant(row["description"])
                if name:
                    conn.execute(
                        "UPDATE transactions SET merchant_name = ? WHERE transaction_id = ?",
                        (name, row["transaction_id"]),
                    )
                    updated += 1
        return updated
    finally:
        conn.close()


def extract_purchase_date(description: str) -> Optional[str]:
    """
    Extract the actual purchase date from an Apple Pay description.
    Descriptions look like: 'SAINSBURYS (VIA APPLE PAY), ON 19-02-2026'
    Returns 'YYYY-MM-DD' or None if no date is found.
    """
    if not description:
        return None
    m = _PURCHASE_DATE_RE.search(description)
    if m:
        dd, mm, yyyy = m.group(1), m.group(2), m.group(3)
        return f"{yyyy}-{mm}-{dd}"
    return None


def backfill_transaction_dates() -> int:
    """
    Fix timestamps for Apple Pay transactions whose descriptions contain the actual
    purchase date in 'ON DD-MM-YYYY' format (TrueLayer uses T+1 settlement date).
    Only updates rows where the stored date differs from the extracted purchase date.
    Returns number of rows updated.
    """
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT transaction_id, description, timestamp FROM transactions "
            "WHERE description LIKE '%ON %'"
        ).fetchall()
        updated = 0
        with conn:
            for row in rows:
                purchase_date = extract_purchase_date(row["description"])
                if not purchase_date:
                    continue
                current_ts = row["timestamp"] or ""
                current_date = current_ts[:10]
                if current_date == purchase_date:
                    continue
                # Preserve the time portion if present, otherwise just use the date
                if "T" in current_ts:
                    new_ts = purchase_date + current_ts[10:]
                else:
                    new_ts = purchase_date
                conn.execute(
                    "UPDATE transactions SET timestamp = ? WHERE transaction_id = ?",
                    (new_ts, row["transaction_id"]),
                )
                updated += 1
        return updated
    finally:
        conn.close()

# ---------------------------------------------------------------------------
# Common categories — shown in every category picker
# ---------------------------------------------------------------------------
PREDEFINED_CATEGORIES = [
    "Bills & Utilities",
    "Eating Out",
    "Entertainment",
    "Food & Groceries",
    "Health & Medical",
    "Housing & Rent",
    "Personal Care",
    "Self-Transfer",
    "Transfer",
    "Shopping",
    "Subscriptions",
    "Transport",
    "Travel",
    "Income",
    "Unknown",
    "Other",
]

EXCLUDE_FROM_SPEND = ("Self-Transfer", "Income")


# ---------------------------------------------------------------------------
# Bank Connections
# ---------------------------------------------------------------------------

def get_all_connections() -> list[dict]:
    conn = get_connection()
    try:
        rows = conn.execute("SELECT * FROM bank_connections ORDER BY id").fetchall()
        return [dict(r) for r in rows]
    finally:
        conn.close()


def get_tokens() -> Optional[dict]:
    """Returns the first bank connection — used as the 'are we authenticated?' check."""
    conn = get_connection()
    try:
        row = conn.execute("SELECT * FROM bank_connections ORDER BY id LIMIT 1").fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


def add_connection(label: str, access_token: str, refresh_token: str, expires_in: int) -> int:
    expires_at = time.time() + expires_in
    conn = get_connection()
    with conn:
        cur = conn.execute(
            "INSERT INTO bank_connections (label, access_token, refresh_token, expires_at) "
            "VALUES (?, ?, ?, ?)",
            (label, access_token, refresh_token, expires_at),
        )
        new_id = cur.lastrowid
    conn.close()
    return new_id


def update_connection_tokens(
    connection_id: int, access_token: str, refresh_token: str, expires_in: int
) -> None:
    expires_at = time.time() + expires_in
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE bank_connections SET access_token = ?, refresh_token = ?, expires_at = ? "
            "WHERE id = ?",
            (access_token, refresh_token, expires_at, connection_id),
        )
    conn.close()


def delete_connection(connection_id: int) -> None:
    """
    Remove a bank connection and ALL associated data:
    accounts, transactions, and any shared splits on those transactions.
    """
    conn = get_connection()
    with conn:
        # Find all account_ids belonging to this connection
        account_rows = conn.execute(
            "SELECT account_id FROM accounts WHERE connection_id = ?", (connection_id,)
        ).fetchall()
        account_ids = [r["account_id"] for r in account_rows]

        if account_ids:
            placeholders = ",".join("?" * len(account_ids))
            # Find transaction_ids for these accounts
            txn_rows = conn.execute(
                f"SELECT transaction_id FROM transactions WHERE account_id IN ({placeholders})",
                account_ids,
            ).fetchall()
            txn_ids = [r["transaction_id"] for r in txn_rows]

            if txn_ids:
                t_placeholders = ",".join("?" * len(txn_ids))
                # Delete shared splits referencing these transactions
                conn.execute(
                    f"DELETE FROM shared_transactions WHERE transaction_id IN ({t_placeholders})",
                    txn_ids,
                )
                # Delete the transactions
                conn.execute(
                    f"DELETE FROM transactions WHERE transaction_id IN ({t_placeholders})",
                    txn_ids,
                )
            # Delete accounts
            conn.execute(
                f"DELETE FROM accounts WHERE account_id IN ({placeholders})", account_ids
            )

        # Delete the connection itself
        conn.execute("DELETE FROM bank_connections WHERE id = ?", (connection_id,))
    conn.close()


# ---------------------------------------------------------------------------
# Accounts
# ---------------------------------------------------------------------------

def upsert_accounts(accounts: list[dict], connection_id: int = None) -> None:
    conn = get_connection()
    with conn:
        for acc in accounts:
            conn.execute(
                """
                INSERT INTO accounts (account_id, account_name, account_type, currency, connection_id)
                VALUES (?, ?, ?, ?, ?)
                ON CONFLICT(account_id) DO UPDATE SET
                    account_name = excluded.account_name,
                    account_type = excluded.account_type,
                    currency = excluded.currency,
                    connection_id = COALESCE(excluded.connection_id, accounts.connection_id)
                """,
                (
                    acc.get("account_id", ""),
                    acc.get("display_name", acc.get("account_id", "")),
                    acc.get("account_type", ""),
                    acc.get("currency", "GBP"),
                    connection_id,
                ),
            )
    conn.close()


def get_accounts() -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            "SELECT account_id, account_name, account_type, currency, "
            "COALESCE(bank_name, account_name) AS bank_name, "
            "COALESCE(bank_color, '#4A90D9') AS bank_color "
            "FROM accounts ORDER BY bank_name, account_name",
            conn,
        )
    finally:
        conn.close()


def update_account_bank_info(account_id: str, bank_name: str, bank_color: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE accounts SET bank_name = ?, bank_color = ? WHERE account_id = ?",
            (bank_name, bank_color, account_id),
        )
    conn.close()


# ---------------------------------------------------------------------------
# Transactions
# ---------------------------------------------------------------------------

def upsert_transactions(transactions: list[dict]) -> int:
    """Upsert a list of TrueLayer transaction dicts. Returns count upserted."""
    conn = get_connection()
    upserted = 0
    with conn:
        for txn in transactions:
            description = txn.get("description", "")
            merchant = (
                txn.get("merchant_name")
                or (txn.get("meta") or {}).get("provider_merchant_name", "")
                or normalize_merchant(description)
            )
            category = ""
            if txn.get("transaction_classification"):
                category = txn["transaction_classification"][0]
            elif txn.get("transaction_category"):
                category = txn["transaction_category"]
            if not category:
                category = auto_categorize(merchant, description)

            # Fix T+1 settlement date: use actual purchase date from description if present
            timestamp = txn.get("timestamp", "")
            purchase_date = extract_purchase_date(description)
            if purchase_date:
                if "T" in timestamp:
                    timestamp = purchase_date + timestamp[10:]
                else:
                    timestamp = purchase_date

            conn.execute(
                """
                INSERT INTO transactions
                    (transaction_id, account_id, account_name, account_type,
                     timestamp, description, amount, currency,
                     transaction_type, category, merchant_name)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(transaction_id) DO UPDATE SET
                    timestamp = excluded.timestamp,
                    category = COALESCE(transactions.category, excluded.category),
                    merchant_name = COALESCE(transactions.merchant_name, excluded.merchant_name)
                """,
                (
                    txn.get("transaction_id", ""),
                    txn.get("account_id", ""),
                    txn.get("account_name", ""),
                    txn.get("account_type", ""),
                    timestamp,
                    description,
                    float(txn.get("amount", 0) or 0),
                    txn.get("currency", "GBP"),
                    txn.get("transaction_type", ""),
                    category,
                    merchant,
                ),
            )
            upserted += 1
    conn.close()
    return upserted


def get_transactions(
    from_date: Optional[str] = None,
    to_date: Optional[str] = None,
    category: Optional[str] = None,
    account_ids: Optional[list[str]] = None,
    txn_type: Optional[str] = None,
    direction: Optional[str] = None,  # 'incoming' | 'outgoing'
    search: Optional[str] = None,
    is_shared: Optional[bool] = None,
) -> pd.DataFrame:
    conditions = []
    params: list = []

    if from_date:
        conditions.append("t.timestamp >= ?")
        params.append(from_date)
    if to_date:
        conditions.append("t.timestamp <= ?")
        params.append(to_date + "T23:59:59")
    if category and category != "All":
        conditions.append("t.category = ?")
        params.append(category)
    if account_ids:
        placeholders = ",".join("?" * len(account_ids))
        conditions.append(f"t.account_id IN ({placeholders})")
        params.extend(account_ids)
    if txn_type and txn_type != "All":
        conditions.append("t.transaction_type = ?")
        params.append(txn_type)
    if direction == "incoming":
        conditions.append("t.amount > 0")
    elif direction == "outgoing":
        conditions.append("t.amount < 0")
    if search:
        conditions.append("(t.description LIKE ? OR t.merchant_name LIKE ? OR t.notes LIKE ?)")
        like = f"%{search}%"
        params.extend([like, like, like])
    if is_shared is not None:
        conditions.append("t.is_shared = ?")
        params.append(1 if is_shared else 0)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    sql = f"""
        SELECT
            t.*,
            COALESCE(a.bank_name, a.account_name, t.account_name) AS bank_name,
            COALESCE(a.bank_color, '#4A90D9') AS bank_color
        FROM transactions t
        LEFT JOIN accounts a ON a.account_id = t.account_id
        {where}
        ORDER BY t.timestamp DESC
    """

    conn = get_connection()
    try:
        return pd.read_sql_query(sql, conn, params=params)
    finally:
        conn.close()


def update_transaction(
    transaction_id: str,
    category: Optional[str] = None,
    is_shared: Optional[bool] = None,
    notes: Optional[str] = None,
    is_excluded: Optional[bool] = None,
) -> None:
    sets = []
    params = []
    if category is not None:
        sets.append("category = ?")
        params.append(category)
    if is_shared is not None:
        sets.append("is_shared = ?")
        params.append(1 if is_shared else 0)
    if notes is not None:
        sets.append("notes = ?")
        params.append(notes)
    if is_excluded is not None:
        sets.append("is_excluded = ?")
        params.append(1 if is_excluded else 0)
    if not sets:
        return
    params.append(transaction_id)
    conn = get_connection()
    with conn:
        conn.execute(
            f"UPDATE transactions SET {', '.join(sets)} WHERE transaction_id = ?",
            params,
        )
    conn.close()


def get_monthly_summary(year_month: str) -> dict:
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN amount > 0 AND category != 'Self-Transfer' THEN amount ELSE 0 END) AS income,
                SUM(CASE WHEN amount < 0 AND category != 'Self-Transfer' THEN ABS(amount) ELSE 0 END) AS spend,
                SUM(CASE WHEN category != 'Self-Transfer' THEN amount ELSE 0 END) AS net
            FROM transactions
            WHERE strftime('%Y-%m', timestamp) = ?
              AND COALESCE(is_excluded, 0) = 0
            """,
            (year_month,),
        ).fetchone()
        return {
            "income": row["income"] or 0.0,
            "spend": row["spend"] or 0.0,
            "net": row["net"] or 0.0,
        }
    finally:
        conn.close()


def get_summary_for_period(from_date: str, to_date: str) -> dict:
    """Income, spend, net for an arbitrary date range."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT
                SUM(CASE WHEN amount > 0 AND category != 'Self-Transfer' THEN amount ELSE 0 END) AS income,
                SUM(CASE WHEN amount < 0 AND category != 'Self-Transfer' THEN ABS(amount) ELSE 0 END) AS spend,
                SUM(CASE WHEN category != 'Self-Transfer' THEN amount ELSE 0 END) AS net
            FROM transactions
            WHERE timestamp >= ? AND timestamp <= ?
              AND COALESCE(is_excluded, 0) = 0
            """,
            (from_date, to_date + "T23:59:59"),
        ).fetchone()
        return {
            "income": row["income"] or 0.0,
            "spend": row["spend"] or 0.0,
            "net": row["net"] or 0.0,
        }
    finally:
        conn.close()


def get_spending_capacity(year_month: str) -> dict:
    """
    Compute how much the user can still spend this month broken into daily/weekly.
    Uses income_sources, fixed_outgoings, and savings_goals tables.
    """
    total_income = get_total_monthly_income()
    total_fixed = get_total_monthly_outgoings()
    total_savings = get_total_monthly_savings_contribution()
    monthly_allowance = total_income - total_fixed - total_savings

    summary = get_monthly_summary(year_month)
    spend_so_far = summary["spend"]
    remaining = monthly_allowance - spend_so_far

    today = date.today()
    days_in_month = calendar.monthrange(today.year, today.month)[1]
    days_remaining = max(1, days_in_month - today.day + 1)

    daily = max(remaining / days_remaining, 0)

    return {
        "monthly_allowance": monthly_allowance,
        "spend_so_far": spend_so_far,
        "remaining": remaining,
        "days_remaining": days_remaining,
        "daily": daily,
        "weekly": daily * 7,
        "income": total_income,
        "fixed_outgoings": total_fixed,
        "savings_contributions": total_savings,
    }


def get_all_spending_capacities() -> dict:
    """
    Return how much the user can still spend in each time window:
    today, this week, this month, this year.
    All figures are clamped to 0 (never negative).
    """
    today = date.today()

    monthly_income = get_total_monthly_income()
    monthly_fixed = get_total_monthly_outgoings()
    monthly_savings = get_total_monthly_savings_contribution()
    monthly_allowance = monthly_income - monthly_fixed - monthly_savings

    # Scale monthly allowance to each period
    daily_allowance   = monthly_allowance * 12 / 365
    weekly_allowance  = monthly_allowance * 12 / 52
    yearly_allowance  = monthly_allowance * 12

    # Actual spend per period
    month_start = date(today.year, today.month, 1)
    year_start  = date(today.year, 1, 1)

    # Rolling 7-day window clamped to the current month start so previous-month
    # spending never bleeds in. The allowance is always the full 7-day target.
    week_start_raw = today - timedelta(days=6)
    week_start     = max(week_start_raw, month_start)
    weekly_allowance = daily_allowance * 7

    today_spend = get_summary_for_period(str(today), str(today))["spend"]
    week_spend  = get_summary_for_period(str(week_start), str(today))["spend"]
    month_spend = get_summary_for_period(str(month_start), str(today))["spend"]
    year_spend  = get_summary_for_period(str(year_start), str(today))["spend"]

    return {
        "has_income": monthly_income > 0,
        "monthly_allowance": monthly_allowance,
        "daily_allowance":   daily_allowance,
        "weekly_allowance":  weekly_allowance,
        "yearly_allowance":  yearly_allowance,
        # Remaining (clamped to 0)
        "today":  max(daily_allowance   - today_spend, 0),
        "week":   max(weekly_allowance  - week_spend,  0),
        "month":  max(monthly_allowance - month_spend, 0),
        "year":   max(yearly_allowance  - year_spend,  0),
        # Raw spend for progress bars
        "today_spend": today_spend,
        "week_spend":  week_spend,
        "month_spend": month_spend,
        "year_spend":  year_spend,
    }


def get_category_totals(year_month: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                COALESCE(NULLIF(category, ''), 'Unknown') AS category,
                SUM(ABS(amount)) AS total
            FROM transactions
            WHERE amount < 0
              AND COALESCE(category, '') NOT IN ('Self-Transfer', 'Transfer')
              AND COALESCE(is_excluded, 0) = 0
              AND strftime('%Y-%m', timestamp) = ?
            GROUP BY 1
            ORDER BY total DESC
            """,
            conn,
            params=(year_month,),
        )
    finally:
        conn.close()


def get_category_totals_for_period(from_date: str, to_date: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                COALESCE(NULLIF(category, ''), 'Unknown') AS category,
                SUM(ABS(amount)) AS total
            FROM transactions
            WHERE amount < 0
              AND COALESCE(category, '') NOT IN ('Self-Transfer', 'Transfer')
              AND COALESCE(is_excluded, 0) = 0
              AND timestamp >= ? AND timestamp <= ?
            GROUP BY 1
            ORDER BY total DESC
            """,
            conn,
            params=(from_date, to_date + "T23:59:59"),
        )
    finally:
        conn.close()


def get_top_merchants(year_month: str, limit: int = 10) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                COALESCE(NULLIF(merchant_name, ''), description) AS merchant,
                SUM(ABS(amount)) AS total
            FROM transactions
            WHERE amount < 0
              AND COALESCE(category, '') NOT IN ('Self-Transfer', 'Transfer')
              AND COALESCE(is_excluded, 0) = 0
              AND strftime('%Y-%m', timestamp) = ?
            GROUP BY 1
            ORDER BY total DESC
            LIMIT ?
            """,
            conn,
            params=(year_month, limit),
        )
    finally:
        conn.close()


def get_top_merchants_for_period(from_date: str, to_date: str, limit: int = 10) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                COALESCE(NULLIF(merchant_name, ''), description) AS merchant,
                SUM(ABS(amount)) AS total
            FROM transactions
            WHERE amount < 0
              AND COALESCE(category, '') NOT IN ('Self-Transfer', 'Transfer')
              AND COALESCE(is_excluded, 0) = 0
              AND timestamp >= ? AND timestamp <= ?
            GROUP BY 1
            ORDER BY total DESC
            LIMIT ?
            """,
            conn,
            params=(from_date, to_date + "T23:59:59", limit),
        )
    finally:
        conn.close()


def get_monthly_trend(months: int = 6) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            f"""
            SELECT
                strftime('%Y-%m', timestamp) AS year_month,
                COALESCE(NULLIF(category, ''), 'Unknown') AS category,
                SUM(ABS(amount)) AS total
            FROM transactions
            WHERE amount < 0
              AND COALESCE(category, '') NOT IN ('Self-Transfer', 'Transfer')
              AND COALESCE(is_excluded, 0) = 0
              AND timestamp >= date('now', '-{months} months')
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            conn,
        )
    finally:
        conn.close()


def get_trend_for_period(from_date: str, to_date: str, group_by: str = "month") -> pd.DataFrame:
    """
    group_by: 'day' | 'week' | 'month'
    Returns period, category, total spend.
    """
    if group_by == "day":
        period_expr = "strftime('%Y-%m-%d', timestamp)"
    elif group_by == "week":
        period_expr = "strftime('%Y-W%W', timestamp)"
    else:
        period_expr = "strftime('%Y-%m', timestamp)"

    conn = get_connection()
    try:
        return pd.read_sql_query(
            f"""
            SELECT
                {period_expr} AS period,
                COALESCE(NULLIF(category, ''), 'Unknown') AS category,
                SUM(ABS(amount)) AS total
            FROM transactions
            WHERE amount < 0
              AND COALESCE(category, '') NOT IN ('Self-Transfer', 'Transfer')
              AND COALESCE(is_excluded, 0) = 0
              AND timestamp >= ? AND timestamp <= ?
            GROUP BY 1, 2
            ORDER BY 1, 2
            """,
            conn,
            params=(from_date, to_date + "T23:59:59"),
        )
    finally:
        conn.close()


def get_day_of_week_spend() -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                CAST(strftime('%w', timestamp) AS INTEGER) AS dow_num,
                CASE strftime('%w', timestamp)
                    WHEN '0' THEN 'Sun'
                    WHEN '1' THEN 'Mon'
                    WHEN '2' THEN 'Tue'
                    WHEN '3' THEN 'Wed'
                    WHEN '4' THEN 'Thu'
                    WHEN '5' THEN 'Fri'
                    WHEN '6' THEN 'Sat'
                END AS day_of_week,
                AVG(ABS(amount)) AS avg_spend,
                COUNT(*) AS txn_count
            FROM transactions
            WHERE amount < 0
              AND COALESCE(category, '') NOT IN ('Self-Transfer', 'Transfer')
              AND COALESCE(is_excluded, 0) = 0
            GROUP BY 1, 2
            ORDER BY 1
            """,
            conn,
        )
    finally:
        conn.close()


def get_distinct_categories() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT category FROM transactions WHERE category != '' ORDER BY category"
        ).fetchall()
        db_cats = [r[0] for r in rows]
        # Merge with predefined list, preserving order
        merged = list(PREDEFINED_CATEGORIES)
        for c in db_cats:
            if c not in merged:
                merged.append(c)
        return merged
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Debts
# ---------------------------------------------------------------------------

def add_debt(direction: str, person_name: str, amount: float, description: str = "") -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO debts (direction, person_name, amount, description) VALUES (?, ?, ?, ?)",
            (direction, person_name, amount, description),
        )
    conn.close()


def get_debts(include_settled: bool = False) -> pd.DataFrame:
    conn = get_connection()
    try:
        where = "" if include_settled else "WHERE is_settled = 0"
        return pd.read_sql_query(
            f"SELECT * FROM debts {where} ORDER BY created_at DESC", conn
        )
    finally:
        conn.close()


def settle_debt(debt_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE debts SET is_settled = 1, settled_at = datetime('now') WHERE id = ?",
            (debt_id,),
        )
    conn.close()


# ---------------------------------------------------------------------------
# Shared Transactions
# ---------------------------------------------------------------------------

def add_shared_split(
    transaction_id: str,
    person_name: str,
    their_share_pct: float,
    their_share_amount: float,
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO shared_transactions
                (transaction_id, person_name, their_share_pct, their_share_amount)
            VALUES (?, ?, ?, ?)
            """,
            (transaction_id, person_name, their_share_pct, their_share_amount),
        )
        conn.execute(
            "UPDATE transactions SET is_shared = 1 WHERE transaction_id = ?",
            (transaction_id,),
        )
    conn.close()


def get_shared_splits(
    settled_filter: str = "all",
    person_filter: Optional[str] = None,
) -> pd.DataFrame:
    conditions = []
    params: list = []
    if settled_filter == "unsettled":
        conditions.append("st.is_settled = 0")
    elif settled_filter == "settled":
        conditions.append("st.is_settled = 1")
    if person_filter and person_filter != "All":
        conditions.append("st.person_name = ?")
        params.append(person_filter)

    where = "WHERE " + " AND ".join(conditions) if conditions else ""
    conn = get_connection()
    try:
        return pd.read_sql_query(
            f"""
            SELECT
                st.id, st.transaction_id, st.person_name,
                st.their_share_pct, st.their_share_amount, st.is_settled, st.settled_at,
                t.timestamp, t.description, t.merchant_name, t.amount AS txn_amount
            FROM shared_transactions st
            JOIN transactions t ON t.transaction_id = st.transaction_id
            {where}
            ORDER BY t.timestamp DESC
            """,
            conn,
            params=params,
        )
    finally:
        conn.close()


def get_splits_for_transaction(transaction_id: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            "SELECT * FROM shared_transactions WHERE transaction_id = ? ORDER BY id",
            conn,
            params=(transaction_id,),
        )
    finally:
        conn.close()


def settle_shared_split(split_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE shared_transactions SET is_settled = 1, settled_at = datetime('now') WHERE id = ?",
            (split_id,),
        )
    conn.close()


def settle_all_splits_for_person(person_name: str) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE shared_transactions SET is_settled = 1, settled_at = datetime('now') WHERE person_name = ? AND is_settled = 0",
            (person_name,),
        )
    conn.close()


def get_person_totals() -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                person_name,
                SUM(their_share_amount) AS total_owed,
                SUM(CASE WHEN is_settled = 0 THEN their_share_amount ELSE 0 END) AS outstanding
            FROM shared_transactions
            GROUP BY person_name
            ORDER BY outstanding DESC
            """,
            conn,
        )
    finally:
        conn.close()


def get_distinct_split_people() -> list[str]:
    conn = get_connection()
    try:
        rows = conn.execute(
            "SELECT DISTINCT person_name FROM shared_transactions ORDER BY person_name"
        ).fetchall()
        return [r[0] for r in rows]
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Budget
# ---------------------------------------------------------------------------

def get_or_create_budget_month(year_month: str) -> dict:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT OR IGNORE INTO budget_months (year_month) VALUES (?)", (year_month,)
        )
    row = conn.execute(
        "SELECT * FROM budget_months WHERE year_month = ?", (year_month,)
    ).fetchone()
    conn.close()
    return dict(row)


def update_budget_month(year_month: str, monthly_income: float, savings_goal: float) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            UPDATE budget_months
            SET monthly_income = ?, savings_goal = ?
            WHERE year_month = ?
            """,
            (monthly_income, savings_goal, year_month),
        )
    conn.close()


def set_category_budget(year_month: str, category: str, spend_limit: float) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO budget_categories (year_month, category, spend_limit)
            VALUES (?, ?, ?)
            ON CONFLICT(year_month, category) DO UPDATE SET spend_limit = excluded.spend_limit
            """,
            (year_month, category, spend_limit),
        )
    conn.close()


def get_budget_vs_actual(year_month: str) -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            """
            SELECT
                bc.category,
                bc.spend_limit,
                COALESCE(SUM(ABS(t.amount)), 0) AS actual_spend
            FROM budget_categories bc
            LEFT JOIN transactions t
                ON t.category = bc.category
                AND strftime('%Y-%m', t.timestamp) = bc.year_month
                AND t.amount < 0
                AND COALESCE(t.category, '') != 'Self-Transfer'
                AND COALESCE(t.is_excluded, 0) = 0
            WHERE bc.year_month = ?
            GROUP BY bc.category, bc.spend_limit
            ORDER BY bc.category
            """,
            conn,
            params=(year_month,),
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Sync log
# ---------------------------------------------------------------------------

def log_sync_start() -> int:
    conn = get_connection()
    with conn:
        cur = conn.execute("INSERT INTO sync_log (status) VALUES ('running')")
        log_id = cur.lastrowid
    conn.close()
    return log_id


def log_sync_finish(log_id: int, rows_upserted: int, error: Optional[str] = None) -> None:
    status = "error" if error else "ok"
    conn = get_connection()
    with conn:
        conn.execute(
            """
            UPDATE sync_log
            SET finished_at = datetime('now'), status = ?, rows_upserted = ?, error_message = ?
            WHERE id = ?
            """,
            (status, rows_upserted, error, log_id),
        )
    conn.close()


def get_last_sync() -> Optional[dict]:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT * FROM sync_log WHERE status != 'running' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row else None
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Income Sources
# ---------------------------------------------------------------------------

def get_income_sources() -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            "SELECT * FROM income_sources ORDER BY id", conn
        )
    finally:
        conn.close()


def add_income_source(name: str, amount: float, frequency: str = "monthly") -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO income_sources (name, amount, frequency) VALUES (?, ?, ?)",
            (name, amount, frequency),
        )
    conn.close()


def update_income_source(source_id: int, name: str, amount: float, frequency: str = "monthly") -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE income_sources SET name = ?, amount = ?, frequency = ? WHERE id = ?",
            (name, amount, frequency, source_id),
        )
    conn.close()


def delete_income_source(source_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM income_sources WHERE id = ?", (source_id,))
    conn.close()


def get_total_monthly_income() -> float:
    """Sum all active income sources, converting each to a monthly equivalent."""
    conn = get_connection()
    try:
        row = conn.execute(
            """
            SELECT COALESCE(SUM(
                CASE COALESCE(frequency, 'monthly')
                    WHEN 'daily'   THEN amount * 365.0 / 12
                    WHEN 'weekly'  THEN amount * 52.0  / 12
                    WHEN 'yearly'  THEN amount / 12.0
                    ELSE amount
                END
            ), 0) AS total
            FROM income_sources
            WHERE is_active = 1
            """
        ).fetchone()
        return float(row[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Fixed Outgoings
# ---------------------------------------------------------------------------

def get_fixed_outgoings() -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            "SELECT * FROM fixed_outgoings ORDER BY id", conn
        )
    finally:
        conn.close()


def add_fixed_outgoing(name: str, amount: float, category: str = "") -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "INSERT INTO fixed_outgoings (name, amount, category) VALUES (?, ?, ?)",
            (name, amount, category),
        )
    conn.close()


def update_fixed_outgoing(outgoing_id: int, name: str, amount: float, category: str = "") -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            "UPDATE fixed_outgoings SET name = ?, amount = ?, category = ? WHERE id = ?",
            (name, amount, category, outgoing_id),
        )
    conn.close()


def delete_fixed_outgoing(outgoing_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("DELETE FROM fixed_outgoings WHERE id = ?", (outgoing_id,))
    conn.close()


def get_total_monthly_outgoings() -> float:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(amount), 0) AS total FROM fixed_outgoings WHERE is_active = 1"
        ).fetchone()
        return float(row[0])
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Savings Goals
# ---------------------------------------------------------------------------

def get_savings_goals() -> pd.DataFrame:
    conn = get_connection()
    try:
        return pd.read_sql_query(
            "SELECT * FROM savings_goals WHERE is_active = 1 ORDER BY id", conn
        )
    finally:
        conn.close()


def add_savings_goal(
    name: str,
    target_amount: float,
    monthly_contribution: float,
    current_amount: float = 0.0,
    deadline: Optional[str] = None,
    color: str = "#4A90D9",
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            INSERT INTO savings_goals
                (name, target_amount, monthly_contribution, current_amount, deadline, color)
            VALUES (?, ?, ?, ?, ?, ?)
            """,
            (name, target_amount, monthly_contribution, current_amount, deadline, color),
        )
    conn.close()


def update_savings_goal(
    goal_id: int,
    name: str,
    target_amount: float,
    monthly_contribution: float,
    current_amount: float,
    deadline: Optional[str] = None,
    color: str = "#4A90D9",
) -> None:
    conn = get_connection()
    with conn:
        conn.execute(
            """
            UPDATE savings_goals SET
                name = ?, target_amount = ?, monthly_contribution = ?,
                current_amount = ?, deadline = ?, color = ?
            WHERE id = ?
            """,
            (name, target_amount, monthly_contribution, current_amount, deadline, color, goal_id),
        )
    conn.close()


def delete_savings_goal(goal_id: int) -> None:
    conn = get_connection()
    with conn:
        conn.execute("UPDATE savings_goals SET is_active = 0 WHERE id = ?", (goal_id,))
    conn.close()


def get_total_monthly_savings_contribution() -> float:
    conn = get_connection()
    try:
        row = conn.execute(
            "SELECT COALESCE(SUM(monthly_contribution), 0) FROM savings_goals WHERE is_active = 1"
        ).fetchone()
        return float(row[0])
    finally:
        conn.close()
