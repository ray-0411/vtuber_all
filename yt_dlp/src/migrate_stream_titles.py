from __future__ import annotations

import argparse
import sqlite3


def column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def migrate_stream_titles(conn: sqlite3.Connection) -> bool:
    snapshot_has_text_title = "title" in column_names(conn, "stream_snapshot")
    status_has_text_title = "title" in column_names(conn, "current_live_status")
    if not snapshot_has_text_title and not status_has_text_title:
        return False

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stream_title (
                    title_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    title TEXT NOT NULL UNIQUE
                )
                """
            )
            if snapshot_has_text_title:
                conn.execute(
                    "INSERT OR IGNORE INTO stream_title (title) "
                    "SELECT DISTINCT title FROM stream_snapshot WHERE title IS NOT NULL"
                )
            if status_has_text_title:
                conn.execute(
                    "INSERT OR IGNORE INTO stream_title (title) "
                    "SELECT DISTINCT title FROM current_live_status WHERE title IS NOT NULL"
                )

            if snapshot_has_text_title:
                snapshot_count = conn.execute("SELECT COUNT(*) FROM stream_snapshot").fetchone()[0]
                conn.execute("ALTER TABLE stream_snapshot RENAME TO stream_snapshot_title_text")
                conn.execute(
                    """
                    CREATE TABLE stream_snapshot (
                        snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
                        stream_id INTEGER NOT NULL,
                        vtuber_id TEXT NOT NULL,
                        platform TEXT NOT NULL CHECK (platform IN ('youtube', 'twitch')),
                        viewer_count INTEGER NOT NULL,
                        captured_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                        title_id INTEGER,
                        category TEXT,
                        tags TEXT,
                        FOREIGN KEY (stream_id) REFERENCES stream(stream_id),
                        FOREIGN KEY (title_id) REFERENCES stream_title(title_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO stream_snapshot (
                        snapshot_id, stream_id, vtuber_id, platform, viewer_count,
                        captured_at, title_id, category, tags
                    )
                    SELECT
                        old.snapshot_id, old.stream_id, old.vtuber_id, old.platform,
                        old.viewer_count, old.captured_at, titles.title_id,
                        old.category, old.tags
                    FROM stream_snapshot_title_text AS old
                    LEFT JOIN stream_title AS titles ON titles.title = old.title
                    """
                )
                migrated_count = conn.execute("SELECT COUNT(*) FROM stream_snapshot").fetchone()[0]
                if migrated_count != snapshot_count:
                    raise RuntimeError(
                        f"Snapshot count changed during migration: {snapshot_count} -> {migrated_count}"
                    )
                conn.execute("DROP TABLE stream_snapshot_title_text")

            if status_has_text_title:
                status_count = conn.execute("SELECT COUNT(*) FROM current_live_status").fetchone()[0]
                conn.execute("ALTER TABLE current_live_status RENAME TO current_live_status_title_text")
                conn.execute(
                    """
                    CREATE TABLE current_live_status (
                        vtuber_id TEXT NOT NULL,
                        platform TEXT NOT NULL CHECK (platform IN ('youtube', 'twitch')),
                        is_live INTEGER NOT NULL DEFAULT 0,
                        stream_id INTEGER,
                        viewer_count INTEGER,
                        stream_url TEXT,
                        title_id INTEGER,
                        category TEXT,
                        tags TEXT,
                        started_at TEXT,
                        last_checked_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                        last_live_at TEXT,
                        PRIMARY KEY (vtuber_id, platform),
                        FOREIGN KEY (stream_id) REFERENCES stream(stream_id),
                        FOREIGN KEY (title_id) REFERENCES stream_title(title_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO current_live_status (
                        vtuber_id, platform, is_live, stream_id, viewer_count,
                        stream_url, title_id, category, tags, started_at,
                        last_checked_at, last_live_at
                    )
                    SELECT
                        old.vtuber_id, old.platform, old.is_live, old.stream_id,
                        old.viewer_count, old.stream_url, titles.title_id,
                        old.category, old.tags, old.started_at,
                        old.last_checked_at, old.last_live_at
                    FROM current_live_status_title_text AS old
                    LEFT JOIN stream_title AS titles ON titles.title = old.title
                    """
                )
                migrated_count = conn.execute("SELECT COUNT(*) FROM current_live_status").fetchone()[0]
                if migrated_count != status_count:
                    raise RuntimeError(
                        f"Live-status count changed during migration: {status_count} -> {migrated_count}"
                    )
                conn.execute("DROP TABLE current_live_status_title_text")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"Foreign-key violations after title migration: {violations[:5]}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize snapshot and live-status titles.")
    parser.add_argument("--database", default="live_data.db")
    args = parser.parse_args()
    with sqlite3.connect(args.database, timeout=30) as conn:
        changed = migrate_stream_titles(conn)
    print("migrated" if changed else "already migrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
