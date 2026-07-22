from __future__ import annotations

import argparse
import sqlite3


def column_names(conn: sqlite3.Connection, table_name: str) -> set[str]:
    return {str(row[1]) for row in conn.execute(f"PRAGMA table_info({table_name})")}


def migrate_stream_tags(conn: sqlite3.Connection) -> bool:
    snapshot_has_text = "tags" in column_names(conn, "stream_snapshot")
    status_has_text = "tags" in column_names(conn, "current_live_status")
    if not snapshot_has_text and not status_has_text:
        return False

    conn.execute("PRAGMA foreign_keys = OFF")
    try:
        with conn:
            conn.execute(
                """
                CREATE TABLE IF NOT EXISTS stream_tags (
                    tags_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    tags TEXT NOT NULL UNIQUE CHECK (tags <> '' AND tags <> '[]')
                )
                """
            )
            if snapshot_has_text:
                conn.execute(
                    "INSERT OR IGNORE INTO stream_tags (tags) "
                    "SELECT DISTINCT tags FROM stream_snapshot "
                    "WHERE tags IS NOT NULL AND tags NOT IN ('', '[]')"
                )
            if status_has_text:
                conn.execute(
                    "INSERT OR IGNORE INTO stream_tags (tags) "
                    "SELECT DISTINCT tags FROM current_live_status "
                    "WHERE tags IS NOT NULL AND tags NOT IN ('', '[]')"
                )

            if snapshot_has_text:
                expected = conn.execute("SELECT COUNT(*) FROM stream_snapshot").fetchone()[0]
                conn.execute("ALTER TABLE stream_snapshot RENAME TO stream_snapshot_tags_text")
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
                        category_id INTEGER,
                        tags_id INTEGER,
                        FOREIGN KEY (stream_id) REFERENCES stream(stream_id),
                        FOREIGN KEY (title_id) REFERENCES stream_title(title_id),
                        FOREIGN KEY (category_id) REFERENCES stream_category(category_id),
                        FOREIGN KEY (tags_id) REFERENCES stream_tags(tags_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO stream_snapshot (
                        snapshot_id, stream_id, vtuber_id, platform, viewer_count,
                        captured_at, title_id, category_id, tags_id
                    )
                    SELECT old.snapshot_id, old.stream_id, old.vtuber_id, old.platform,
                           old.viewer_count, old.captured_at, old.title_id,
                           old.category_id, mapped.tags_id
                    FROM stream_snapshot_tags_text AS old
                    LEFT JOIN stream_tags AS mapped
                      ON mapped.tags = CASE
                          WHEN old.tags IN ('', '[]') THEN NULL ELSE old.tags
                      END
                    """
                )
                actual = conn.execute("SELECT COUNT(*) FROM stream_snapshot").fetchone()[0]
                if actual != expected:
                    raise RuntimeError(f"Snapshot count changed: {expected} -> {actual}")
                conn.execute("DROP TABLE stream_snapshot_tags_text")

            if status_has_text:
                expected = conn.execute("SELECT COUNT(*) FROM current_live_status").fetchone()[0]
                conn.execute("ALTER TABLE current_live_status RENAME TO current_live_status_tags_text")
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
                        category_id INTEGER,
                        tags_id INTEGER,
                        started_at TEXT,
                        last_checked_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
                        last_live_at TEXT,
                        PRIMARY KEY (vtuber_id, platform),
                        FOREIGN KEY (stream_id) REFERENCES stream(stream_id),
                        FOREIGN KEY (title_id) REFERENCES stream_title(title_id),
                        FOREIGN KEY (category_id) REFERENCES stream_category(category_id),
                        FOREIGN KEY (tags_id) REFERENCES stream_tags(tags_id)
                    )
                    """
                )
                conn.execute(
                    """
                    INSERT INTO current_live_status (
                        vtuber_id, platform, is_live, stream_id, viewer_count,
                        stream_url, title_id, category_id, tags_id, started_at,
                        last_checked_at, last_live_at
                    )
                    SELECT old.vtuber_id, old.platform, old.is_live, old.stream_id,
                           old.viewer_count, old.stream_url, old.title_id,
                           old.category_id, mapped.tags_id, old.started_at,
                           old.last_checked_at, old.last_live_at
                    FROM current_live_status_tags_text AS old
                    LEFT JOIN stream_tags AS mapped
                      ON mapped.tags = CASE
                          WHEN old.tags IN ('', '[]') THEN NULL ELSE old.tags
                      END
                    """
                )
                actual = conn.execute("SELECT COUNT(*) FROM current_live_status").fetchone()[0]
                if actual != expected:
                    raise RuntimeError(f"Live-status count changed: {expected} -> {actual}")
                conn.execute("DROP TABLE current_live_status_tags_text")
    finally:
        conn.execute("PRAGMA foreign_keys = ON")

    violations = conn.execute("PRAGMA foreign_key_check").fetchall()
    if violations:
        raise RuntimeError(f"Foreign-key violations after tags migration: {violations[:5]}")
    return True


def main() -> int:
    parser = argparse.ArgumentParser(description="Normalize snapshot and live-status tags.")
    parser.add_argument("--database", default="live_data.db")
    args = parser.parse_args()
    with sqlite3.connect(args.database, timeout=30) as conn:
        changed = migrate_stream_tags(conn)
    print("migrated" if changed else "already migrated")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
