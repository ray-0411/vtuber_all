from __future__ import annotations

import sqlite3
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from migrate_youtube_api_data import migrate_youtube_api_data
from youtube_api_db import init_youtube_api_database


class YouTubeApiDatabaseTests(unittest.TestCase):
    def test_migration_copies_only_api_tables_without_changing_source(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            source = Path(temp_dir) / "live.db"
            target = Path(temp_dir) / "api.db"
            init_youtube_api_database(str(source), None, sync=False)
            conn = sqlite3.connect(source)
            try:
                conn.execute(
                    """
                    INSERT INTO youtube_websub_subscription (
                        channel_id,
                        vtuber_id,
                        callback_url,
                        topic_url,
                        status
                    )
                    VALUES ('UC123', 'test', 'https://example.com/webhook',
                            'https://www.youtube.com/feeds/videos.xml?channel_id=UC123',
                            'verified')
                    """
                )
                conn.commit()
            finally:
                conn.close()
            before = source.read_bytes()

            copied = migrate_youtube_api_data(
                str(source),
                str(target),
                None,
            )

            self.assertEqual(source.read_bytes(), before)
            self.assertEqual(copied["youtube_websub_subscription"], 1)
            conn = sqlite3.connect(target)
            try:
                count = conn.execute(
                    "SELECT count(*) FROM youtube_websub_subscription"
                ).fetchone()[0]
                old_table = conn.execute(
                    """
                    SELECT count(*)
                    FROM sqlite_master
                    WHERE type = 'table' AND name = 'stream_snapshot'
                    """
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(count, 1)
            self.assertEqual(old_table, 0)


if __name__ == "__main__":
    unittest.main()

