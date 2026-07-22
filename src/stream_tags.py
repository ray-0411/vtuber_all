from __future__ import annotations

import sqlite3


def resolve_tags_id(
    conn: sqlite3.Connection,
    vtuber_id: str,
    platform: str,
    tags: str | None,
) -> int | None:
    """Return an id for a non-empty serialized tags array."""
    if not tags or tags == "[]":
        return None

    current = conn.execute(
        """
        SELECT current_live_status.tags_id
        FROM current_live_status
        JOIN stream_tags ON stream_tags.tags_id = current_live_status.tags_id
        WHERE current_live_status.vtuber_id = ?
          AND current_live_status.platform = ?
          AND stream_tags.tags = ?
        """,
        (vtuber_id, platform, tags),
    ).fetchone()
    if current is not None:
        return int(current[0])

    conn.execute(
        "INSERT INTO stream_tags (tags) VALUES (?) ON CONFLICT(tags) DO NOTHING",
        (tags,),
    )
    row = conn.execute("SELECT tags_id FROM stream_tags WHERE tags = ?", (tags,)).fetchone()
    if row is None:
        raise RuntimeError("Failed to resolve stream tags")
    return int(row[0])

