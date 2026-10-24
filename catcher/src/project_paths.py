"""Stable paths shared by collector entry points, independent of cwd."""
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]
DATABASE_DIR = REPO_ROOT / "database" / "main"

def database_path(name: str) -> str:
    return str(DATABASE_DIR / name)

def normalize_saved_database(value: str) -> str:
    # Older control-panel settings stored bare names or paths under yt_dlp.
    path = Path(value)
    known = {"live_data.db", "streamer_config.db", "youtube_api_data.db", "streamer_audience.db"}
    if value in known:
        return database_path(value)
    if path.name in known and path.parent == REPO_ROOT / "yt_dlp":
        return database_path(path.name)
    # Preserve relative custom paths against the relocated collector directory.
    return str(path if path.is_absolute() else REPO_ROOT / "catcher" / path)
