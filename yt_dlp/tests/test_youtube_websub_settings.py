from __future__ import annotations

import json
import sys
import tempfile
import unittest
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youtube_websub_settings import (
    YouTubeWebSubSettings,
    load_settings,
    save_settings,
)


class SecureSettingsTests(unittest.TestCase):
    def test_dpapi_round_trip_does_not_store_plaintext_secrets(self) -> None:
        with tempfile.TemporaryDirectory() as temp_dir:
            path = Path(temp_dir) / "settings.json"
            expected = YouTubeWebSubSettings(
                api_key="test-api-key-secret",
                webhook_token="test-webhook-token-secret",
                callback_url="https://example.com/webhooks/youtube",
                mode="fixed",
                interval_seconds=600,
                candidate_limit=1200,
            )

            save_settings(expected, path)
            raw_text = path.read_text(encoding="utf-8")
            raw_payload = json.loads(raw_text)
            actual = load_settings(path)

            self.assertNotIn(expected.api_key, raw_text)
            self.assertNotIn(expected.webhook_token, raw_text)
            self.assertIn("windows_dpapi", raw_payload)
            self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()

