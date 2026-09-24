#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import os
import sqlite3
import time
import urllib.error
import urllib.parse
import urllib.request
from contextlib import closing
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import Any, Iterable

from time_utils import APP_TIMEZONE_INFO, DB_TIME_FORMAT, iso_to_db_time, now_db_time
from working_log import fail_job, finish_job, start_job
from youtube_api_db import (
    DEFAULT_API_DATABASE,
    DEFAULT_CONFIG_DATABASE,
    init_youtube_api_database,
)


DEFAULT_DATABASE = DEFAULT_API_DATABASE
YOUTUBE_VIDEOS_URL = "https://www.googleapis.com/youtube/v3/videos"
BATCH_SIZE = 50


@dataclass(frozen=True)
class Candidate:
    video_id: str
    channel_id: str
    vtuber_id: str | None


@dataclass(frozen=True)
class VideoObservation:
    video_id: str
    channel_id: str
    live_status: str
    title: str
    concurrent_viewers: int | None
    view_count: int | None
    like_count: int | None
    scheduled_start_at: str | None
    actual_start_at: str | None
    actual_end_at: str | None
    raw_json: str


def chunks(items: list[Candidate], size: int = BATCH_SIZE) -> Iterable[list[Candidate]]:
    for offset in range(0, len(items), size):
        yield items[offset : offset + size]


def nullable_int(value: object) -> int | None:
    if value is None:
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def next_check_time(seconds: int) -> str:
    return (
        datetime.now(APP_TIMEZONE_INFO) + timedelta(seconds=seconds)
    ).strftime(DB_TIME_FORMAT)


def classify_video(item: dict[str, Any]) -> str:
    snippet = item.get("snippet") or {}
    details = item.get("liveStreamingDetails")
    broadcast_content = snippet.get("liveBroadcastContent")
    if broadcast_content == "live":
        return "live"
    if broadcast_content == "upcoming":
        return "upcoming"
    if details:
        if details.get("actualEndTime") or details.get("actualStartTime"):
            return "completed"
        if details.get("scheduledStartTime"):
            return "not_live"
    return "not_live"


def parse_observation(item: dict[str, Any]) -> VideoObservation:
    snippet = item.get("snippet") or {}
    details = item.get("liveStreamingDetails") or {}
    statistics = item.get("statistics") or {}
    return VideoObservation(
        video_id=str(item["id"]),
        channel_id=str(snippet.get("channelId") or ""),
        live_status=classify_video(item),
        title=str(snippet.get("title") or ""),
        concurrent_viewers=nullable_int(details.get("concurrentViewers")),
        view_count=nullable_int(statistics.get("viewCount")),
        like_count=nullable_int(statistics.get("likeCount")),
        scheduled_start_at=iso_to_db_time(details.get("scheduledStartTime")),
        actual_start_at=iso_to_db_time(details.get("actualStartTime")),
        actual_end_at=iso_to_db_time(details.get("actualEndTime")),
        raw_json=json.dumps(item, ensure_ascii=False, separators=(",", ":")),
    )


