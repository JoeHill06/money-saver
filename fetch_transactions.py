"""
Fetch transactions from all TrueLayer-connected bank accounts and write to the
SQLite database (default) and/or a CSV file.

Usage:
    python fetch_transactions.py                        # last 30 days → DB
    python fetch_transactions.py --from 2025-01-01     # from a date
    python fetch_transactions.py --from 2025-01-01 --to 2025-01-31
    python fetch_transactions.py --output my_data.csv  # also export CSV
    python fetch_transactions.py --csv-only            # CSV only, skip DB write
"""

import argparse
import csv
import os
import sys
import threading
import urllib.parse
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from dotenv import load_dotenv

load_dotenv()

CLIENT_ID = os.environ["TRUELAYER_CLIENT_ID"]
CLIENT_SECRET = os.environ["TRUELAYER_CLIENT_SECRET"]
REDIRECT_URI = os.getenv("TRUELAYER_REDIRECT_URI", "http://localhost:3000/callback")
USE_SANDBOX = os.getenv("USE_SANDBOX", "true").lower() == "true"

AUTH_BASE = "https://auth.truelayer-sandbox.com" if USE_SANDBOX else "https://auth.truelayer.com"
API_BASE = "https://api.truelayer-sandbox.com" if USE_SANDBOX else "https://api.truelayer.com"

CALLBACK_PORT = int(urllib.parse.urlparse(REDIRECT_URI).port or 3000)

CSV_FIELDS = [
    "account_id",
    "account_name",
    "account_type",
    "transaction_id",
    "timestamp",
    "description",
    "amount",
    "currency",
    "transaction_type",
    "transaction_category",
    "merchant_name",
]


# ---------------------------------------------------------------------------
# OAuth2 helpers
# ---------------------------------------------------------------------------

def build_auth_url() -> str:
    params = {
        "response_type": "code",
        "client_id": CLIENT_ID,
        "scope": "accounts transactions offline_access",
        "redirect_uri": REDIRECT_URI,
        "providers": "mock" if USE_SANDBOX else "uk-ob-all uk-oauth-all",
    }
    return f"{AUTH_BASE}/?{urllib.parse.urlencode(params)}"


