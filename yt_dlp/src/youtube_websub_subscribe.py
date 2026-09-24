#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from dataclasses import dataclass

from time_utils import now_db_time
from youtube_api_db import (
    DEFAULT_API_DATABASE,
    DEFAULT_CONFIG_DATABASE,
    init_youtube_api_database,
)
from youtube_websub_common import callback_with_token, topic_url


DEFAULT_DATABASE = DEFAULT_API_DATABASE
DEFAULT_HUB_URL = "https://pubsubhubbub.appspot.com/subscribe"


@dataclass(frozen=True)
class Channel:
    vtuber_id: str
    name: str
    channel_id: str


def read_channels(
    conn: sqlite3.Connection,
    selected_channel_ids: set[str],
) -> list[Channel]:
    rows = conn.execute(
        """
        SELECT vtuber_id, name, youtube_channel_id
        FROM streamer
        WHERE enabled = 1
          AND youtube_channel_id IS NOT NULL
          AND trim(youtube_channel_id) <> ''
        ORDER BY vtuber_id
        """
    ).fetchall()
    return [
        Channel(str(row[0]), str(row[1]), str(row[2]))
        for row in rows
        if not selected_channel_ids or str(row[2]) in selected_channel_ids
    ]


def filter_due_channels(
    conn: sqlite3.Connection,
    channels: list[Channel],
    due_within_hours: int | None,
) -> list[Channel]:
    if due_within_hours is None:
        return channels
    rows = conn.execute(
        """
        SELECT channel_id
        FROM youtube_websub_subscription
        WHERE status = 'verified'
          AND expires_at IS NOT NULL
          AND expires_at > datetime('now', '+8 hours', ?)
        """,
        (f"+{due_within_hours} hours",),
    ).fetchall()
    healthy = {str(row[0]) for row in rows}
    return [channel for channel in channels if channel.channel_id not in healthy]


def request_subscription(
    hub_url: str,
    callback_url: str,
    channel_id: str,
    mode: str,
    timeout: float,
) -> int:
    body = urllib.parse.urlencode(
        {
            "hub.callback": callback_url,
            "hub.mode": mode,
            "hub.topic": topic_url(channel_id),
            "hub.verify": "async",
        }
    ).encode("ascii")
    request = urllib.request.Request(
        hub_url,
        data=body,
        headers={"Content-Type": "application/x-www-form-urlencoded"},
        method="POST",
    )
    with urllib.request.urlopen(request, timeout=timeout) as response:
        return int(response.status)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Subscribe tracked YouTube channels to WebSub."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument(
        "--callback-url",
        default=os.environ.get("YOUTUBE_WEBHOOK_CALLBACK_URL", ""),
    )
    parser.add_argument(
        "--webhook-token",
        default=os.environ.get("YOUTUBE_WEBHOOK_TOKEN"),
    )
    parser.add_argument("--hub-url", default=DEFAULT_HUB_URL)
    parser.add_argument(
        "--mode",
        choices=("subscribe", "unsubscribe"),
        default="subscribe",
    )
    parser.add_argument("--channel-id", action="append", default=[])
    parser.add_argument("--timeout", type=float, default=20)
    parser.add_argument(
        "--due-within-hours",
        type=int,
        help="only subscribe missing, unverified, or expiring channels",
    )
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    if not args.callback_url:
        parser.error("set --callback-url or YOUTUBE_WEBHOOK_CALLBACK_URL")
    if not args.callback_url.startswith("https://"):
        parser.error("the public callback URL must use HTTPS")

    callback_url = callback_with_token(args.callback_url, args.webhook_token)
    init_youtube_api_database(args.database, args.config_database)
    selected = set(args.channel_id)
    succeeded = 0
    failed = 0
    with closing(sqlite3.connect(args.database, timeout=30)) as conn:
        channels = read_channels(conn, selected)
        if args.mode == "subscribe":
            channels = filter_due_channels(conn, channels, args.due_within_hours)
        if selected:
            found = {channel.channel_id for channel in channels}
            missing = sorted(selected - found)
            if missing:
                parser.error(f"unknown or disabled channel id(s): {', '.join(missing)}")

        for index, channel in enumerate(channels, 1):
            print(
                f"[{index}/{len(channels)}] {args.mode} "
                f"{channel.vtuber_id} {channel.channel_id}"
            )
            if args.dry_run:
                continue
            try:
                conn.execute(
                    """
                    INSERT INTO youtube_websub_subscription (
                        channel_id,
                        vtuber_id,
                        callback_url,
                        topic_url,
                        status,
                        requested_at,
                        last_error
                    )
                    VALUES (?, ?, ?, ?, 'pending', ?, NULL)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        vtuber_id = excluded.vtuber_id,
                        callback_url = excluded.callback_url,
                        topic_url = excluded.topic_url,
                        status = 'pending',
                        requested_at = excluded.requested_at,
                        last_error = NULL
                    """,
                    (
                        channel.channel_id,
                        channel.vtuber_id,
                        args.callback_url,
                        topic_url(channel.channel_id),
                        now_db_time(),
                    ),
                )
                conn.commit()
                status = request_subscription(
                    args.hub_url,
                    callback_url,
                    channel.channel_id,
                    args.mode,
                    args.timeout,
                )
                if status not in {202, 204}:
                    raise RuntimeError(f"hub returned HTTP {status}")
                succeeded += 1
            except (OSError, urllib.error.HTTPError, RuntimeError) as exc:
                conn.execute(
                    """
                    INSERT INTO youtube_websub_subscription (
                        channel_id,
                        vtuber_id,
                        callback_url,
                        topic_url,
                        status,
                        requested_at,
                        last_error
                    )
                    VALUES (?, ?, ?, ?, 'error', ?, ?)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        status = 'error',
                        requested_at = excluded.requested_at,
                        last_error = excluded.last_error
                    """,
                    (
                        channel.channel_id,
                        channel.vtuber_id,
                        args.callback_url,
                        topic_url(channel.channel_id),
                        now_db_time(),
                        str(exc),
                    ),
                )
                conn.commit()
                failed += 1
                print(f"  ERROR: {exc}")

    print(
        f"channels={len(channels)} succeeded={succeeded} failed={failed} "
        f"dry_run={args.dry_run}"
    )
    return 1 if failed else 0


if __name__ == "__main__":
    raise SystemExit(main())
