#!/usr/bin/env python3
"""Create a consistent publishable copy of the current collector database."""

from __future__ import annotations

import argparse
import os
import sqlite3
from pathlib import Path


def parse_args() -> argparse.Namespace:
    root = Path(__file__).resolve().parents[2]
    tool = Path(__file__).resolve().parents[1]
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=root / "live_data.db")
    parser.add_argument("--audience", type=Path, default=root / "streamer_audience.db")
    parser.add_argument("--output", type=Path, default=tool / "data" / "merged_live_data.db")
    return parser.parse_args()


def table_sql(connection: sqlite3.Connection, table: str) -> str | None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return row[0] if row else None


def replace_audience(target: sqlite3.Connection, source_path: Path) -> int:
    source = sqlite3.connect(f"file:{source_path.resolve().as_posix()}?mode=ro", uri=True)
    try:
        sql = table_sql(source, "streamer_audience")
        if not sql:
            raise RuntimeError("audience database is missing streamer_audience")
        target.execute('DROP TABLE IF EXISTS "streamer_audience"')
        target.execute(sql)
        columns = [row[1] for row in source.execute('PRAGMA table_info("streamer_audience")')]
        names = ", ".join(f'"{column}"' for column in columns)
        placeholders = ", ".join("?" for _ in columns)
        target.executemany(
            f'INSERT INTO "streamer_audience" ({names}) VALUES ({placeholders})',
            source.execute(f'SELECT {names} FROM "streamer_audience"'),
        )
        return target.execute('SELECT COUNT(*) FROM "streamer_audience"').fetchone()[0]
    finally:
        source.close()


def read_group_settings(path: Path) -> list[tuple[str, int | None, str | None]]:
    if not path.is_file():
        return []
    connection = sqlite3.connect(f"file:{path.as_posix()}?mode=ro", uri=True)
    try:
        exists = connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='group_settings'"
        ).fetchone()
        if not exists:
            return []
        return connection.execute(
            "SELECT group_name, display_order, note FROM group_settings"
        ).fetchall()
    finally:
        connection.close()


def synchronize_group_settings(
    target: sqlite3.Connection,
    preserved: list[tuple[str, int | None, str | None]],
) -> int:
    target.execute(
        """
        CREATE TABLE IF NOT EXISTS group_settings (
            group_name TEXT PRIMARY KEY,
            display_order INTEGER,
            note TEXT
        )
        """
    )
    target.executemany(
        """
        INSERT INTO group_settings (group_name, display_order, note)
        VALUES (?, ?, ?)
        ON CONFLICT(group_name) DO UPDATE SET
            display_order=excluded.display_order,
            note=excluded.note
        """,
        preserved,
    )
    target.execute(
        """
        INSERT OR IGNORE INTO group_settings (group_name)
        SELECT DISTINCT group_name FROM streamer
        WHERE group_name IS NOT NULL AND trim(group_name) <> ''
        """
    )
    return target.execute("SELECT COUNT(*) FROM group_settings").fetchone()[0]


def main() -> int:
    args = parse_args()
    current = args.current.resolve()
    audience = args.audience.resolve()
    output = args.output.resolve()
    for path, label in ((current, "current"), (audience, "audience")):
        if not path.is_file():
            raise FileNotFoundError(f"{label} database not found: {path}")
    if output in {current, audience}:
        raise ValueError("output must differ from source databases")

    # Most collector databases do not have this table, but retain it when they
    # do. A prior publish copy takes precedence so edits survive every rebuild.
    preserved_by_group = {
        row[0]: row for row in read_group_settings(current)
    }
    preserved_by_group.update({row[0]: row for row in read_group_settings(output)})
    preserved_settings = list(preserved_by_group.values())
    output.parent.mkdir(parents=True, exist_ok=True)
    temporary = output.with_name(output.name + ".tmp")
    temporary.unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{current.as_posix()}?mode=ro", uri=True, timeout=30)
    target = sqlite3.connect(temporary)
    try:
        source.backup(target)
        audience_count = replace_audience(target, audience)
        group_count = synchronize_group_settings(target, preserved_settings)
        target.commit()
        integrity = target.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = target.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError(
                f"validation failed: integrity={integrity}, foreign_key_errors={len(foreign_keys)}"
            )
    except Exception:
        target.close()
        source.close()
        temporary.unlink(missing_ok=True)
        raise
    else:
        target.close()
        source.close()

    os.replace(temporary, output)
    print(f"Prepared database: {output}")
    print(f"Audience rows: {audience_count}")
    print(f"Group settings: {group_count}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
