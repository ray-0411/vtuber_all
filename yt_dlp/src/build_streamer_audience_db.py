#!/usr/bin/env python3
"""Build a standalone audience-count database for website DB merging."""

from __future__ import annotations

import argparse
import json
import os
import re
import sqlite3
import subprocess
import sys
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

from twitch_collector import get_app_access_token, request_json


DEFAULT_CONFIG_DATABASE = "streamer_config.db"
DEFAULT_PREVIEW_DATABASE = (
    "import_previews/taiwan_vtuber_yt20k_tw10k_preview.db"
)
DEFAULT_OUTPUT_DATABASE = "streamer_audience.db"
YOUTUBE_HELPER = Path(__file__).with_name("youtube_audience_ytjs.mjs")
TWITCH_USERS_URL = "https://api.twitch.tv/helix/users"
TWITCH_FOLLOWERS_URL = "https://api.twitch.tv/helix/channels/followers"
STATISTICS_AT_PATTERN = re.compile(r"(?:^|; )statistics_at=([^;]+)")


def utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds").replace("+00:00", "Z")


def read_enabled_streamers(database: str) -> list[dict[str, object]]:
    rows: list[dict[str, object]] = []
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        tables = conn.execute(
            """
            SELECT name
            FROM sqlite_master
            WHERE type = 'table' AND name LIKE 'streamer_%'
            ORDER BY name
            """
        ).fetchall()
        for table_row in tables:
            table = table_row["name"]
            columns = {
                row["name"]
                for row in conn.execute(f'PRAGMA table_info("{table}")')
            }
            required = {
                "vtuber_id",
                "name",
                "youtube_channel_id",
                "twitch_login",
                "enabled",
            }
            if not required.issubset(columns):
                continue
            for row in conn.execute(
                f"""
                SELECT vtuber_id, name, youtube_url, youtube_channel_id, twitch_login
                FROM "{table}"
                WHERE enabled <> 0
                ORDER BY display_order, vtuber_id
                """
            ):
                rows.append(
                    {
                        "vtuber_id": row["vtuber_id"],
                        "name": row["name"],
                        "group_table": table,
                        "youtube_url": row["youtube_url"],
                        "youtube_channel_id": row["youtube_channel_id"],
                        "twitch_login": row["twitch_login"],
                    }
                )
    return rows


def preview_indexes(database: str) -> tuple[dict[str, sqlite3.Row], dict[str, sqlite3.Row]]:
    with sqlite3.connect(database) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM streamer_other").fetchall()
    youtube = {
        row["youtube_channel_id"]: row
        for row in rows
        if row["youtube_channel_id"]
    }
    twitch = {
        row["twitch_login"].lower(): row
        for row in rows
        if row["twitch_login"]
    }
    return youtube, twitch


def statistics_at(row: sqlite3.Row | None) -> str | None:
    if row is None:
        return None
    match = STATISTICS_AT_PATTERN.search(row["note"] or "")
    return match.group(1) if match else row["updated_at"]


def fetch_missing_twitch_followers(
    logins: list[str],
    client_id: str,
    client_secret: str,
) -> tuple[dict[str, int], dict[str, str]]:
    if not logins:
        return {}, {}
    token = get_app_access_token(client_id, client_secret)
    headers = {
        "Client-Id": client_id,
        "Authorization": f"Bearer {token}",
    }
    users_by_login: dict[str, dict[str, object]] = {}
    for start in range(0, len(logins), 100):
        params = [("login", login) for login in logins[start : start + 100]]
        data, _ = request_json(
            f"{TWITCH_USERS_URL}?{urllib.parse.urlencode(params)}",
            headers=headers,
        )
        users_by_login.update(
            {item["login"].lower(): item for item in data.get("data", [])}
        )

    counts: dict[str, int] = {}
    errors: dict[str, str] = {}
    for login in logins:
        user = users_by_login.get(login.lower())
        if user is None:
            errors[login] = "Twitch account not found"
            continue
        try:
            data, _ = request_json(
                f"{TWITCH_FOLLOWERS_URL}?{urllib.parse.urlencode({'broadcaster_id': user['id'], 'first': 1})}",
                headers=headers,
            )
            total = data.get("total")
            if total is None:
                errors[login] = "Twitch API response did not contain total"
            else:
                counts[login] = int(total)
        except Exception as error:  # Preserve per-account failures in the output DB.
            errors[login] = f"{type(error).__name__}: {error}"
    return counts, errors


def fetch_missing_youtube_counts(
    rows: list[dict[str, object]],
) -> tuple[dict[str, dict[str, object]], dict[str, str]]:
    if not rows:
        return {}, {}
    process = subprocess.run(
        ["node", str(YOUTUBE_HELPER)],
        input=json.dumps(rows, ensure_ascii=False),
        capture_output=True,
        text=True,
        encoding="utf-8",
        errors="replace",
        timeout=180,
        check=False,
        env=os.environ.copy(),
    )
    if process.returncode != 0:
        message = process.stderr.strip() or process.stdout.strip()
        return {}, {
            str(row["vtuber_id"]): f"YouTube helper failed: {message}"
            for row in rows
        }
    payload = json.loads(process.stdout)
    fetched: dict[str, dict[str, object]] = {}
    errors: dict[str, str] = {}
    for item in payload.get("results", []):
        vtuber_id = str(item.get("vtuber_id") or "")
        if not vtuber_id:
            continue
        if item.get("error"):
            errors[vtuber_id] = str(item["error"])
        else:
            fetched[vtuber_id] = item
    return fetched, errors