def fetch_video_batch(
    api_key: str,
    candidates: list[Candidate],
    timeout: float,
) -> dict[str, VideoObservation]:
    query = urllib.parse.urlencode(
        {
            "part": "snippet,liveStreamingDetails,statistics,status",
            "id": ",".join(candidate.video_id for candidate in candidates),
            "key": api_key,
        }
    )
    request = urllib.request.Request(
        f"{YOUTUBE_VIDEOS_URL}?{query}",
        headers={"Accept": "application/json"},
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = json.load(response)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode("utf-8", errors="replace")
        raise RuntimeError(f"YouTube API HTTP {exc.code}: {body[:1000]}") from exc
    except (OSError, ValueError) as exc:
        raise RuntimeError(f"YouTube API request failed: {exc}") from exc

    return {
        observation.video_id: observation
        for observation in (
            parse_observation(item) for item in payload.get("items", [])
        )
    }


def read_due_candidates(
    conn: sqlite3.Connection,
    limit: int,
) -> list[Candidate]:
    rows = conn.execute(
        """
        SELECT video_id, channel_id, vtuber_id
        FROM youtube_api_candidate
        WHERE active = 1
          AND (next_check_at IS NULL OR next_check_at <= ?)
        ORDER BY
            CASE status
                WHEN 'live' THEN 0
                WHEN 'pending' THEN 1
                WHEN 'upcoming' THEN 2
                ELSE 3
            END,
            COALESCE(next_check_at, discovered_at),
            video_id
        LIMIT ?
        """,
        (now_db_time(), limit),
    ).fetchall()
    return [
        Candidate(str(row[0]), str(row[1]), str(row[2]) if row[2] else None)
        for row in rows
    ]


def insert_snapshot(
    conn: sqlite3.Connection,
    candidate: Candidate,
    observation: VideoObservation,
) -> None:
    conn.execute(
        """
        INSERT INTO youtube_api_snapshot (
            video_id,
            channel_id,
            vtuber_id,
            live_status,
            title,
            concurrent_viewers,
            view_count,
            like_count,
            scheduled_start_at,
            actual_start_at,
            actual_end_at,
            captured_at,
            raw_json
        )
        VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
        """,
        (
            observation.video_id,
            observation.channel_id,
            candidate.vtuber_id,
            observation.live_status,
            observation.title,
            observation.concurrent_viewers,
            observation.view_count,
            observation.like_count,
            observation.scheduled_start_at,
            observation.actual_start_at,
            observation.actual_end_at,
            now_db_time(),
            observation.raw_json,
        ),
    )


def update_current_status(
    conn: sqlite3.Connection,
    candidate: Candidate,
    observation: VideoObservation,
) -> None:
    if not candidate.vtuber_id:
        return
    current_time = now_db_time()
    if observation.live_status == "live":
        conn.execute(
            """
            INSERT INTO youtube_api_current_status (
                vtuber_id,
                channel_id,
                is_live,
                video_id,
                title,
                concurrent_viewers,
                scheduled_start_at,
                actual_start_at,
                last_checked_at,
                last_event_at,
                last_live_at
            )
            VALUES (?, ?, 1, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(vtuber_id) DO UPDATE SET
                channel_id = excluded.channel_id,
                is_live = 1,
                video_id = excluded.video_id,
                title = excluded.title,
                concurrent_viewers = excluded.concurrent_viewers,
                scheduled_start_at = excluded.scheduled_start_at,
                actual_start_at = excluded.actual_start_at,
                last_checked_at = excluded.last_checked_at,
                last_event_at = excluded.last_event_at,
                last_live_at = excluded.last_live_at
            """,
            (
                candidate.vtuber_id,
                observation.channel_id,
                observation.video_id,
                observation.title,
                observation.concurrent_viewers,
                observation.scheduled_start_at,
                observation.actual_start_at,
                current_time,
                current_time,
                current_time,
            ),
        )
        return

    conn.execute(
        """
        INSERT INTO youtube_api_current_status (
            vtuber_id,
            channel_id,
            is_live,
            video_id,
            title,
            concurrent_viewers,
            scheduled_start_at,
            actual_start_at,
            last_checked_at,
            last_event_at
        )
        VALUES (?, ?, 0, ?, ?, NULL, ?, ?, ?, ?)
        ON CONFLICT(vtuber_id) DO UPDATE SET
            channel_id = excluded.channel_id,
            is_live = 0,
            video_id = excluded.video_id,
            title = excluded.title,
            concurrent_viewers = NULL,
            scheduled_start_at = excluded.scheduled_start_at,
            actual_start_at = excluded.actual_start_at,
            last_checked_at = excluded.last_checked_at,
            last_event_at = excluded.last_event_at
        WHERE youtube_api_current_status.is_live = 0
           OR youtube_api_current_status.video_id = excluded.video_id
        """,
        (
            candidate.vtuber_id,
            observation.channel_id,
            observation.video_id,
            observation.title,
            observation.scheduled_start_at,
            observation.actual_start_at,
            current_time,
            current_time,
        ),
    )


def record_observation(
    conn: sqlite3.Connection,
    candidate: Candidate,
    observation: VideoObservation,
    interval_seconds: int,
) -> str:
    if observation.channel_id != candidate.channel_id:
        conn.execute(
            """
            UPDATE youtube_api_candidate
            SET status = 'channel_mismatch',
                active = 0,
                last_checked_at = ?,
                consecutive_errors = 0,
                last_error = ?
            WHERE video_id = ?
            """,
            (
                now_db_time(),
                f"expected channel {candidate.channel_id}, got {observation.channel_id}",
                candidate.video_id,
            ),
        )
        return "channel_mismatch"

    active = int(observation.live_status in {"live", "upcoming"})
    conn.execute(
        """
        UPDATE youtube_api_candidate
        SET status = ?,
            active = ?,
            title = ?,
            last_checked_at = ?,
            next_check_at = ?,
            scheduled_start_at = ?,
            actual_start_at = ?,
            actual_end_at = ?,
            consecutive_errors = 0,
            last_error = NULL
        WHERE video_id = ?
        """,
        (
            observation.live_status,
            active,
            observation.title,
            now_db_time(),
            next_check_time(interval_seconds) if active else None,
            observation.scheduled_start_at,
            observation.actual_start_at,
            observation.actual_end_at,
            candidate.video_id,
        ),
    )
    insert_snapshot(conn, candidate, observation)
    update_current_status(conn, candidate, observation)
    return observation.live_status


def record_unavailable(conn: sqlite3.Connection, candidate: Candidate) -> None:
    conn.execute(
        """
        UPDATE youtube_api_candidate
        SET status = 'unavailable',
            active = 0,
            last_checked_at = ?,
            consecutive_errors = 0,
            last_error = 'videos.list did not return this video id'
        WHERE video_id = ?
        """,
        (now_db_time(), candidate.video_id),
    )
    if candidate.vtuber_id:
        conn.execute(
            """
            UPDATE youtube_api_current_status
            SET is_live = 0,
                concurrent_viewers = NULL,
                last_checked_at = ?
            WHERE vtuber_id = ?
              AND video_id = ?
            """,
            (now_db_time(), candidate.vtuber_id, candidate.video_id),
        )


def record_batch_error(
    conn: sqlite3.Connection,
    candidates: list[Candidate],
    message: str,
    retry_seconds: int,
) -> None:
    for candidate in candidates:
        conn.execute(
            """
            UPDATE youtube_api_candidate
            SET status = 'error',
                last_checked_at = ?,
                next_check_at = ?,
                consecutive_errors = consecutive_errors + 1,
                last_error = ?
            WHERE video_id = ?
            """,
            (
                now_db_time(),
                next_check_time(retry_seconds),
                message,
                candidate.video_id,
            ),
        )


def collect_youtube_api(
    database: str,
    api_key: str,
    *,
    config_database: str | None = DEFAULT_CONFIG_DATABASE,
    limit: int = 1500,
    interval_seconds: int = 300,
    retry_seconds: int = 60,
    timeout: float = 20,
) -> dict[str, Any]:
    started = time.perf_counter()
    init_youtube_api_database(database, config_database)
    working_id: int | None = None
    errors: list[str] = []
    quota_units = 0
    checked = 0
    snapshots_inserted = 0
    live = 0
    upcoming = 0

    try:
        with closing(sqlite3.connect(database, timeout=30)) as conn:
            conn.execute("PRAGMA foreign_keys = ON")
            working_id = start_job(conn, "youtube_api_collector", "youtube")
            candidates = read_due_candidates(conn, limit)
            conn.commit()

        for batch in chunks(candidates):
            quota_units += 1
            try:
                observations = fetch_video_batch(api_key, batch, timeout)
            except RuntimeError as exc:
                message = str(exc)
                errors.append(message)
                with closing(sqlite3.connect(database, timeout=30)) as conn:
                    record_batch_error(conn, batch, message, retry_seconds)
                    conn.commit()
                continue

            with closing(sqlite3.connect(database, timeout=30)) as conn:
                conn.execute("PRAGMA foreign_keys = ON")
                for candidate in batch:
                    observation = observations.get(candidate.video_id)
                    if observation is None:
                        record_unavailable(conn, candidate)
                        checked += 1
                        continue
                    status = record_observation(
                        conn,
                        candidate,
                        observation,
                        interval_seconds,
                    )
                    snapshots_inserted += int(status != "channel_mismatch")
                    checked += 1
                    live += int(status == "live")
                    upcoming += int(status == "upcoming")
                conn.commit()

        elapsed = time.perf_counter() - started
        with closing(sqlite3.connect(database, timeout=30)) as conn:
            if working_id is not None:
                finish_job(
                    conn,
                    working_id,
                    status="partial_success" if errors else "success",
                    elapsed_seconds=elapsed,
                    checked_count=checked,
                    live_count=live,
                    offline_count=max(checked - live - upcoming, 0),
                    snapshots_inserted=snapshots_inserted,
                    error_count=len(errors),
                    error_message="\n".join(errors) if errors else None,
                )
                conn.commit()
        return {
            "status": "partial_success" if errors else "success",
            "candidates": len(candidates),
            "checked": checked,
            "live": live,
            "upcoming": upcoming,
            "quota_units": quota_units,
            "errors": errors,
            "elapsed_seconds": round(elapsed, 3),
        }
    except Exception as exc:
        elapsed = time.perf_counter() - started
        if working_id is not None:
            with closing(sqlite3.connect(database, timeout=30)) as conn:
                fail_job(
                    conn,
                    working_id,
                    elapsed_seconds=elapsed,
                    error_message=str(exc),
                )
                conn.commit()
        raise


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Check WebSub candidate videos with YouTube Data API videos.list."
    )
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument("--api-key", default=os.environ.get("YOUTUBE_API_KEY"))
    parser.add_argument("--limit", type=int, default=1500)
    parser.add_argument("--interval-seconds", type=int, default=300)
    parser.add_argument("--retry-seconds", type=int, default=60)
    parser.add_argument("--timeout", type=float, default=20)
    args = parser.parse_args()

    if not args.api_key:
        parser.error("set --api-key or YOUTUBE_API_KEY")
    if args.limit <= 0 or args.limit > 1700:
        parser.error("--limit must be between 1 and 1700")
    if args.interval_seconds <= 0 or args.retry_seconds <= 0:
        parser.error("interval values must be greater than zero")

    summary = collect_youtube_api(
        args.database,
        args.api_key,
        config_database=args.config_database,
        limit=args.limit,
        interval_seconds=args.interval_seconds,
        retry_seconds=args.retry_seconds,
        timeout=args.timeout,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))
    return 1 if summary["status"] == "partial_success" else 0


if __name__ == "__main__":
    raise SystemExit(main())
