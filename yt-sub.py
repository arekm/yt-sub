#!/usr/bin/env python3
# SPDX-License-Identifier: Unlicense
#
# This file is dedicated to the public domain. See LICENSE for the full text,
# or <https://unlicense.org/> for details.
"""Bulk subscribe to YouTube channels via YouTube Data API v3.

Reads URLs from input.txt, tracks progress in state.db (SQLite), resumes
where it left off on re-run. Stops cleanly on quota exhaustion; just run
again the next day (quota resets ~midnight Pacific).
"""

import argparse
import json
import re
import sqlite3
import sys
import time
from pathlib import Path

# Ensure non-ASCII URLs and API error messages don't crash print() on
# Windows consoles (default codepage cp1252) or any misconfigured locale.
for _stream in (sys.stdout, sys.stderr):
    try:
        _stream.reconfigure(encoding="utf-8", errors="replace")
    except (AttributeError, ValueError):
        pass

from google.auth.transport.requests import Request
from google.oauth2.credentials import Credentials
from google_auth_oauthlib.flow import InstalledAppFlow
from googleapiclient.discovery import build
from googleapiclient.errors import HttpError

SCOPES = ["https://www.googleapis.com/auth/youtube"]
HERE = Path(__file__).parent
CLIENT_SECRET = HERE / "client_secret.json"
TOKEN = HERE / "token.json"
DB = HERE / "state.db"
INPUT = HERE / "input.txt"

SLEEP_BETWEEN = 1.0  # polite delay between insert calls

CHANNEL_ID_RE = re.compile(r"/channel/(UC[\w-]{22})")


def get_credentials():
    creds = None
    if TOKEN.exists():
        creds = Credentials.from_authorized_user_file(str(TOKEN), SCOPES)
    if not creds or not creds.valid:
        if creds and creds.expired and creds.refresh_token:
            creds.refresh(Request())
        else:
            if not CLIENT_SECRET.exists():
                sys.exit(
                    f"missing {CLIENT_SECRET.name} — download OAuth client "
                    "(Desktop) JSON from Google Cloud Console and save it here"
                )
            flow = InstalledAppFlow.from_client_secrets_file(str(CLIENT_SECRET), SCOPES)
            creds = flow.run_local_server(port=0)
        TOKEN.write_text(creds.to_json(), encoding="utf-8")
    return creds


