"""
Database schema: connection, table creation, and CSV seeding.
"""

import csv
import os
import sqlite3

DB_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "finance.db")


def get_connection() -> sqlite3.Connection:
    """Return a WAL-mode connection safe for multi-thread use."""
    conn = sqlite3.connect(DB_PATH, check_same_thread=False)
    conn.execute("PRAGMA journal_mode=WAL")
    conn.row_factory = sqlite3.Row
    return conn


def create_tables() -> None:
    conn = get_connection()
    with conn:
        conn.executescript("""
            CREATE TABLE IF NOT EXISTS tokens (
                id              INTEGER PRIMARY KEY CHECK (id = 1),
                access_token    TEXT NOT NULL,
                refresh_token   TEXT NOT NULL,
                expires_at      REAL NOT NULL
            );

            CREATE TABLE IF NOT EXISTS accounts (
                account_id      TEXT PRIMARY KEY,
                account_name    TEXT,
                account_type    TEXT,
                currency        TEXT
            );

            CREATE TABLE IF NOT EXISTS transactions (
                transaction_id      TEXT PRIMARY KEY,
                account_id          TEXT,
                account_name        TEXT,
                account_type        TEXT,
                timestamp           TEXT,
                description         TEXT,
                amount              REAL,
                currency            TEXT,
                transaction_type    TEXT,
                category            TEXT,
                merchant_name       TEXT,
                is_shared           INTEGER DEFAULT 0,
                notes               TEXT,
                FOREIGN KEY (account_id) REFERENCES accounts(account_id)
            );

            CREATE TABLE IF NOT EXISTS debts (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                direction       TEXT NOT NULL CHECK (direction IN ('i_owe', 'they_owe')),
                person_name     TEXT NOT NULL,
                amount          REAL NOT NULL,
                description     TEXT,
                created_at      TEXT DEFAULT (datetime('now')),
                is_settled      INTEGER DEFAULT 0,
                settled_at      TEXT
            );

            CREATE TABLE IF NOT EXISTS shared_transactions (
                id                  INTEGER PRIMARY KEY AUTOINCREMENT,
                transaction_id      TEXT NOT NULL,
                person_name         TEXT NOT NULL,
                their_share_pct     REAL NOT NULL,
                their_share_amount  REAL NOT NULL,
                is_settled          INTEGER DEFAULT 0,
                settled_at          TEXT,
                FOREIGN KEY (transaction_id) REFERENCES transactions(transaction_id)
            );

            CREATE TABLE IF NOT EXISTS budget_months (
                year_month      TEXT PRIMARY KEY,
                monthly_income  REAL DEFAULT 0,
                savings_goal    REAL DEFAULT 0
            );

            CREATE TABLE IF NOT EXISTS budget_categories (
                year_month      TEXT NOT NULL,
                category        TEXT NOT NULL,
                spend_limit     REAL NOT NULL,
                PRIMARY KEY (year_month, category),
                FOREIGN KEY (year_month) REFERENCES budget_months(year_month)
            );

            CREATE TABLE IF NOT EXISTS bank_connections (
                id            INTEGER PRIMARY KEY AUTOINCREMENT,
                label         TEXT NOT NULL DEFAULT 'My Bank',
                access_token  TEXT NOT NULL,
                refresh_token TEXT NOT NULL,
                expires_at    REAL NOT NULL,
                created_at    TEXT DEFAULT (datetime('now'))
            );

            CREATE TABLE IF NOT EXISTS sync_log (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                started_at      TEXT DEFAULT (datetime('now')),
                finished_at     TEXT,
                status          TEXT,
                rows_upserted   INTEGER DEFAULT 0,
                error_message   TEXT
            );

            CREATE TABLE IF NOT EXISTS income_sources (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                amount          REAL NOT NULL,
                is_active       INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS fixed_outgoings (
                id              INTEGER PRIMARY KEY AUTOINCREMENT,
                name            TEXT NOT NULL,
                amount          REAL NOT NULL,
                category        TEXT DEFAULT '',
                is_active       INTEGER DEFAULT 1
            );

            CREATE TABLE IF NOT EXISTS savings_goals (
                id                      INTEGER PRIMARY KEY AUTOINCREMENT,
                name                    TEXT NOT NULL,
                target_amount           REAL NOT NULL,
                monthly_contribution    REAL DEFAULT 0,
                current_amount          REAL DEFAULT 0,
                deadline                TEXT,
                color                   TEXT DEFAULT '#4A90D9',
                is_active               INTEGER DEFAULT 1
            );
        """)
    conn.close()
    _migrate_schema()


def _migrate_schema() -> None:
    """Add columns introduced after initial creation (idempotent)."""
    conn = get_connection()
    migrations = [
        "ALTER TABLE accounts ADD COLUMN bank_name TEXT",
        "ALTER TABLE accounts ADD COLUMN bank_color TEXT DEFAULT '#4A90D9'",
        "ALTER TABLE income_sources ADD COLUMN frequency TEXT DEFAULT 'monthly'",
        "ALTER TABLE accounts ADD COLUMN connection_id INTEGER",
        "ALTER TABLE transactions ADD COLUMN is_excluded INTEGER DEFAULT 0",
    ]
    for sql in migrations:
        try:
            with conn:
                conn.execute(sql)
        except sqlite3.OperationalError:
            pass  # column already exists
    conn.close()
    _migrate_tokens_to_connections()


def _migrate_tokens_to_connections() -> None:
    """One-time migration: copy the legacy single-token row into bank_connections."""
    conn = get_connection()
    try:
        existing = conn.execute("SELECT * FROM tokens WHERE id = 1").fetchone()
        if not existing:
            return
        count = conn.execute("SELECT COUNT(*) FROM bank_connections").fetchone()[0]
        if count > 0:
            return  # already migrated
        with conn:
            conn.execute(
                "INSERT INTO bank_connections (label, access_token, refresh_token, expires_at) "
                "VALUES (?, ?, ?, ?)",
                ("My Bank", existing["access_token"], existing["refresh_token"], existing["expires_at"]),
            )
    finally:
        conn.close()


def seed_from_csv(csv_path: str = "transactions.csv") -> int:
    """
    Seed the transactions table from an existing CSV if the table is empty.
    Returns number of rows inserted (0 if table already had data or CSV not found).
    """
    if not os.path.exists(csv_path):
        return 0

    conn = get_connection()
    try:
        count = conn.execute("SELECT COUNT(*) FROM transactions").fetchone()[0]
        if count > 0:
            return 0

        with open(csv_path, newline="", encoding="utf-8") as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        inserted = 0
        with conn:
            for row in rows:
                try:
                    amount = float(row.get("amount", 0) or 0)
                except ValueError:
                    amount = 0.0
                conn.execute(
                    """
                    INSERT OR IGNORE INTO transactions
                        (transaction_id, account_id, account_name, account_type,
                         timestamp, description, amount, currency,
                         transaction_type, category, merchant_name)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        row.get("transaction_id", ""),
                        row.get("account_id", ""),
                        row.get("account_name", ""),
                        row.get("account_type", ""),
                        row.get("timestamp", ""),
                        row.get("description", ""),
                        amount,
                        row.get("currency", "GBP"),
                        row.get("transaction_type", ""),
                        row.get("transaction_category", ""),
                        row.get("merchant_name", ""),
                    ),
                )
                inserted += 1
        return inserted
    finally:
        conn.close()
