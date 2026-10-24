CREATE TABLE IF NOT EXISTS stream_category (
    category_id INTEGER PRIMARY KEY AUTOINCREMENT,
    category TEXT NOT NULL UNIQUE CHECK (category <> '')
);

