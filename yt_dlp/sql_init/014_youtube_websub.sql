CREATE TABLE IF NOT EXISTS youtube_websub_subscription (
    channel_id TEXT PRIMARY KEY,
    vtuber_id TEXT,
    callback_url TEXT NOT NULL,
    topic_url TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (status IN ('pending', 'verified', 'denied', 'unsubscribed', 'error')),
    requested_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
    verified_at TEXT,
    lease_seconds INTEGER,
    expires_at TEXT,
    last_error TEXT
);

CREATE TABLE IF NOT EXISTS youtube_websub_event (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    channel_id TEXT NOT NULL,
    video_id TEXT NOT NULL,
    event_kind TEXT NOT NULL CHECK (event_kind IN ('upsert', 'deleted')),
    title TEXT,
    published_at TEXT,
    event_updated_at TEXT,
    received_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
    raw_xml TEXT,
    UNIQUE (channel_id, video_id, event_kind, event_updated_at)
);

CREATE INDEX IF NOT EXISTS idx_youtube_websub_event_received
ON youtube_websub_event (received_at);

CREATE TABLE IF NOT EXISTS youtube_api_candidate (
    video_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    vtuber_id TEXT,
    source TEXT NOT NULL DEFAULT 'websub',
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK (
            status IN (
                'pending',
                'upcoming',
                'live',
                'completed',
                'not_live',
                'unavailable',
                'deleted',
                'channel_mismatch',
                'error'
            )
        ),
    active INTEGER NOT NULL DEFAULT 1 CHECK (active IN (0, 1)),
    title TEXT,
    discovered_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
    last_event_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
    last_checked_at TEXT,
    next_check_at TEXT,
    scheduled_start_at TEXT,
    actual_start_at TEXT,
    actual_end_at TEXT,
    consecutive_errors INTEGER NOT NULL DEFAULT 0,
    last_error TEXT
);

CREATE INDEX IF NOT EXISTS idx_youtube_api_candidate_due
ON youtube_api_candidate (active, next_check_at);

CREATE INDEX IF NOT EXISTS idx_youtube_api_candidate_vtuber
ON youtube_api_candidate (vtuber_id, status);

CREATE TABLE IF NOT EXISTS youtube_api_snapshot (
    snapshot_id INTEGER PRIMARY KEY AUTOINCREMENT,
    video_id TEXT NOT NULL,
    channel_id TEXT NOT NULL,
    vtuber_id TEXT,
    live_status TEXT NOT NULL,
    title TEXT,
    concurrent_viewers INTEGER,
    view_count INTEGER,
    like_count INTEGER,
    scheduled_start_at TEXT,
    actual_start_at TEXT,
    actual_end_at TEXT,
    captured_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
    raw_json TEXT,
    FOREIGN KEY (video_id) REFERENCES youtube_api_candidate(video_id)
);

CREATE INDEX IF NOT EXISTS idx_youtube_api_snapshot_video_time
ON youtube_api_snapshot (video_id, captured_at);

CREATE INDEX IF NOT EXISTS idx_youtube_api_snapshot_vtuber_time
ON youtube_api_snapshot (vtuber_id, captured_at);

CREATE TABLE IF NOT EXISTS youtube_api_current_status (
    vtuber_id TEXT PRIMARY KEY,
    channel_id TEXT NOT NULL,
    is_live INTEGER NOT NULL DEFAULT 0 CHECK (is_live IN (0, 1)),
    video_id TEXT,
    title TEXT,
    concurrent_viewers INTEGER,
    scheduled_start_at TEXT,
    actual_start_at TEXT,
    last_checked_at TEXT NOT NULL DEFAULT (datetime('now', '+8 hours')),
    last_event_at TEXT,
    last_live_at TEXT
);