def init_db():
    conn = sqlite3.connect(str(DB))
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS channels (
            url        TEXT PRIMARY KEY,
            channel_id TEXT,
            status     TEXT NOT NULL DEFAULT 'pending',
            error      TEXT,
            updated_at TEXT
        )
        """
    )
    conn.commit()
    return conn


def load_input(conn):
    if not INPUT.exists():
        return 0
    added = 0
    for line in INPUT.read_text(encoding="utf-8").splitlines():
        url = line.strip()
        if not url or url.startswith("#"):
            continue
        m = CHANNEL_ID_RE.search(url)
        if not m:
            print(f"skip (no channel id): {url}")
            continue
        cur = conn.execute(
            "INSERT OR IGNORE INTO channels (url, channel_id) VALUES (?, ?)",
            (url, m.group(1)),
        )
        added += cur.rowcount
    conn.commit()
    return added


def mark(conn, url, status, error=None):
    conn.execute(
        "UPDATE channels SET status=?, error=?, updated_at=datetime('now') WHERE url=?",
        (status, error, url),
    )
    conn.commit()


def extract_reason(e: HttpError) -> str:
    try:
        details = getattr(e, "error_details", None)
        if details and isinstance(details, list) and details:
            r = details[0].get("reason")
            if r:
                return r
    except Exception:
        pass
    try:
        body = json.loads(e.content.decode("utf-8"))
        errs = body.get("error", {}).get("errors", [])
        if errs:
            return errs[0].get("reason", "")
    except Exception:
        pass
    return ""


def subscribe(youtube, channel_id):
    return youtube.subscriptions().insert(
        part="snippet",
        body={
            "snippet": {
                "resourceId": {"kind": "youtube#channel", "channelId": channel_id}
            }
        },
    ).execute()


STOP_REASONS = {"quotaExceeded", "rateLimitExceeded", "userRateLimitExceeded"}
OK_DUP_REASONS = {"subscriptionDuplicate"}
SKIP_REASONS = {
    "subscriberNotFound",
    "channelNotFound",
    "publisherNotFound",
    "accountClosed",
    "accountSuspended",
}


def counts(conn):
    rows = conn.execute(
        "SELECT status, COUNT(*) FROM channels GROUP BY status"
    ).fetchall()
    by_status = {s: 0 for s in ("pending", "done", "skipped", "error")}
    for s, c in rows:
        by_status[s] = c
    by_status["total"] = sum(by_status.values())
    return by_status


def print_status(conn):
    c = counts(conn)
    if c["total"] == 0:
        print("no state yet — add URLs to input.txt and run the script")
        return
    pct = int(round(100 * c["done"] / c["total"]))
    print(
        f"total: {c['total']} | done: {c['done']} ({pct}%) | "
        f"pending: {c['pending']} | skipped: {c['skipped']} | error: {c['error']}"
    )
    errs = conn.execute(
        "SELECT url, error FROM channels WHERE status='error' ORDER BY updated_at"
    ).fetchall()
    if errs:
        print(f"\nprevious errors ({len(errs)}):")
        for url, err in errs:
            print(f"  {url}  {err or ''}")
    skipped = conn.execute(
        "SELECT url, error FROM channels WHERE status='skipped' ORDER BY updated_at"
    ).fetchall()
    if skipped:
        print(f"\nskipped ({len(skipped)}):")
        for url, err in skipped:
            print(f"  {url}  {err or ''}")


def run(conn):
    added = load_input(conn)

    pending = conn.execute(
        "SELECT url, channel_id FROM channels WHERE status='pending'"
    ).fetchall()
    c = counts(conn)
    print(
        f"input: +{added} new | pending: {len(pending)} | done: {c['done']} | "
        f"skipped: {c['skipped']} | error: {c['error']}"
    )
    if not pending:
        return

    creds = get_credentials()
    youtube = build("youtube", "v3", credentials=creds, cache_discovery=False)

    total = len(pending)
    for i, (url, cid) in enumerate(pending, 1):
        try:
            subscribe(youtube, cid)
            mark(conn, url, "done")
            print(f"[{i}/{total}] ok   {cid}")
        except HttpError as e:
            reason = extract_reason(e)
            status = e.resp.status if e.resp is not None else "?"
            msg = f"{status} {reason}".strip()
            if reason in OK_DUP_REASONS:
                mark(conn, url, "done", "already subscribed")
                print(f"[{i}/{total}] dup  {cid}")
            elif reason in SKIP_REASONS:
                mark(conn, url, "skipped", msg)
                print(f"[{i}/{total}] skip {cid}: {msg}")
            elif reason in STOP_REASONS:
                print(f"[{i}/{total}] stop {cid}: {msg} — re-run later")
                return
            else:
                mark(conn, url, "error", msg)
                print(f"[{i}/{total}] err  {cid}: {msg}")
        except Exception as e:
            mark(conn, url, "error", repr(e))
            print(f"[{i}/{total}] err  {cid}: {e!r}")
        time.sleep(SLEEP_BETWEEN)


def main():
    parser = argparse.ArgumentParser(
        description="Bulk subscribe to YouTube channels listed in input.txt."
    )
    parser.add_argument(
        "--status",
        action="store_true",
        help="print progress summary and exit (no API calls)",
    )
    args = parser.parse_args()

    conn = init_db()
    if args.status:
        print_status(conn)
    else:
        run(conn)


if __name__ == "__main__":
    main()
