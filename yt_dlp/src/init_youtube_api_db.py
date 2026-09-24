#!/usr/bin/env python3
from __future__ import annotations

import argparse

from youtube_api_db import (
    DEFAULT_API_DATABASE,
    DEFAULT_CONFIG_DATABASE,
    init_youtube_api_database,
)


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Initialize the separate YouTube WebSub/API database."
    )
    parser.add_argument("--database", default=DEFAULT_API_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    args = parser.parse_args()

    files = init_youtube_api_database(args.database, args.config_database)
    print(f"YouTube API database: {args.database}")
    print(f"Streamer config database: {args.config_database}")
    print("Initialized SQL:")
    for file_name in files:
        print(f"- {file_name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

