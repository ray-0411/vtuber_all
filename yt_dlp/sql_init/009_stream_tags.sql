CREATE TABLE IF NOT EXISTS stream_tags (
    tags_id INTEGER PRIMARY KEY AUTOINCREMENT,
    tags TEXT NOT NULL UNIQUE CHECK (tags <> '' AND tags <> '[]')
);

