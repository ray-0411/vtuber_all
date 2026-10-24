import sqlite3
import sys
import tempfile
import unittest
from contextlib import closing
from pathlib import Path


repo_root = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(repo_root / "catcher/src"))
sys.path.insert(0, str(repo_root / "tools/catcher/streamer_manager"))

from streamer_form import FORM_GROUPS, parse_nonnegative_count, save_audience


class StreamerFormAudienceTests(unittest.TestCase):
    def test_form_groups_are_limited_to_active_five(self):
        self.assertEqual(
            FORM_GROUPS, ("other", "meridian", "squarelive", "envision", "thebox")
        )

    def test_count_validation(self):
        self.assertEqual(parse_nonnegative_count("1,234", "訂閱數"), 1234)
        self.assertIsNone(parse_nonnegative_count("", "訂閱數"))
        with self.assertRaises(ValueError):
            parse_nonnegative_count("-1", "訂閱數")

    def test_blank_optional_values_do_not_erase_existing_data(self):
        with tempfile.TemporaryDirectory() as directory:
            database = str(Path(directory) / "audience.db")
            with closing(sqlite3.connect(database)) as conn, conn:
                conn.execute(
                    """
                    CREATE TABLE streamer_audience (
                        vtuber_id TEXT PRIMARY KEY, name TEXT NOT NULL,
                        group_table TEXT NOT NULL, youtube_channel_id TEXT,
                        youtube_subscribers INTEGER, twitch_followers INTEGER,
                        youtube_avatar_url TEXT, updated_at TEXT NOT NULL
                    )
                    """
                )
            save_audience(
                database, "new_id", "新人", "other", None, "UC123", None,
                1234, 55, "https://example.com/avatar.png", None,
            )
            save_audience(
                database, "new_id", "新名稱", "other", None, None, None,
                None, 77, None, None,
            )
            with closing(sqlite3.connect(database)) as conn:
                row = conn.execute(
                    """
                    SELECT name, youtube_channel_id, youtube_subscribers,
                           twitch_followers, youtube_avatar_url
                    FROM streamer_audience WHERE vtuber_id = 'new_id'
                    """
                ).fetchone()
            self.assertEqual(
                row, ("新名稱", "UC123", 1234, 77, "https://example.com/avatar.png")
            )


if __name__ == "__main__":
    unittest.main()
