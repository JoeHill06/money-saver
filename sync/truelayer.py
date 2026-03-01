"""
TrueLayer OAuth2 + Data API helpers.
Refactored from fetch_transactions.py with added token refresh and DB integration.
"""

import os
import threading
import time
import urllib.parse
import webbrowser
from datetime import date, timedelta
from http.server import BaseHTTPRequestHandler, HTTPServer

import requests
from dotenv import load_dotenv

import db.queries as queries
from db.queries import (
    add_connection, get_all_connections, update_connection_tokens,
    log_sync_finish, log_sync_start, upsert_accounts, upsert_transactions,
)

load_dotenv()

CLIENT_ID = os.environ.get("TRUELAYER_CLIENT_ID", "")
CLIENT_SECRET = os.environ.get("TRUELAYER_CLIENT_SECRET", "")
REDIRECT_URI = os.getenv("TRUELAYER_REDIRECT_URI", "http://localhost:3000/callback")
USE_SANDBOX = os.getenv("USE_SANDBOX", "true").lower() == "true"

AUTH_BASE = "https://auth.truelayer-sandbox.com" if USE_SANDBOX else "https://auth.truelayer.com"
API_BASE = "https://api.truelayer-sandbox.com" if USE_SANDBOX else "https://api.truelayer.com"

CALLBACK_PORT = int(urllib.parse.urlparse(REDIRECT_URI).port or 3000)

# How many seconds before expiry we proactively refresh
REFRESH_BUFFER = 300


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


def refresh_access_token(refresh_token: str) -> dict:
    response = requests.post(
        f"{AUTH_BASE}/connect/token",
        data={
            "grant_type": "refresh_token",
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "refresh_token": refresh_token,
        },
        timeout=15,
    )
    response.raise_for_status()
    return response.json()


def get_valid_access_token(connection: dict) -> str:
    """
    Return a valid access token for the given connection dict,
    refreshing silently if within REFRESH_BUFFER seconds of expiry.
    """
    if time.time() >= connection["expires_at"] - REFRESH_BUFFER:
        token_data = refresh_access_token(connection["refresh_token"])
        update_connection_tokens(
            connection["id"],
            token_data["access_token"],
            token_data.get("refresh_token", connection["refresh_token"]),
            token_data.get("expires_in", 3600),
        )
        return token_data["access_token"]

    return connection["access_token"]


def run_local_callback_server() -> tuple[list, threading.Event]:
    """
    Start a temporary local server that captures ?code= from TrueLayer's redirect.
    Returns (auth_code_list, code_received_event).
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
                    b"<p>You can close this tab and return to the dashboard.</p>"
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


def run_oauth_flow(label: str = "My Bank") -> bool:
    """
    Full auth flow: open browser, wait for callback, exchange code,
    save as a new bank connection in DB. Returns True on success.
    """
    auth_codes, code_received = run_local_callback_server()
    auth_url = build_auth_url()
    webbrowser.open(auth_url)

    # Wait up to 5 minutes for user to authorise
    code_received.wait(timeout=300)

    if not auth_codes:
        return False

    token_data = exchange_code_for_token(auth_codes[0])
    add_connection(
        label,
        token_data["access_token"],
        token_data.get("refresh_token", ""),
        token_data.get("expires_in", 3600),
    )
    return True


# ---------------------------------------------------------------------------
# TrueLayer Data API
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


def fetch_transactions_for_account(
    token: str, account_id: str, from_date: str, to_date: str
) -> list[dict]:
    return api_get(
        f"accounts/{account_id}/transactions",
        token,
        params={"from": from_date, "to": to_date},
    )


# ---------------------------------------------------------------------------
# Sync orchestration
# ---------------------------------------------------------------------------

def run_sync(days_back: int = 90) -> dict:
    """
    Fetch accounts + transactions for all connected banks and upsert into the DB.
    Returns a summary dict with 'rows_upserted' and optional 'error'.
    """
    log_id = log_sync_start()
    try:
        connections = get_all_connections()
        if not connections:
            raise RuntimeError("No bank connections found — connect a bank first.")

        today = date.today()
        from_date = str(today - timedelta(days=days_back))
        to_date = str(today)

        total_upserted = 0
        for connection in connections:
            token = get_valid_access_token(connection)

            accounts = fetch_accounts(token)
            upsert_accounts(accounts, connection_id=connection["id"])

            for account in accounts:
                account_id = account["account_id"]
                account_name = account.get("display_name", account_id)
                account_type = account.get("account_type", "")
                try:
                    txns = fetch_transactions_for_account(token, account_id, from_date, to_date)
                except requests.HTTPError:
                    continue

                for txn in txns:
                    txn.setdefault("account_id", account_id)
                    txn.setdefault("account_name", account_name)
                    txn.setdefault("account_type", account_type)

                total_upserted += upsert_transactions(txns)

        log_sync_finish(log_id, total_upserted)
        return {"rows_upserted": total_upserted}

    except Exception as exc:
        log_sync_finish(log_id, 0, str(exc))
        return {"rows_upserted": 0, "error": str(exc)}
