#!/usr/bin/env python3
from __future__ import annotations

import argparse
import os
import sqlite3
import sys
import threading
from contextlib import closing
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from urllib.parse import parse_qs, urlparse

from time_utils import now_db_time
from youtube_api_db import (
    DEFAULT_API_DATABASE,
    DEFAULT_CONFIG_DATABASE,
    init_youtube_api_database,
)
from youtube_websub_common import (
    channel_id_from_topic,
    known_channel,
    lease_expiry,
    parse_atom_events,
    payload_sha256,
    record_events,
    topic_url,
    valid_token,
)


DEFAULT_DATABASE = DEFAULT_API_DATABASE
DEFAULT_HOST = "127.0.0.1"
DEFAULT_PORT = 8787
DEFAULT_PATH = "/webhooks/youtube"
MAX_BODY_BYTES = 1_048_576


class YouTubeWebhookHandler(BaseHTTPRequestHandler):
    server_version = "YouTubeWebSub/1.0"

    @property
    def app(self) -> "YouTubeWebhookServer":
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: object) -> None:
        status = args[1] if len(args) > 1 else "-"
        print(
            f"[{now_db_time()}] {self.client_address[0]} "
            f"{self.command} {urlparse(self.path).path} {status}",
            file=sys.stderr,
        )

    def send_text(self, status: int, text: str = "") -> None:
        body = text.encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "text/plain; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        if body:
            self.wfile.write(body)

    def request_query(self) -> dict[str, list[str]]:
        return parse_qs(urlparse(self.path).query, keep_blank_values=True)

    def authorized_path(self) -> bool:
        parsed = urlparse(self.path)
        token = self.request_query().get("token", [None])[0]
        return parsed.path == self.app.callback_path and valid_token(
            self.app.webhook_token, token
        )

    def do_GET(self) -> None:
        if not self.authorized_path():
            self.send_text(404, "Not found")
            return

        query = self.request_query()
        mode = query.get("hub.mode", [""])[0]
        challenge = query.get("hub.challenge", [""])[0]
        topic = query.get("hub.topic", [""])[0]
        channel_id = channel_id_from_topic(topic)
        if mode not in {"subscribe", "unsubscribe", "denied"}:
            self.send_text(400, "Invalid WebSub verification request")
            return
        if mode in {"subscribe", "unsubscribe"} and not challenge:
            self.send_text(400, "Missing WebSub challenge")
            return
        if not channel_id:
            self.send_text(400, "Invalid YouTube topic")
            return

        with closing(sqlite3.connect(self.app.database, timeout=30)) as conn:
            streamer = known_channel(conn, channel_id)
            if streamer is None:
                self.send_text(404, "Unknown channel")
                return

        # WebSub hubs expect the challenge response immediately.  Send it before
        # waiting for other concurrent callbacks to finish their SQLite writes.
        self.send_text(200, challenge)

        with self.app.database_lock:
            with closing(sqlite3.connect(self.app.database, timeout=30)) as conn:
                conn.execute("PRAGMA busy_timeout = 30000")
                if mode == "denied":
                    reason = query.get("hub.reason", ["WebSub subscription denied"])[0]
                    conn.execute(
                    """
                    UPDATE youtube_websub_subscription
                    SET status = 'denied', last_error = ?
                    WHERE channel_id = ?
                    """,
                    (reason, channel_id),
                )
                elif mode == "unsubscribe":
                    conn.execute(
                    """
                    UPDATE youtube_websub_subscription
                    SET status = 'unsubscribed',
                        verified_at = ?,
                        expires_at = NULL,
                        last_error = NULL
                    WHERE channel_id = ?
                    """,
                    (now_db_time(), channel_id),
                )
                else:
                    lease_raw = query.get("hub.lease_seconds", [None])[0]
                    try:
                        lease_seconds = int(lease_raw) if lease_raw else None
                    except ValueError:
                        lease_seconds = None
                    conn.execute(
                    """
                    INSERT INTO youtube_websub_subscription (
                        channel_id,
                        vtuber_id,
                        callback_url,
                        topic_url,
                        status,
                        requested_at,
                        verified_at,
                        lease_seconds,
                        expires_at,
                        last_error
                    )
                    VALUES (?, ?, ?, ?, 'verified', ?, ?, ?, ?, NULL)
                    ON CONFLICT(channel_id) DO UPDATE SET
                        vtuber_id = excluded.vtuber_id,
                        status = 'verified',
                        verified_at = excluded.verified_at,
                        lease_seconds = excluded.lease_seconds,
                        expires_at = excluded.expires_at,
                        last_error = NULL
                    """,
                    (
                        channel_id,
                        streamer[0],
                        self.app.public_callback_url,
                        topic_url(channel_id),
                        now_db_time(),
                        now_db_time(),
                        lease_seconds,
                        lease_expiry(lease_seconds),
                    ),
                    )
                conn.commit()

    def do_POST(self) -> None:
        if not self.authorized_path():
            self.send_text(404, "Not found")
            return

        length_raw = self.headers.get("Content-Length")
        try:
            length = int(length_raw or "0")
        except ValueError:
            self.send_text(400, "Invalid Content-Length")
            return
        if length <= 0 or length > MAX_BODY_BYTES:
            self.send_text(413, "Invalid webhook body size")
            return

        payload = self.rfile.read(length)
        try:
            events = parse_atom_events(payload)
        except Exception as exc:
            self.send_text(400, f"Invalid Atom payload: {exc}")
            return
        if not events:
            self.send_text(204)
            return

        raw_xml = payload.decode("utf-8", errors="replace")
        with closing(sqlite3.connect(self.app.database, timeout=30)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            inserted = record_events(conn, events, raw_xml)
            conn.commit()

        print(
            f"[{now_db_time()}] webhook events={len(events)} inserted={inserted} "
            f"sha256={payload_sha256(payload)[:12]}",
            file=sys.stderr,
        )
        self.send_text(204)


class YouTubeWebhookServer(ThreadingHTTPServer):
    def __init__(
        self,
        address: tuple[str, int],
        database: str,
        callback_path: str,
        public_callback_url: str,
        webhook_token: str | None,
    ) -> None:
        super().__init__(address, YouTubeWebhookHandler)
        self.database = database
        self.callback_path = callback_path
        self.public_callback_url = public_callback_url
        self.webhook_token = webhook_token
        self.database_lock = threading.Lock()


def main() -> int:
    parser = argparse.ArgumentParser(description="Receive YouTube WebSub notifications.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument("--host", default=DEFAULT_HOST)
    parser.add_argument("--port", type=int, default=DEFAULT_PORT)
    parser.add_argument("--path", default=DEFAULT_PATH)
    parser.add_argument(
        "--public-callback-url",
        default=os.environ.get("YOUTUBE_WEBHOOK_CALLBACK_URL", ""),
    )
    parser.add_argument(
        "--webhook-token",
        default=os.environ.get("YOUTUBE_WEBHOOK_TOKEN"),
    )
    args = parser.parse_args()

    if not args.path.startswith("/"):
        parser.error("--path must start with /")
    if not args.public_callback_url:
        parser.error(
            "set --public-callback-url or YOUTUBE_WEBHOOK_CALLBACK_URL to the public HTTPS URL"
        )

    init_youtube_api_database(args.database, args.config_database)
    server = YouTubeWebhookServer(
        (args.host, args.port),
        database=args.database,
        callback_path=args.path,
        public_callback_url=args.public_callback_url,
        webhook_token=args.webhook_token,
    )
    token_mode = "required" if args.webhook_token else "disabled"
    print(
        f"YouTube webhook listening on http://{args.host}:{args.port}{args.path} "
        f"(token={token_mode})"
    )
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("Stopping YouTube webhook server.")
    finally:
        server.server_close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
