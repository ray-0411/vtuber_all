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


API_TABLES = (
    "youtube_websub_subscription",
    "youtube_websub_event",
    "youtube_api_candidate",
    "youtube_api_snapshot",
    "youtube_api_current_status",
)


def table_exists(conn: sqlite3.Connection, schema: str, table: str) -> bool:
    row = conn.execute(
        f"""
        SELECT 1
        FROM {schema}.sqlite_master
        WHERE type = 'table'
          AND name = ?
        """,
        (table,),
    ).fetchone()
    return row is not None


def migrate_youtube_api_data(
    source_database: str,
    target_database: str,
    config_database: str | None,
) -> dict[str, int]:
    init_youtube_api_database(target_database, config_database)
    source_uri = Path(source_database).resolve().as_uri() + "?mode=ro"
    copied: dict[str, int] = {}
    with closing(sqlite3.connect(target_database, timeout=30, uri=True)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        conn.execute("ATTACH DATABASE ? AS source_db", (source_uri,))
        try:
            for table in API_TABLES:
                if not table_exists(conn, "source_db", table):
                    copied[table] = 0
                    continue
                columns = [
                    str(row[1])
                    for row in conn.execute(f"PRAGMA main.table_info({table})")
                ]
                column_sql = ", ".join(f'"{column}"' for column in columns)
                before = conn.total_changes
                conn.execute(
                    f"""
                    INSERT OR IGNORE INTO main.{table} ({column_sql})
                    SELECT {column_sql}
                    FROM source_db.{table}
                    """
                )
                copied[table] = conn.total_changes - before
            conn.commit()
        finally:
            conn.execute("DETACH DATABASE source_db")
    return copied


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Copy existing WebSub/API data out of live_data.db."
    )
    parser.add_argument("--source-database", default="live_data.db")
    parser.add_argument("--target-database", default=DEFAULT_API_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    args = parser.parse_args()

    copied = migrate_youtube_api_data(
        args.source_database,
        args.target_database,
        args.config_database,
    )
    print(f"Source database: {args.source_database}")
    print(f"Target database: {args.target_database}")
    for table, count in copied.items():
        print(f"{table}: copied {count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
