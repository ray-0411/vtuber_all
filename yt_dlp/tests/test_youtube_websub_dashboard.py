from __future__ import annotations

import sys
import threading
import unittest
import urllib.parse
import urllib.request
from pathlib import Path
from unittest.mock import patch


ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from youtube_websub_dashboard import DashboardServer, PipelineRuntime
from youtube_websub_settings import YouTubeWebSubSettings


class DashboardTests(unittest.TestCase):
    @patch("youtube_websub_dashboard.save_settings")
    @patch("youtube_websub_dashboard.load_settings")
    @patch("youtube_websub_dashboard.listening_pid", return_value=12345)
    def test_start_all_rejects_stale_webhook_port(
        self,
        listening_pid,
        load_settings,
        save_settings,
    ) -> None:
        load_settings.return_value = YouTubeWebSubSettings(
            api_key="api-key",
            webhook_token="token",
        )
        runtime = PipelineRuntime()
        with self.assertRaisesRegex(RuntimeError, "8787.*12345"):
            runtime.start_all()

    @patch("youtube_websub_dashboard.save_settings")
    @patch("youtube_websub_dashboard.load_settings")
    def test_dashboard_does_not_render_saved_secrets(
        self,
        load_settings,
        save_settings,
    ) -> None:
        load_settings.return_value = YouTubeWebSubSettings(
            api_key="secret-api-key",
            webhook_token="secret-webhook-token",
        )
        runtime = PipelineRuntime()
        server = DashboardServer(("127.0.0.1", 0), runtime)
        thread = threading.Thread(target=server.serve_forever, daemon=True)
        thread.start()
        url = f"http://127.0.0.1:{server.server_address[1]}/"
        try:
            with urllib.request.urlopen(url) as response:
                page = response.read().decode("utf-8")
            self.assertNotIn("secret-api-key", page)
            self.assertNotIn("secret-webhook-token", page)
            self.assertIn("已保存", page)

            form = urllib.parse.urlencode(
                {
                    "csrf": server.csrf_token,
                    "action": "generate_token",
                    "api_key": "",
                    "webhook_token": "",
                    "callback_url": "",
                    "mode": "quick_tunnel",
                    "api_database": "youtube_api_data.db",
                    "live_database": "live_data.db",
                    "config_database": "streamer_config.db",
                    "interval_seconds": "300",
                    "candidate_limit": "1500",
                }
            ).encode()
            request = urllib.request.Request(
                f"{url}action",
                data=form,
                method="POST",
            )
            with urllib.request.urlopen(request) as response:
                self.assertEqual(response.status, 200)
            self.assertNotEqual(runtime.settings.webhook_token, "secret-webhook-token")
            self.assertTrue(save_settings.called)
        finally:
            server.shutdown()
            server.server_close()
            runtime.shutdown()
            thread.join(timeout=2)


if __name__ == "__main__":
    unittest.main()
