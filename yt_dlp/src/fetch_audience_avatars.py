#!/usr/bin/env python3
"""Fetch YouTube and Twitch avatar URLs into streamer_audience.db."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

from twitch_collector import get_app_access_token, request_json


DEFAULT_DATABASE = "streamer_audience.db"
HELPER = Path(__file__).with_name("youtube_avatar_ytjs.mjs")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def ensure_columns(conn: sqlite3.Connection) -> None:
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(streamer_audience)")
    }
    additions = {
        "youtube_avatar_url": "TEXT",
        "youtube_avatar_width": "INTEGER",
        "youtube_avatar_height": "INTEGER",
        "youtube_avatar_source": "TEXT",
        "youtube_avatar_at": "TEXT",
        "youtube_avatar_error": "TEXT",
        "twitch_avatar_url": "TEXT",
        "twitch_avatar_source": "TEXT",
        "twitch_avatar_at": "TEXT",
        "twitch_avatar_error": "TEXT",
    }
    for column, data_type in additions.items():
        if column not in columns:
            conn.execute(
                f"ALTER TABLE streamer_audience ADD COLUMN {column} {data_type}"
            )
    conn.executescript(
        """
        DROP VIEW IF EXISTS audience_merge_export;
        CREATE VIEW audience_merge_export AS
        SELECT
            vtuber_id,
            youtube_subscribers,
            twitch_followers,
            youtube_avatar_url,
            twitch_avatar_url
        FROM streamer_audience;
        """
    )


def fetch_twitch_avatar_results(logins: list[str]) -> dict[str, dict[str, str]]:
    if not logins:
        return {}
    client_id = os.environ.get("TWITCH_CLIENT_ID")
    client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
    if not client_id or not client_secret:
        return {
            login: {
                "error": "TWITCH_CLIENT_ID or TWITCH_CLIENT_SECRET is not set"
            }
            for login in logins
        }

    token = get_app_access_token(client_id, client_secret)
    headers = {
        "Client-Id": client_id,
        "Authorization": f"Bearer {token}",
    }
    found: dict[str, dict[str, str]] = {}
    for start in range(0, len(logins), 100):
        params = [("login", login) for login in logins[start : start + 100]]
        from urllib.parse import urlencode

        data, _ = request_json(
            f"https://api.twitch.tv/helix/users?{urlencode(params)}",
            headers=headers,
        )
        for item in data.get("data", []):
            login = item["login"].lower()
            avatar_url = item.get("profile_image_url")
            found[login] = (
                {"url": avatar_url}
                if avatar_url
                else {"error": "Twitch profile image URL is empty"}
            )
    for login in logins:
        found.setdefault(login.lower(), {"error": "Twitch account not found"})
    return found


def fetch_avatars(database: str, refresh: bool = False) -> dict[str, int]:
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        ensure_columns(conn)
        where = "youtube_channel_id IS NOT NULL AND trim(youtube_channel_id) <> ''"
        if not refresh:
            where += " AND youtube_avatar_url IS NULL"
        youtube_rows = conn.execute(
            f"""
            SELECT vtuber_id, youtube_channel_id, youtube_url
            FROM streamer_audience
            WHERE {where}
            ORDER BY vtuber_id
            """
        ).fetchall()
        youtube_payload = [dict(row) for row in youtube_rows]
        twitch_where = "twitch_login IS NOT NULL AND trim(twitch_login) <> ''"
        if not refresh:
            twitch_where += " AND twitch_avatar_url IS NULL"
        twitch_rows = conn.execute(
            f"""
            SELECT vtuber_id, twitch_login
            FROM streamer_audience
            WHERE {twitch_where}
            ORDER BY vtuber_id
            """
        ).fetchall()
        conn.commit()

    youtube_results: list[dict[str, object]] = []
    if youtube_payload:
        process = subprocess.run(
            ["node", str(HELPER)],
            input=json.dumps(youtube_payload, ensure_ascii=False),
            capture_output=True,
            text=True,
            encoding="utf-8",
            errors="replace",
            timeout=300,
            check=False,
            env=os.environ.copy(),
        )
        if process.returncode != 0:
            raise RuntimeError(
                "YouTube avatar helper failed: "
                + (process.stderr.strip() or process.stdout.strip())
            )
        youtube_results = json.loads(process.stdout).get("results", [])

    twitch_results = fetch_twitch_avatar_results(
        [row["twitch_login"].lower() for row in twitch_rows]
    )
    fetched_at = utc_now()
    youtube_updated = 0
    youtube_failed = 0
    twitch_updated = 0
    twitch_failed = 0
    with sqlite3.connect(database) as conn:
        ensure_columns(conn)
        for item in youtube_results:
            vtuber_id = item.get("vtuber_id")
            if not vtuber_id:
                continue
            if item.get("error"):
                youtube_failed += 1
                conn.execute(
                    """
                    UPDATE streamer_audience
                    SET youtube_avatar_error = ?, youtube_avatar_at = ?
                    WHERE vtuber_id = ?
                    """,
                    (item["error"], fetched_at, vtuber_id),
                )
                continue
            youtube_updated += 1
            conn.execute(
                """
                UPDATE streamer_audience
                SET youtube_channel_id = ?,
                    youtube_avatar_url = ?,
                    youtube_avatar_width = ?,
                    youtube_avatar_height = ?,
                    youtube_avatar_source = 'YouTube public channel page',
                    youtube_avatar_at = ?,
                    youtube_avatar_error = NULL,
                    updated_at = ?
                WHERE vtuber_id = ?
                """,
                (
                    item["youtube_channel_id"],
                    item["youtube_avatar_url"],
                    item.get("youtube_avatar_width"),
                    item.get("youtube_avatar_height"),
                    fetched_at,
                    fetched_at,
                    vtuber_id,
                ),
            )
        for row in twitch_rows:
            vtuber_id = row["vtuber_id"]
            login = row["twitch_login"].lower()
            item = twitch_results[login]
            if item.get("error"):
                twitch_failed += 1
                conn.execute(
                    """
                    UPDATE streamer_audience
                    SET twitch_avatar_error = ?, twitch_avatar_at = ?
                    WHERE vtuber_id = ?
                    """,
                    (item["error"], fetched_at, vtuber_id),
                )
                continue
            twitch_updated += 1
            conn.execute(
                """
                UPDATE streamer_audience
                SET twitch_avatar_url = ?,
                    twitch_avatar_source = 'Twitch Helix API',
                    twitch_avatar_at = ?,
                    twitch_avatar_error = NULL,
                    updated_at = ?
                WHERE vtuber_id = ?
                """,
                (item["url"], fetched_at, fetched_at, vtuber_id),
            )

    return {
        "youtube_checked": len(youtube_payload),
        "youtube_updated": youtube_updated,
        "youtube_failed": youtube_failed,
        "twitch_checked": len(twitch_rows),
        "twitch_updated": twitch_updated,
        "twitch_failed": twitch_failed,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Fetch YouTube and Twitch avatar URLs into streamer_audience.db."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument(
        "--refresh",
        action="store_true",
        help="Refresh avatars that already have a URL.",
    )
    args = parser.parse_args()
    summary = fetch_avatars(args.database, args.refresh)
    print(
        "youtube: checked={youtube_checked} updated={youtube_updated} "
        "failed={youtube_failed}".format(**summary)
    )
    print(
        "twitch: checked={twitch_checked} updated={twitch_updated} "
        "failed={twitch_failed}".format(**summary)
    )
    return 1 if summary["youtube_failed"] or summary["twitch_failed"] else 0


if __name__ == "__main__":
    sys.exit(main())
