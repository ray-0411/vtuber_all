from __future__ import annotations

import hashlib
import hmac
import sqlite3
import xml.etree.ElementTree as ET
from dataclasses import dataclass
from datetime import datetime, timedelta
from urllib.parse import parse_qs, urlencode, urlparse, urlunparse

from time_utils import APP_TIMEZONE_INFO, DB_TIME_FORMAT, iso_to_db_time, now_db_time


ATOM = "http://www.w3.org/2005/Atom"
YT = "http://www.youtube.com/xml/schemas/2015"
TOMBSTONES = "http://purl.org/atompub/tombstones/1.0"
YOUTUBE_TOPIC_PREFIX = "https://www.youtube.com/feeds/videos.xml?channel_id="


@dataclass(frozen=True)
class WebSubEvent:
    channel_id: str
    video_id: str
    event_kind: str
    title: str | None
    published_at: str | None
    updated_at: str | None


def topic_url(channel_id: str) -> str:
    return f"{YOUTUBE_TOPIC_PREFIX}{channel_id}"


def channel_id_from_topic(value: str | None) -> str | None:
    if not value:
        return None
    parsed = urlparse(value)
    if parsed.netloc.lower() not in {"www.youtube.com", "youtube.com"}:
        return None
    if parsed.path not in {"/feeds/videos.xml", "/xml/feeds/videos.xml"}:
        return None
    channel_id = parse_qs(parsed.query).get("channel_id", [None])[0]
    return channel_id or None


def callback_with_token(callback_url: str, token: str | None) -> str:
    if not token:
        return callback_url
    parsed = urlparse(callback_url)
    query = parse_qs(parsed.query, keep_blank_values=True)
    query["token"] = [token]
    return urlunparse(parsed._replace(query=urlencode(query, doseq=True)))


def lease_expiry(lease_seconds: int | None) -> str | None:
    if lease_seconds is None:
        return None
    return (
        datetime.now(APP_TIMEZONE_INFO) + timedelta(seconds=lease_seconds)
    ).strftime(DB_TIME_FORMAT)


def parse_atom_events(payload: bytes) -> list[WebSubEvent]:
    upper_payload = payload.upper()
    if b"<!DOCTYPE" in upper_payload or b"<!ENTITY" in upper_payload:
        raise ValueError("DTD and XML entities are not accepted")
    root = ET.fromstring(payload)
    feed_channel_id = None
    for link in root.findall(f"{{{ATOM}}}link"):
        if link.get("rel") == "self":
            feed_channel_id = channel_id_from_topic(link.get("href"))
            if feed_channel_id:
                break

    events: list[WebSubEvent] = []
    for entry in root.findall(f"{{{ATOM}}}entry"):
        video_id = entry.findtext(f"{{{YT}}}videoId")
        channel_id = entry.findtext(f"{{{YT}}}channelId") or feed_channel_id
        if not video_id or not channel_id:
            continue
        events.append(
            WebSubEvent(
                channel_id=channel_id,
                video_id=video_id,
                event_kind="upsert",
                title=entry.findtext(f"{{{ATOM}}}title"),
                published_at=iso_to_db_time(entry.findtext(f"{{{ATOM}}}published")),
                updated_at=iso_to_db_time(entry.findtext(f"{{{ATOM}}}updated")),
            )
        )

    for deleted in root.findall(f"{{{TOMBSTONES}}}deleted-entry"):
        ref = deleted.get("ref") or ""
        video_id = ref.removeprefix("yt:video:")
        if video_id and feed_channel_id:
            events.append(
                WebSubEvent(
                    channel_id=feed_channel_id,
                    video_id=video_id,
                    event_kind="deleted",
                    title=None,
                    published_at=None,
                    updated_at=iso_to_db_time(deleted.get("when")),
                )
            )
    return events


def known_channel(conn: sqlite3.Connection, channel_id: str) -> tuple[str, str] | None:
    row = conn.execute(
        """
        SELECT vtuber_id, youtube_channel_id
        FROM streamer
        WHERE enabled = 1
          AND youtube_channel_id = ?
        LIMIT 1
        """,
        (channel_id,),
    ).fetchone()
    if row is None:
        return None
    return str(row[0]), str(row[1])


def record_events(
    conn: sqlite3.Connection,
    events: list[WebSubEvent],
    raw_xml: str,
) -> int:
    inserted = 0
    current_time = now_db_time()
    for event in events:
        streamer = known_channel(conn, event.channel_id)
        if streamer is None:
            continue
        vtuber_id, _ = streamer
        cursor = conn.execute(
            """
            INSERT OR IGNORE INTO youtube_websub_event (
                channel_id,
                video_id,
                event_kind,
                title,
                published_at,
                event_updated_at,
                received_at,
                raw_xml
            )
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.channel_id,
                event.video_id,
                event.event_kind,
                event.title,
                event.published_at,
                event.updated_at,
                current_time,
                raw_xml,
            ),
        )
        inserted += int(cursor.rowcount > 0)

        if event.event_kind == "deleted":
            conn.execute(
                """
                UPDATE youtube_api_candidate
                SET status = 'deleted',
                    active = 0,
                    last_event_at = ?,
                    last_error = NULL
                WHERE video_id = ?
                """,
                (current_time, event.video_id),
            )
            conn.execute(
                """
                UPDATE youtube_api_current_status
                SET is_live = 0,
                    concurrent_viewers = NULL,
                    last_checked_at = ?
                WHERE vtuber_id = ?
                  AND video_id = ?
                """,
                (current_time, vtuber_id, event.video_id),
            )
            continue

        conn.execute(
            """
            INSERT INTO youtube_api_candidate (
                video_id,
                channel_id,
                vtuber_id,
                source,
                status,
                active,
                title,
                discovered_at,
                last_event_at,
                next_check_at
            )
            VALUES (?, ?, ?, 'websub', 'pending', 1, ?, ?, ?, ?)
            ON CONFLICT(video_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                vtuber_id = excluded.vtuber_id,
                title = COALESCE(excluded.title, youtube_api_candidate.title),
                active = 1,
                last_event_at = excluded.last_event_at,
                next_check_at = excluded.next_check_at,
                last_error = NULL
            """,
            (
                event.video_id,
                event.channel_id,
                vtuber_id,
                event.title,
                current_time,
                current_time,
                current_time,
            ),
        )
    return inserted


def valid_token(expected: str | None, actual: str | None) -> bool:
    if not expected:
        return True
    return bool(actual) and hmac.compare_digest(expected, actual)


def payload_sha256(payload: bytes) -> str:
    return hashlib.sha256(payload).hexdigest()
