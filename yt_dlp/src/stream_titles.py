from __future__ import annotations

import sqlite3


def resolve_title_id(
    conn: sqlite3.Connection,
    vtuber_id: str,
    platform: str,
    title: str | None,
) -> int | None:
    """Return a title id, reusing the current live status without a title-table search."""
    if title is None:
        return None

    current = conn.execute(
        """
        SELECT current_live_status.title_id
        FROM current_live_status
        JOIN stream_title
          ON stream_title.title_id = current_live_status.title_id
        WHERE current_live_status.vtuber_id = ?
          AND current_live_status.platform = ?
          AND stream_title.title = ?
        """,
        (vtuber_id, platform, title),
    ).fetchone()
    if current is not None:
        return int(current[0])

    conn.execute(
        "INSERT INTO stream_title (title) VALUES (?) ON CONFLICT(title) DO NOTHING",
        (title,),
    )
    row = conn.execute(
        "SELECT title_id FROM stream_title WHERE title = ?",
        (title,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Failed to resolve stream title")
    return int(row[0])

