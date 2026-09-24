from __future__ import annotations

import sqlite3
from contextlib import closing
from pathlib import Path

from sync_streamers import sync_streamers


DEFAULT_API_DATABASE = "youtube_api_data.db"
DEFAULT_CONFIG_DATABASE = "streamer_config.db"
API_SQL_FILES = (
    "002_streamer.sql",
    "013_working.sql",
    "014_youtube_websub.sql",
)


def project_root() -> Path:
    return Path(__file__).resolve().parents[1]


def init_youtube_api_database(
    database: str = DEFAULT_API_DATABASE,
    config_database: str | None = DEFAULT_CONFIG_DATABASE,
    *,
    sync: bool = True,
) -> list[str]:
    sql_dir = project_root() / "sql_init"
    with closing(sqlite3.connect(database, timeout=30)) as conn:
        conn.execute("PRAGMA foreign_keys = ON")
        for file_name in API_SQL_FILES:
            conn.executescript((sql_dir / file_name).read_text(encoding="utf-8"))
        conn.commit()
    if sync and config_database is not None:
        sync_streamers(config_database, database)
    return list(API_SQL_FILES)