def initialize_output(conn: sqlite3.Connection) -> None:
    conn.executescript(
        """
        CREATE TABLE IF NOT EXISTS streamer_audience (
            vtuber_id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            group_table TEXT NOT NULL,
            youtube_url TEXT,
            youtube_channel_id TEXT,
            youtube_subscribers INTEGER,
            youtube_source TEXT,
            youtube_count_at TEXT,
            youtube_error TEXT,
            youtube_avatar_url TEXT,
            youtube_avatar_width INTEGER,
            youtube_avatar_height INTEGER,
            youtube_avatar_source TEXT,
            youtube_avatar_at TEXT,
            youtube_avatar_error TEXT,
            twitch_login TEXT,
            twitch_followers INTEGER,
            twitch_source TEXT,
            twitch_count_at TEXT,
            twitch_error TEXT,
            twitch_avatar_url TEXT,
            twitch_avatar_source TEXT,
            twitch_avatar_at TEXT,
            twitch_avatar_error TEXT,
            updated_at TEXT NOT NULL
        );

        CREATE UNIQUE INDEX IF NOT EXISTS idx_streamer_audience_youtube_channel
        ON streamer_audience (youtube_channel_id)
        WHERE youtube_channel_id IS NOT NULL;

        CREATE UNIQUE INDEX IF NOT EXISTS idx_streamer_audience_twitch_login
        ON streamer_audience (twitch_login)
        WHERE twitch_login IS NOT NULL;

        CREATE TABLE IF NOT EXISTS audience_build_info (
            key TEXT PRIMARY KEY,
            value TEXT NOT NULL
        );

        """
    )
    columns = {
        row[1] for row in conn.execute("PRAGMA table_info(streamer_audience)")
    }
    additions = {
        "youtube_url": "TEXT",
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


def build_database(
    config_database: str,
    preview_database: str,
    output_database: str,
    fetch_missing_twitch: bool,
    fetch_missing_youtube: bool,
) -> dict[str, int]:
    streamers = read_enabled_streamers(config_database)
    youtube_preview, twitch_preview = preview_indexes(preview_database)
    built_at = utc_now()
    output_rows: list[dict[str, object]] = []

    for streamer in streamers:
        youtube_row = youtube_preview.get(streamer["youtube_channel_id"])
        twitch_login = streamer["twitch_login"]
        twitch_row = twitch_preview.get(str(twitch_login).lower()) if twitch_login else None
        output_rows.append(
            {
                **streamer,
                "youtube_subscribers": (
                    youtube_row["youtube_subscribers"] if youtube_row else None
                ),
                "youtube_source": "TaiwanVtuberData" if youtube_row else None,
                "youtube_count_at": statistics_at(youtube_row),
                "youtube_error": None,
                "twitch_followers": twitch_row["twitch_followers"] if twitch_row else None,
                "twitch_source": "TaiwanVtuberData" if twitch_row else None,
                "twitch_count_at": statistics_at(twitch_row),
                "twitch_error": None,
                "updated_at": built_at,
            }
        )

    missing_twitch = sorted(
        {
            str(row["twitch_login"])
            for row in output_rows
            if row["twitch_login"] and row["twitch_followers"] is None
        }
    )
    fetched: dict[str, int] = {}
    fetch_errors: dict[str, str] = {}
    if fetch_missing_twitch and missing_twitch:
        client_id = os.environ.get("TWITCH_CLIENT_ID")
        client_secret = os.environ.get("TWITCH_CLIENT_SECRET")
        if client_id and client_secret:
            fetched, fetch_errors = fetch_missing_twitch_followers(
                missing_twitch, client_id, client_secret
            )
        else:
            fetch_errors = {
                login: "TWITCH_CLIENT_ID or TWITCH_CLIENT_SECRET is not set"
                for login in missing_twitch
            }

    for row in output_rows:
        login = str(row["twitch_login"] or "")
        if login in fetched:
            row["twitch_followers"] = fetched[login]
            row["twitch_source"] = "Twitch Helix API"
            row["twitch_count_at"] = built_at
        elif login in fetch_errors:
            row["twitch_error"] = fetch_errors[login]

    missing_youtube_rows = [
        {
            "vtuber_id": row["vtuber_id"],
            "youtube_url": row["youtube_url"],
        }
        for row in output_rows
        if row["youtube_url"] and row["youtube_subscribers"] is None
    ]
    youtube_fetched: dict[str, dict[str, object]] = {}
    youtube_fetch_errors: dict[str, str] = {}
    if fetch_missing_youtube:
        youtube_fetched, youtube_fetch_errors = fetch_missing_youtube_counts(
            missing_youtube_rows
        )
    for row in output_rows:
        vtuber_id = str(row["vtuber_id"])
        item = youtube_fetched.get(vtuber_id)
        if item:
            row["youtube_channel_id"] = item["youtube_channel_id"]
            row["youtube_subscribers"] = item["youtube_subscribers"]
            row["youtube_source"] = "YouTube public channel page (rounded)"
            row["youtube_count_at"] = built_at
        elif vtuber_id in youtube_fetch_errors:
            row["youtube_error"] = youtube_fetch_errors[vtuber_id]

    output_path = Path(output_database)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    with sqlite3.connect(output_path) as conn:
        conn.row_factory = sqlite3.Row
        initialize_output(conn)
        existing_avatars = {
            row["vtuber_id"]: dict(row)
            for row in conn.execute(
                """
                SELECT vtuber_id, youtube_avatar_url, youtube_avatar_width,
                       youtube_avatar_height, youtube_avatar_source,
                       youtube_avatar_at, youtube_avatar_error,
                       twitch_avatar_url, twitch_avatar_source,
                       twitch_avatar_at, twitch_avatar_error
                FROM streamer_audience
                """
            )
        }
        for row in output_rows:
            avatar = existing_avatars.get(str(row["vtuber_id"]), {})
            for column in (
                "youtube_avatar_url",
                "youtube_avatar_width",
                "youtube_avatar_height",
                "youtube_avatar_source",
                "youtube_avatar_at",
                "youtube_avatar_error",
                "twitch_avatar_url",
                "twitch_avatar_source",
                "twitch_avatar_at",
                "twitch_avatar_error",
            ):
                row[column] = avatar.get(column)
        conn.execute("DELETE FROM streamer_audience")
        conn.executemany(
            """
            INSERT INTO streamer_audience (
                vtuber_id, name, group_table, youtube_url,
                youtube_channel_id, youtube_subscribers, youtube_source,
                youtube_count_at, youtube_error,
                youtube_avatar_url, youtube_avatar_width, youtube_avatar_height,
                youtube_avatar_source, youtube_avatar_at, youtube_avatar_error,
                twitch_login, twitch_followers, twitch_source,
                twitch_count_at, twitch_error,
                twitch_avatar_url, twitch_avatar_source,
                twitch_avatar_at, twitch_avatar_error,
                updated_at
            ) VALUES (
                :vtuber_id, :name, :group_table, :youtube_url,
                :youtube_channel_id, :youtube_subscribers, :youtube_source,
                :youtube_count_at, :youtube_error,
                :youtube_avatar_url, :youtube_avatar_width, :youtube_avatar_height,
                :youtube_avatar_source, :youtube_avatar_at, :youtube_avatar_error,
                :twitch_login, :twitch_followers, :twitch_source,
                :twitch_count_at, :twitch_error,
                :twitch_avatar_url, :twitch_avatar_source,
                :twitch_avatar_at, :twitch_avatar_error,
                :updated_at
            )
            """,
            output_rows,
        )
        info = {
            "built_at": built_at,
            "config_database": config_database,
            "preview_database": preview_database,
            "enabled_streamers": str(len(output_rows)),
            "schema_version": "2",
        }
        conn.executemany(
            """
            INSERT INTO audience_build_info (key, value) VALUES (?, ?)
            ON CONFLICT(key) DO UPDATE SET value = excluded.value
            """,
            info.items(),
        )

    return {
        "streamers": len(output_rows),
        "youtube_accounts": sum(bool(row["youtube_channel_id"]) for row in output_rows),
        "youtube_counts": sum(row["youtube_subscribers"] is not None for row in output_rows),
        "twitch_accounts": sum(bool(row["twitch_login"]) for row in output_rows),
        "twitch_counts": sum(row["twitch_followers"] is not None for row in output_rows),
        "twitch_fetched": len(fetched),
        "youtube_fetched": len(youtube_fetched),
        "errors": sum(
            bool(row["youtube_error"] or row["twitch_error"]) for row in output_rows
        ),
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Build standalone streamer subscriber/follower DB."
    )
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument("--preview-database", default=DEFAULT_PREVIEW_DATABASE)
    parser.add_argument("--output-database", default=DEFAULT_OUTPUT_DATABASE)
    parser.add_argument(
        "--no-fetch-missing-youtube",
        action="store_true",
        help="Do not use YouTube.js for missing public subscriber counts.",
    )
    parser.add_argument(
        "--no-fetch-missing-twitch",
        action="store_true",
        help="Do not call Twitch Helix API for missing follower counts.",
    )
    args = parser.parse_args()
    summary = build_database(
        args.config_database,
        args.preview_database,
        args.output_database,
        not args.no_fetch_missing_twitch,
        not args.no_fetch_missing_youtube,
    )
    print(f"Created {args.output_database}")
    for key, value in summary.items():
        print(f"{key}: {value}")
    return 0 if summary["errors"] == 0 else 1


if __name__ == "__main__":
    sys.exit(main())
