#!/usr/bin/env python3
from __future__ import annotations

import argparse
import sqlite3
from contextlib import closing
from pathlib import Path

from youtube_api_db import (
    DEFAULT_API_DATABASE,
    DEFAULT_CONFIG_DATABASE,
    init_youtube_api_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Compare the original YouTube collector with the WebSub/API collector."
    )
    parser.add_argument("--live-database", default="live_data.db")
    parser.add_argument("--api-database", default=DEFAULT_API_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument("--differences-only", action="store_true")
    args = parser.parse_args()

    init_youtube_api_database(args.api_database, args.config_database)
    with closing(sqlite3.connect(args.api_database, timeout=30, uri=True)) as conn:
        live_database_uri = Path(args.live_database).resolve().as_uri() + "?mode=ro"
        conn.execute("ATTACH DATABASE ? AS original_db", (live_database_uri,))
        rows = conn.execute(
            """
            SELECT
                streamer.vtuber_id,
                streamer.name,
                COALESCE(original.is_live, 0) AS original_live,
                original.viewer_count AS original_viewers,
                original.stream_url AS original_url,
                COALESCE(official.is_live, 0) AS official_live,
                official.concurrent_viewers AS official_viewers,
                official.video_id AS official_video_id,
                official.last_checked_at AS official_checked_at
            FROM streamer
            LEFT JOIN original_db.current_live_status AS original
              ON original.vtuber_id = streamer.vtuber_id
             AND original.platform = 'youtube'
            LEFT JOIN youtube_api_current_status AS official
              ON official.vtuber_id = streamer.vtuber_id
            WHERE streamer.enabled = 1
              AND streamer.youtube_channel_id IS NOT NULL
              AND trim(streamer.youtube_channel_id) <> ''
            ORDER BY streamer.vtuber_id
            """
        ).fetchall()

    compared = 0
    differences = 0
    for row in rows:
        (
            vtuber_id,
            name,
            original_live,
            original_viewers,
            original_url,
            official_live,
            official_viewers,
            official_video_id,
            official_checked_at,
        ) = row
        has_official_data = official_checked_at is not None
        different = has_official_data and original_live != official_live
        if args.differences_only and not different:
            continue
        compared += int(has_official_data)
        differences += int(different)
        marker = "DIFF" if different else ("OK" if has_official_data else "NO_EVENT")
        print(
            f"{marker:8} {vtuber_id} {name} "
            f"original={original_live}/{original_viewers} "
            f"official={official_live}/{official_viewers} "
            f"video={official_video_id or '-'} "
            f"checked={official_checked_at or '-'}"
        )
        if different and original_url:
            print(f"         original_url={original_url}")

    print(
        f"rows={len(rows)} official_compared={compared} "
        f"live_state_differences={differences}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
