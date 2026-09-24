from __future__ import annotations

import io
import json
import sqlite3
import sys
import tempfile
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youtube_api_collector import (
    Candidate,
    VideoObservation,
    classify_video,
    collect_youtube_api,
    fetch_video_batch,
    record_observation,
)
from youtube_api_db import init_youtube_api_database
from youtube_webhook_server import YouTubeWebhookServer
from youtube_websub_common import (
    callback_with_token,
    channel_id_from_topic,
    parse_atom_events,
)


CHANNEL_ID = "UC1234567890123456789012"
VIDEO_ID = "abcdefghijk"


def atom_payload() -> bytes:
    return f"""<?xml version="1.0" encoding="UTF-8"?>
<feed xmlns:yt="http://www.youtube.com/xml/schemas/2015"
      xmlns="http://www.w3.org/2005/Atom">
  <link rel="self"
        href="https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"/>
  <entry>
    <yt:videoId>{VIDEO_ID}</yt:videoId>
    <yt:channelId>{CHANNEL_ID}</yt:channelId>
    <title>Test live</title>
    <published>2026-07-29T10:00:00+00:00</published>
    <updated>2026-07-29T10:01:00+00:00</updated>
  </entry>
</feed>""".encode()


class WebSubUnitTests(unittest.TestCase):
    def test_topic_and_callback_helpers(self) -> None:
        topic = f"https://www.youtube.com/feeds/videos.xml?channel_id={CHANNEL_ID}"
        self.assertEqual(channel_id_from_topic(topic), CHANNEL_ID)
        self.assertEqual(
            callback_with_token("https://example.com/webhook?x=1", "secret"),
            "https://example.com/webhook?x=1&token=secret",
        )

    def test_parse_atom_event(self) -> None:
        events = parse_atom_events(atom_payload())
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0].video_id, VIDEO_ID)
        self.assertEqual(events[0].channel_id, CHANNEL_ID)
        self.assertEqual(events[0].title, "Test live")

    def test_classify_video(self) -> None:
        self.assertEqual(
            classify_video({"snippet": {"liveBroadcastContent": "live"}}),
            "live",
        )
        self.assertEqual(
            classify_video({"snippet": {"liveBroadcastContent": "upcoming"}}),
            "upcoming",
        )
        self.assertEqual(
            classify_video(
                {
                    "snippet": {"liveBroadcastContent": "none"},
                    "liveStreamingDetails": {"actualEndTime": "2026-01-01T00:00:00Z"},
                }
            ),
            "completed",
        )
        self.assertEqual(
            classify_video({"snippet": {"liveBroadcastContent": "none"}}),
            "not_live",
        )

    def test_non_live_candidate_does_not_override_different_live_video(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = str(Path(temp_dir) / "status.db")
            init_youtube_api_database(database, None, sync=False)
            conn = sqlite3.connect(database)
            try:
                conn.execute(
                    """
                    INSERT INTO streamer (
                        vtuber_id, group_name, name, youtube_channel_id
                    )
                    VALUES ('test_vtuber', 'test', 'Test VTuber', ?)
                    """,
                    (CHANNEL_ID,),
                )
                for video_id in ("livevideo01", "upcoming001"):
                    conn.execute(
                        """
                        INSERT INTO youtube_api_candidate (
                            video_id, channel_id, vtuber_id
                        )
                        VALUES (?, ?, 'test_vtuber')
                        """,
                        (video_id, CHANNEL_ID),
                    )

                live_candidate = Candidate("livevideo01", CHANNEL_ID, "test_vtuber")
                live_observation = VideoObservation(
                    "livevideo01",
                    CHANNEL_ID,
                    "live",
                    "Live",
                    123,
                    1000,
                    50,
                    None,
                    "2026-07-29 10:00:00",
                    None,
                    "{}",
                )
                record_observation(conn, live_candidate, live_observation, 300)

                upcoming_candidate = Candidate("upcoming001", CHANNEL_ID, "test_vtuber")
                upcoming_observation = VideoObservation(
                    "upcoming001",
                    CHANNEL_ID,
                    "upcoming",
                    "Upcoming",
                    None,
                    0,
                    0,
                    "2026-07-30 10:00:00",
                    None,
                    None,
                    "{}",
                )
                record_observation(conn, upcoming_candidate, upcoming_observation, 300)
                current = conn.execute(
                    """
                    SELECT is_live, video_id, concurrent_viewers
                    FROM youtube_api_current_status
                    WHERE vtuber_id = 'test_vtuber'
                    """
                ).fetchone()
                self.assertEqual(current, (1, "livevideo01", 123))
            finally:
                conn.close()

    @patch("youtube_api_collector.urllib.request.urlopen")
    def test_fetch_video_batch_uses_one_request_for_multiple_ids(self, urlopen) -> None:
        response = {
            "items": [
                {
                    "id": VIDEO_ID,
                    "snippet": {
                        "channelId": CHANNEL_ID,
                        "title": "Test live",
                        "liveBroadcastContent": "live",
                    },
                    "liveStreamingDetails": {
                        "actualStartTime": "2026-07-29T10:00:00Z",
                        "concurrentViewers": "42",
                    },
                    "statistics": {"viewCount": "100", "likeCount": "5"},
                }
            ]
        }
        urlopen.return_value = io.BytesIO(json.dumps(response).encode())
        candidates = [
            Candidate(VIDEO_ID, CHANNEL_ID, "test_vtuber"),
            Candidate("missing0001", CHANNEL_ID, "test_vtuber"),
        ]

        observations = fetch_video_batch("test-key", candidates, timeout=5)

        self.assertEqual(urlopen.call_count, 1)
        request = urlopen.call_args.args[0]
        query = urllib.parse.parse_qs(urllib.parse.urlparse(request.full_url).query)
        self.assertEqual(query["id"], [f"{VIDEO_ID},missing0001"])
        self.assertEqual(observations[VIDEO_ID].concurrent_viewers, 42)

    @patch("youtube_api_collector.fetch_video_batch")
    def test_official_collector_writes_separate_snapshot(self, fetch_video_batch) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            database = str(Path(temp_dir) / "collector.db")
            init_youtube_api_database(database, None, sync=False)
            conn = sqlite3.connect(database)
            try:
                conn.execute(
                    """
                    INSERT INTO streamer (
                        vtuber_id, group_name, name, youtube_channel_id
                    )
                    VALUES ('test_vtuber', 'test', 'Test VTuber', ?)
                    """,
                    (CHANNEL_ID,),
                )
                conn.execute(
                    """
                    INSERT INTO youtube_api_candidate (
                        video_id, channel_id, vtuber_id
                    )
                    VALUES (?, ?, 'test_vtuber')
                    """,
                    (VIDEO_ID, CHANNEL_ID),
                )
                conn.commit()
            finally:
                conn.close()

            fetch_video_batch.return_value = {
                VIDEO_ID: VideoObservation(
                    VIDEO_ID,
                    CHANNEL_ID,
                    "live",
                    "Test live",
                    42,
                    100,
                    5,
                    None,
                    "2026-07-29 10:00:00",
                    None,
                    "{}",
                )
            }
            summary = collect_youtube_api(
                database,
                "test-key",
                config_database=None,
            )
            self.assertEqual(summary["quota_units"], 1)
            self.assertEqual(summary["live"], 1)

            conn = sqlite3.connect(database)
            try:
                snapshot = conn.execute(
                    """
                    SELECT live_status, concurrent_viewers
                    FROM youtube_api_snapshot
                    WHERE video_id = ?
                    """,
                    (VIDEO_ID,),
                ).fetchone()
                canonical_table = conn.execute(
                    """
                    SELECT count(*)
                    FROM sqlite_master
                    WHERE type = 'table'
                      AND name = 'stream_snapshot'
                    """
                ).fetchone()[0]
            finally:
                conn.close()
            self.assertEqual(snapshot, ("live", 42))
            self.assertEqual(canonical_table, 0)


class WebhookIntegrationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temp_dir = tempfile.TemporaryDirectory()
        self.database = str(Path(self.temp_dir.name) / "test.db")
        init_youtube_api_database(self.database, None, sync=False)
        conn = sqlite3.connect(self.database)
        try:
            conn.execute(
                """
                INSERT INTO streamer (
                    vtuber_id, group_name, name, youtube_channel_id
                )
                VALUES ('test_vtuber', 'test', 'Test VTuber', ?)
                """,
                (CHANNEL_ID,),
            )
            conn.commit()
        finally:
            conn.close()
        self.server = YouTubeWebhookServer(
            ("127.0.0.1", 0),
            database=self.database,
            callback_path="/webhooks/youtube",
            public_callback_url="https://example.com/webhooks/youtube?token=test-token",
            webhook_token="test-token",
        )
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()
        self.base_url = (
            f"http://127.0.0.1:{self.server.server_address[1]}/webhooks/youtube"
        )

    def tearDown(self) -> None:
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)
        self.temp_dir.cleanup()

    def test_verification_and_event_delivery(self) -> None:
        query = urllib.parse.urlencode(
            {
                "token": "test-token",
                "hub.mode": "subscribe",
                "hub.topic": (
                    "https://www.youtube.com/feeds/videos.xml"
                    f"?channel_id={CHANNEL_ID}"
                ),
                "hub.challenge": "challenge-value",
                "hub.lease_seconds": "86400",
            }
        )
        with urllib.request.urlopen(f"{self.base_url}?{query}") as response:
            self.assertEqual(response.read(), b"challenge-value")

        request = urllib.request.Request(
            f"{self.base_url}?token=test-token",
            data=atom_payload(),
            headers={"Content-Type": "application/atom+xml"},
            method="POST",
        )
        with urllib.request.urlopen(request) as response:
            self.assertEqual(response.status, 204)

        conn = sqlite3.connect(self.database)
        try:
            subscription = conn.execute(
                "SELECT status FROM youtube_websub_subscription WHERE channel_id = ?",
                (CHANNEL_ID,),
            ).fetchone()
            candidate = conn.execute(
                """
                SELECT vtuber_id, status, active
                FROM youtube_api_candidate
                WHERE video_id = ?
                """,
                (VIDEO_ID,),
            ).fetchone()
        finally:
            conn.close()
        self.assertEqual(subscription, ("verified",))
        self.assertEqual(candidate, ("test_vtuber", "pending", 1))


if __name__ == "__main__":
    unittest.main()
