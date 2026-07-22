CREATE TABLE IF NOT EXISTS stream_snapshot (
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
);
