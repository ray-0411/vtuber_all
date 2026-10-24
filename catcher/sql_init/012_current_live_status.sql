CREATE TABLE IF NOT EXISTS current_live_status (
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
);
