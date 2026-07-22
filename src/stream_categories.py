from __future__ import annotations

import sqlite3


def resolve_category_id(
    conn: sqlite3.Connection,
    vtuber_id: str,
    platform: str,
    category: str | None,
) -> int | None:
    """Return a category id, or None for a missing/empty category."""
    if not category:
        return None

    current = conn.execute(
        """
        SELECT current_live_status.category_id
        FROM current_live_status
        JOIN stream_category
          ON stream_category.category_id = current_live_status.category_id
        WHERE current_live_status.vtuber_id = ?
          AND current_live_status.platform = ?
          AND stream_category.category = ?
        """,
        (vtuber_id, platform, category),
    ).fetchone()
    if current is not None:
        return int(current[0])

    conn.execute(
        "INSERT INTO stream_category (category) VALUES (?) "
        "ON CONFLICT(category) DO NOTHING",
        (category,),
    )
    row = conn.execute(
        "SELECT category_id FROM stream_category WHERE category = ?",
        (category,),
    ).fetchone()
    if row is None:
        raise RuntimeError("Failed to resolve stream category")
    return int(row[0])

