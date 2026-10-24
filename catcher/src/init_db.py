#!/usr/bin/env python3
"""
Initialize the project SQLite database.

Usage:
    python src/init_db.py
    python src/init_db.py --database live_data.db
"""

from __future__ import annotations

from project_paths import database_path

import argparse
import json
import sqlite3
from contextlib import closing
from pathlib import Path

from migrate_stream_titles import migrate_stream_titles
from migrate_stream_categories import migrate_stream_categories
from migrate_stream_tags import migrate_stream_tags

DEFAULT_DATABASE = database_path('live_data.db')
CORE_SQL_FILES = [
    "002_streamer.sql",
    "009_stream_category.sql",
    "009_stream_tags.sql",
    "009_stream_title.sql",
    "010_stream.sql",
    "011_stream_snapshot.sql",
    "012_current_live_status.sql",
    "013_working.sql",
]


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def run_sql_file(conn: sqlite3.Connection, path: Path) -> None:
    sql = path.read_text(encoding="utf-8")
    conn.executescript(sql)


def migrate_working_summary(conn: sqlite3.Connection) -> None:
    columns = {row[1] for row in conn.execute("PRAGMA table_info(working)")}
    if "synced_streamers" not in columns:
        conn.execute("ALTER TABLE working ADD COLUMN synced_streamers INTEGER")
    if "summary" not in columns:
        return

    rows = conn.execute(
        "SELECT working_id, summary FROM working WHERE summary IS NOT NULL AND summary <> ''"
    ).fetchall()
    for working_id, raw_summary in rows:
        try:
            summary = json.loads(raw_summary)
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        synced_streamers = summary.get("synced_streamers")
        if isinstance(synced_streamers, int):
            conn.execute(
                "UPDATE working SET synced_streamers=? WHERE working_id=?",
                (synced_streamers, working_id),
            )

    conn.execute("ALTER TABLE working DROP COLUMN summary")


def init_core_tables(database: str) -> list[str]:
    sql_dir = project_root() / "sql_init"
    executed: list[str] = []

    with closing(sqlite3.connect(database)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for file_name in CORE_SQL_FILES:
            run_sql_file(conn, sql_dir / file_name)
            executed.append(file_name)
        migrate_working_summary(conn)
        migrate_stream_titles(conn)
        migrate_stream_categories(conn)
        migrate_stream_tags(conn)
        conn.commit()

    return executed


def init_database(database: str) -> list[str]:
    sql_files = init_core_tables(database)
    return sql_files


def main() -> int:
    parser = argparse.ArgumentParser(description="Initialize project database tables.")
    parser.add_argument(
        "--database",
        default=DEFAULT_DATABASE,
        help=f"SQLite database path. Default: {DEFAULT_DATABASE}",
    )
    args = parser.parse_args()

    sql_files = init_database(args.database)

    print(f"Database: {args.database}")
    print("Initialized core SQL:")
    for file_name in sql_files:
        print(f"- {file_name}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