def exchange_code_for_token(code: str) -> dict:
    response = requests.post(
        f"{AUTH_BASE}/connect/token",
        data={
            "grant_type": "authorization_code",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uri": REDIRECT_URI,
            "code": code,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def run_local_callback_server() -> tuple[list, threading.Event]:
    """
    Start a temporary local server that captures the ?code= from TrueLayer's
    redirect. Returns (auth_code_list, code_received_event).
    """
    auth_code: list[str] = []
    server_ready = threading.Event()
    code_received = threading.Event()

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # suppress request logs

        def do_GET(self):
            parsed = urllib.parse.urlparse(self.path)
            params = urllib.parse.parse_qs(parsed.query)
            if "code" in params:
                auth_code.append(params["code"][0])
                self.send_response(200)
                self.send_header("Content-Type", "text/html")
                self.end_headers()
                self.wfile.write(
                    b"<h2>Authorization successful!</h2>"
                    b"<p>You can close this tab and return to the terminal.</p>"
                )
                code_received.set()
            elif "error" in params:
                error = params.get("error", ["unknown"])[0]
                self.send_response(400)
                self.end_headers()
                self.wfile.write(f"<h2>Error: {error}</h2>".encode())
                code_received.set()
            else:
                self.send_response(404)
                self.end_headers()

    def serve():
        httpd = HTTPServer(("localhost", CALLBACK_PORT), Handler)
        server_ready.set()
        while not code_received.is_set():
            httpd.handle_request()
        httpd.server_close()

    thread = threading.Thread(target=serve, daemon=True)
    thread.start()
    server_ready.wait()
    return auth_code, code_received


# ---------------------------------------------------------------------------
# TrueLayer Data API calls
# ---------------------------------------------------------------------------

def api_get(path: str, token: str, params: dict = None) -> list:
    response = requests.get(
        f"{API_BASE}/data/v1/{path}",
        headers={"Authorization": f"Bearer {token}"},
        params=params or {},
        timeout=20,
    )
    response.raise_for_status()
    return response.json().get("results", [])


def fetch_accounts(token: str) -> list[dict]:
    return api_get("accounts", token)


def fetch_transactions(token: str, account_id: str, from_date: str, to_date: str) -> list[dict]:
    return api_get(
        f"accounts/{account_id}/transactions",
        token,
        params={"from": from_date, "to": to_date},
    )


# ---------------------------------------------------------------------------
# Output helpers
# ---------------------------------------------------------------------------

def write_csv(rows: list[dict], output_path: str):
    with open(output_path, "w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=CSV_FIELDS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)


def write_to_db(all_txn_dicts: list[dict]) -> int:
    """
    Write raw TrueLayer transaction dicts (with account context attached) to the DB.
    Returns the number of rows upserted.
    """
    from db.schema import create_tables
    from db.queries import upsert_accounts, upsert_transactions

    create_tables()

    # Build minimal account records from the transaction data
    accounts_seen: dict[str, dict] = {}
    for txn in all_txn_dicts:
        aid = txn.get("account_id", "")
        if aid and aid not in accounts_seen:
            accounts_seen[aid] = {
                "account_id": aid,
                "display_name": txn.get("account_name", aid),
                "account_type": txn.get("account_type", ""),
                "currency": txn.get("currency", "GBP"),
            }

    if accounts_seen:
        upsert_accounts(list(accounts_seen.values()))

    return upsert_transactions(all_txn_dicts)


# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def parse_args():
    today = date.today()
    parser = argparse.ArgumentParser(description="Fetch TrueLayer transactions.")
    parser.add_argument("--from", dest="from_date", default=str(today - timedelta(days=30)),
                        help="Start date (YYYY-MM-DD). Default: 30 days ago.")
    parser.add_argument("--to", dest="to_date", default=str(today),
                        help="End date (YYYY-MM-DD). Default: today.")
    parser.add_argument("--output", default=None,
                        help="Also export a CSV to this path.")
    parser.add_argument("--csv-only", action="store_true",
                        help="Write CSV only; skip database write.")
    return parser.parse_args()


def main():
    args = parse_args()

    env = "sandbox" if USE_SANDBOX else "production"
    print(f"TrueLayer transaction fetcher ({env})")
    print(f"Date range : {args.from_date} → {args.to_date}")
    if args.output:
        print(f"CSV output : {args.output}")
    if not args.csv_only:
        print("DB output  : finance.db (transactions table)")
    print()

    # Step 1: OAuth2 authorization
    auth_codes, code_received = run_local_callback_server()
    auth_url = build_auth_url()

    print("Opening your browser to authorize with TrueLayer...")
    print(f"If it doesn't open, visit:\n  {auth_url}\n")
    webbrowser.open(auth_url)

    print("Waiting for authorization callback… (ctrl+c to cancel)")
    code_received.wait()

    if not auth_codes:
        print("Authorization failed or was cancelled.")
        sys.exit(1)

    # Step 2: Exchange code for access token
    print("Authorization received. Exchanging code for token...")
    token_data = exchange_code_for_token(auth_codes[0])
    access_token = token_data["access_token"]

    # Step 3: Fetch accounts
    print("Fetching accounts...")
    accounts = fetch_accounts(access_token)
    print(f"Found {len(accounts)} account(s).")

    # Step 4: Fetch transactions per account
    all_rows = []       # CSV format
    all_txn_dicts = []  # raw TrueLayer format with account context

    for account in accounts:
        account_id = account["account_id"]
        account_name = account.get("display_name", account_id)
        account_type = account.get("account_type", "")

        print(f"  Fetching transactions for: {account_name}...")
        try:
            transactions = fetch_transactions(
                access_token, account_id, args.from_date, args.to_date
            )
        except requests.HTTPError as e:
            print(f"    Warning: could not fetch transactions ({e}), skipping.")
            continue

        print(f"    {len(transactions)} transaction(s).")
        for txn in transactions:
            merchant = txn.get("merchant_name") or (txn.get("meta") or {}).get("provider_merchant_name", "")
            category = ""
            if txn.get("transaction_classification"):
                category = txn["transaction_classification"][0]

            all_rows.append({
                "account_id": account_id,
                "account_name": account_name,
                "account_type": account_type,
                "transaction_id": txn.get("transaction_id", ""),
                "timestamp": txn.get("timestamp", ""),
                "description": txn.get("description", ""),
                "amount": txn.get("amount", ""),
                "currency": txn.get("currency", "GBP"),
                "transaction_type": txn.get("transaction_type", ""),
                "transaction_category": category,
                "merchant_name": merchant,
            })

            # Raw dict with account context for DB write
            enriched = dict(txn)
            enriched["account_id"] = account_id
            enriched["account_name"] = account_name
            enriched["account_type"] = account_type
            all_txn_dicts.append(enriched)

    # Step 5: Write to DB (default)
    if not args.csv_only:
        count = write_to_db(all_txn_dicts)
        print(f"\nSaved {count} transaction(s) to finance.db")

    # Step 6: Write CSV if requested
    if args.output:
        write_csv(all_rows, args.output)
        print(f"Saved {len(all_rows)} transaction(s) to: {args.output}")

    if args.csv_only and not args.output:
        print("Warning: --csv-only specified but no --output path given. Nothing written.")


if __name__ == "__main__":
    main()
