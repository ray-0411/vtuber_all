#!/usr/bin/env python3
"""Restore configured Group settings to the publish DB and Supabase."""

from __future__ import annotations

import argparse
import sqlite3
from pathlib import Path

from sync_merged_to_postgres import load_local_environment, postgres_driver_and_url


def parse_args() -> argparse.Namespace:
    tool = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source", type=Path, required=True)
    parser.add_argument(
        "--database", type=Path, default=tool / "data" / "merged_live_data.db"
    )
    parser.add_argument("--confirm-upload", action="store_true")
    return parser.parse_args()


def configured_rows(path: Path) -> list[tuple[str, int | None, str | None]]:
    resolved = path.resolve()
    connection = sqlite3.connect(f"file:{resolved.as_posix()}?mode=ro", uri=True)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='group_settings'"
        ).fetchone()
        if not exists:
            raise RuntimeError(f"group_settings is missing: {resolved}")
        return connection.execute(
            """
            SELECT group_name, display_order, note
            FROM group_settings
            WHERE display_order IS NOT NULL OR note IS NOT NULL
            ORDER BY display_order IS NULL, display_order, group_name
            """
        ).fetchall()
    finally:
        connection.close()


def main() -> int:
    args = parse_args()
    rows = configured_rows(args.source)
    if not rows:
        raise RuntimeError("source has no configured Group settings")

    database = args.database.resolve()
    with sqlite3.connect(database) as connection:
        connection.executemany(
            """
            INSERT INTO group_settings (group_name, display_order, note)
            VALUES (?, ?, ?)
            ON CONFLICT(group_name) DO UPDATE SET
                display_order=excluded.display_order,
                note=excluded.note
            """,
            rows,
        )

    print(f"Restored local Group settings: {len(rows)} rows")
    if not args.confirm_upload:
        print("Supabase was not changed; pass --confirm-upload to restore it.")
        return 0

    load_local_environment()
    psycopg, database_url = postgres_driver_and_url()
    with psycopg.connect(database_url) as postgres:
        with postgres.cursor() as cursor:
            cursor.execute("SELECT pg_advisory_xact_lock(%s)", (847_041_103,))
            cursor.executemany(
                """
                INSERT INTO dashboard.group_settings (group_name, display_order, note)
                VALUES (%s, %s, %s)
                ON CONFLICT (group_name) DO UPDATE SET
                    display_order=excluded.display_order,
                    note=excluded.note
                """,
                rows,
            )
        postgres.commit()

    with psycopg.connect(database_url) as postgres:
        with postgres.cursor() as cursor:
            cursor.execute(
                """
                SELECT group_name, display_order, note
                FROM dashboard.group_settings
                WHERE display_order IS NOT NULL OR note IS NOT NULL
                ORDER BY display_order IS NULL, display_order, group_name
                """
            )
            restored = cursor.fetchall()
    print(f"Verified Supabase Group settings: {len(restored)} configured rows")
    for row in restored:
        print(row)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
