#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import time
from datetime import datetime, timedelta

from time_utils import APP_TIMEZONE_INFO
from youtube_api_collector import collect_youtube_api
from youtube_api_db import DEFAULT_API_DATABASE, DEFAULT_CONFIG_DATABASE


def next_aligned_run(interval_seconds: int) -> datetime:
    now = datetime.now(APP_TIMEZONE_INFO)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed = int((now - day_start).total_seconds())
    next_elapsed = ((elapsed // interval_seconds) + 1) * interval_seconds
    return day_start + timedelta(seconds=next_elapsed)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Run the separate YouTube WebSub/API collector on a schedule."
    )
    parser.add_argument("--database", default=DEFAULT_API_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY"))
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--run-immediately", action="store_true")
    args = parser.parse_args()

    if not args.api_key:
        parser.error("set --api-key or YOUTUBE_API_KEY")
    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be greater than zero")

    first = True
    while True:
        if first and (args.once or args.run_immediately):
            target = datetime.now(APP_TIMEZONE_INFO)
        else:
            target = next_aligned_run(args.interval_seconds)
        wait_seconds = max((target - datetime.now(APP_TIMEZONE_INFO)).total_seconds(), 0)
        if wait_seconds:
            print(f"next YouTube API collection: {target.isoformat(timespec='seconds')}")
            time.sleep(wait_seconds)

        try:
            summary = collect_youtube_api(
                args.database,
                args.api_key,
                config_database=args.config_database,
                limit=args.limit,
                interval_seconds=args.interval_seconds,
            )
            print(json.dumps(summary, ensure_ascii=False))
        except Exception as exc:
            print(f"YouTube API collection failed: {type(exc).__name__}: {exc}")

        if args.once:
            return 0
        first = False


if __name__ == "__main__":
    raise SystemExit(main())
