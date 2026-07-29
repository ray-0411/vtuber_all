#!/usr/bin/env python3
"""
Run the live-status collector repeatedly on a local machine.

Usage:
    python src/run_local_scheduler.py
    python src/run_local_scheduler.py --once
    python src/run_local_scheduler.py --interval-seconds 300
"""

from __future__ import annotations

import argparse
import ctypes
import multiprocessing
import os
import queue
import sqlite3
import sys
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta
from zoneinfo import ZoneInfo

from collect_all import DEFAULT_CONFIG_DATABASE, DEFAULT_DATABASE, collect_all
from init_db import init_database
from init_streamer_config import DEFAULT_GROUPS
from create_streamer_group import create_streamer_group
from time_utils import now_db_time


DEFAULT_INTERVAL_SECONDS = 300
DEFAULT_COLLECTION_TIMEOUT_SECONDS = 240
DEFAULT_TIMEZONE = "Asia/Taipei"
COLLECTOR_JOB_NAMES = ("collect_all", "youtube_collector", "twitch_collector")


@dataclass(frozen=True)
class LiveStatusRow:
    platform: str
    vtuber_id: str
    name: str
    viewer_count: int | None
    title: str | None
    stream_url: str | None


def configure_output_encoding() -> None:
    for stream in (sys.stdout, sys.stderr):
        if hasattr(stream, "reconfigure"):
            stream.reconfigure(encoding="utf-8", errors="replace")


def now_text(timezone_name: str) -> str:
    return datetime.now(ZoneInfo(timezone_name)).isoformat(timespec="seconds")


def next_run_time(timezone_name: str, interval_seconds: int) -> datetime:
    zone = ZoneInfo(timezone_name)
    now = datetime.now(zone)
    day_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    elapsed_seconds = (now - day_start).total_seconds()
    next_elapsed = ((int(elapsed_seconds) // interval_seconds) + 1) * interval_seconds
    return day_start + timedelta(seconds=next_elapsed)


def seconds_until(target: datetime) -> float:
    return max(0.0, (target - datetime.now(target.tzinfo)).total_seconds())


def process_is_running(pid: int) -> bool:
    if pid <= 0:
        return False
    if os.name == "nt":
        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        ctypes.windll.kernel32.CloseHandle(handle)
        return True

    try:
        os.kill(pid, 0)
    except OSError:
        return False
    return True


def lock_path_for_database(database: str) -> str:
    return f"{os.path.abspath(database)}.collect.lock"


def read_lock_pids(lock_path: str) -> list[int]:
    try:
        with open(lock_path, encoding="utf-8") as file:
            lines = [line.strip().lstrip("\ufeff") for line in file]
    except OSError:
        return []

    pids: list[int] = []
    for line in lines:
        try:
            pids.append(int(line))
        except ValueError:
            continue
    return pids


def write_collection_lock(lock_path: str, pids: list[int]) -> None:
    payload = "".join(f"{pid}\n" for pid in pids)
    payload += f"{now_db_time()}\n"
    with open(lock_path, "w", encoding="utf-8") as file:
        file.write(payload)


def lock_has_running_process(lock_path: str) -> bool:
    return any(process_is_running(pid) for pid in read_lock_pids(lock_path))


def acquire_collection_lock(database: str) -> tuple[int, str] | None:
    lock_path = lock_path_for_database(database)

    while True:
        try:
            fd = os.open(lock_path, os.O_CREAT | os.O_EXCL | os.O_WRONLY)
        except FileExistsError:
            if lock_has_running_process(lock_path):
                return None
            try:
                os.unlink(lock_path)
            except FileNotFoundError:
                continue
            except OSError:
                return None
            continue

        with os.fdopen(fd, "w", encoding="utf-8") as file:
            file.write(f"{os.getpid()}\n{now_db_time()}\n")
        return os.open(lock_path, os.O_RDONLY), lock_path


def release_collection_lock(lock: tuple[int, str]) -> None:
    fd, lock_path = lock
    try:
        os.close(fd)
    except OSError:
        pass
    try:
        os.unlink(lock_path)
    except FileNotFoundError:
        pass


def initialize_databases(database: str, config_database: str) -> None:
    init_database(database)
    for group in DEFAULT_GROUPS:
        create_streamer_group(config_database, group)


def read_current_lives(database: str) -> list[LiveStatusRow]:
    with sqlite3.connect(database) as conn:
        rows = conn.execute(
            """
            SELECT
                current_live_status.platform,
                current_live_status.vtuber_id,
                streamer.name,
                current_live_status.viewer_count,
                stream_title.title,
                current_live_status.stream_url
            FROM current_live_status
            JOIN streamer
              ON streamer.vtuber_id = current_live_status.vtuber_id
            LEFT JOIN stream_title
              ON stream_title.title_id = current_live_status.title_id
            WHERE current_live_status.is_live = 1
            ORDER BY current_live_status.platform, streamer.group_name, streamer.display_order
            """
        ).fetchall()

    return [
        LiveStatusRow(
            platform=row[0],
            vtuber_id=row[1],
            name=row[2],
            viewer_count=row[3],
            title=row[4],
            stream_url=row[5],
        )
        for row in rows
    ]


def latest_working_id(database: str) -> int:
    with sqlite3.connect(database) as conn:
        row = conn.execute("SELECT COALESCE(MAX(working_id), 0) FROM working").fetchone()
    return int(row[0])


def print_live_report(database: str) -> None:
    lives = read_current_lives(database)
    by_platform = {
        "youtube": [live for live in lives if live.platform == "youtube"],
        "twitch": [live for live in lives if live.platform == "twitch"],
    }

    print("", flush=True)
    for platform, platform_lives in by_platform.items():
        print(f"{platform.upper()} live: {len(platform_lives)}", flush=True)
        if not platform_lives:
            print("- none", flush=True)
            continue

        for live in platform_lives:
            viewer_text = "unknown" if live.viewer_count is None else str(live.viewer_count)
            print(f"- {live.name}: {viewer_text}", flush=True)

    print(f"TOTAL live now: {len(lives)}", flush=True)


def print_error_report(summary: dict[str, object]) -> None:
    errors: list[str] = []

    top_level_errors = summary.get("errors", [])
    if isinstance(top_level_errors, list):
        errors.extend(str(error) for error in top_level_errors)

    results = summary.get("results", {})
    if isinstance(results, dict):
        for platform, result in results.items():
            if not isinstance(result, dict):
                continue
            platform_errors = result.get("errors", [])
            if isinstance(platform_errors, list):
                errors.extend(f"{platform}: {error}" for error in platform_errors)

    print("", flush=True)
    if not errors:
        print("ERRORS: none", flush=True)
        return

    print(f"ERRORS: {len(errors)}", flush=True)
    for error in errors:
        print(f"- {error}", flush=True)


def collect_all_worker(
    database: str,
    config_database: str,
    result_queue: multiprocessing.Queue,
) -> None:
    try:
        summary = collect_all(database, config_database)
        queue_summary = dict(summary)
        top_errors = summary.get("errors", [])
        if isinstance(top_errors, list) and len(top_errors) > 20:
            queue_summary["errors"] = [
                *top_errors[:20],
                f"... {len(top_errors) - 20} more errors; see working.error_message",
            ]

        results = summary.get("results", {})
        if isinstance(results, dict):
            queue_results = {}
            for platform, result in results.items():
                if not isinstance(result, dict):
                    queue_results[platform] = result
                    continue
                queue_result = dict(result)
                platform_errors = result.get("errors", [])
                if isinstance(platform_errors, list) and len(platform_errors) > 20:
                    queue_result["errors"] = [
                        *platform_errors[:20],
                        f"... {len(platform_errors) - 20} more errors; "
                        "see working.error_message",
                    ]
                queue_results[platform] = queue_result
            queue_summary["results"] = queue_results

        result_queue.put(("success", queue_summary))
    except BaseException as exc:
        result_queue.put(
            (
                "error",
                type(exc).__name__,
                str(exc),
                traceback.format_exc(),
            )
        )


def fail_timed_out_jobs(
    database: str,
    started_at: str,
    working_id_after: int,
    elapsed_seconds: float,
    timeout_seconds: int,
) -> None:
    current_time = now_db_time()
    error_message = (
        f"collection timeout: exceeded {timeout_seconds} seconds; "
        "unfinished checks in this run were counted as errors"
    )
    placeholders = ",".join("?" for _ in COLLECTOR_JOB_NAMES)
    with sqlite3.connect(database) as conn:
        cursor = conn.execute(
            f"""
            UPDATE working
            SET
                status = 'failed',
                finished_at = ?,
                elapsed_seconds = ?,
                error_count = CASE
                    WHEN error_count > 0 THEN error_count
                    ELSE 1
                END,
                error_message = CASE
                    WHEN error_message IS NULL OR error_message = '' THEN ?
                    ELSE error_message || char(10) || ?
                END
            WHERE status = 'running'
              AND working_id > ?
              AND job_name IN ({placeholders})
            """,
            (
                current_time,
                elapsed_seconds,
                error_message,
                error_message,
                working_id_after,
                *COLLECTOR_JOB_NAMES,
            ),
        )
        if cursor.rowcount == 0:
            conn.execute(
                """
                INSERT INTO working (
                    job_name,
                    platform,
                    started_at,
                    status,
                    finished_at,
                    elapsed_seconds,
                    error_count,
                    error_message
                )
                VALUES ('collect_all', NULL, ?, 'failed', ?, ?, 1, ?)
                """,
                (
                    started_at,
                    current_time,
                    elapsed_seconds,
                    error_message,
                ),
            )


def cleanup_stale_running_jobs(database: str, timeout_seconds: int) -> int:
    current_time = now_db_time()
    error_message = (
        f"stale running job cleaned on scheduler startup after exceeding "
        f"{timeout_seconds} seconds"
    )
    placeholders = ",".join("?" for _ in COLLECTOR_JOB_NAMES)
    with sqlite3.connect(database) as conn:
        cursor = conn.execute(
            f"""
            UPDATE working
            SET
                status = 'failed',
                finished_at = ?,
                elapsed_seconds = MAX(
                    0,
                    (julianday(?) - julianday(started_at)) * 86400.0
                ),
                error_count = CASE
                    WHEN error_count > 0 THEN error_count
                    ELSE 1
                END,
                error_message = CASE
                    WHEN error_message IS NULL OR error_message = '' THEN ?
                    ELSE error_message || char(10) || ?
                END
            WHERE status = 'running'
              AND started_at <= datetime('now', '+8 hours', ?)
              AND job_name IN ({placeholders})
            """,
            (
                current_time,
                current_time,
                error_message,
                error_message,
                f"-{timeout_seconds} seconds",
                *COLLECTOR_JOB_NAMES,
            ),
        )
    return cursor.rowcount


def run_collect_all_with_timeout(
    database: str,
    config_database: str,
    timeout_seconds: int,
    lock_path: str | None = None,
) -> dict[str, object]:
    result_queue: multiprocessing.Queue = multiprocessing.Queue()
    process = multiprocessing.Process(
        target=collect_all_worker,
        args=(database, config_database, result_queue),
    )
    process.start()
    if lock_path is not None:
        write_collection_lock(lock_path, [os.getpid(), process.pid or 0])
    process.join(timeout_seconds)

    if process.is_alive():
        process.terminate()
        process.join(10)
        if process.is_alive():
            process.kill()
            process.join(5)
        raise TimeoutError(f"collect_all exceeded {timeout_seconds} seconds")

    try:
        result = result_queue.get_nowait()
    except queue.Empty as exc:
        if process.exitcode == 0:
            raise RuntimeError("collect_all finished without returning a summary") from exc
        raise RuntimeError(f"collect_all exited with code {process.exitcode}") from exc

    if result[0] == "success":
        return result[1]

    _, exc_type, message, formatted_traceback = result
    raise RuntimeError(f"{exc_type}: {message}\n{formatted_traceback}")


def run_once(
    database: str,
    config_database: str,
    timezone_name: str,
    timeout_seconds: int,
) -> int:
    lock = acquire_collection_lock(database)
    if lock is None:
        print(
            f"[{now_text(timezone_name)}] collect skipped: another collection is already running",
            flush=True,
        )
        return 1

    started = time.perf_counter()
    started_at = now_db_time()
    working_id_after = latest_working_id(database)
    print(f"[{now_text(timezone_name)}] collect start", flush=True)
    try:
        try:
            summary = run_collect_all_with_timeout(
                database,
                config_database,
                timeout_seconds,
                lock_path=lock[1],
            )
        except TimeoutError as exc:
            elapsed = time.perf_counter() - started
            fail_timed_out_jobs(database, started_at, working_id_after, elapsed, timeout_seconds)
            print(
                f"[{now_text(timezone_name)}] collect timeout after {elapsed:.2f}s: {exc}",
                file=sys.stderr,
                flush=True,
            )
            print_live_report(database)
            print_error_report(
                {
                    "errors": [
                        f"collect_all: exceeded {timeout_seconds} seconds; "
                        "unfinished checks in this run were counted as errors"
                    ],
                    "results": {},
                }
            )
            return 1

        elapsed = time.perf_counter() - started

        print(
            "[{time}] collect done status={status} checked={checked} live={live} "
            "offline={offline} snapshots_inserted={snapshots_inserted} "
            "synced_streamers={synced_streamers} errors={errors} elapsed_seconds={elapsed:.2f}".format(
                time=now_text(timezone_name),
                status=summary["status"],
                checked=summary["checked"],
                live=summary["live"],
                offline=summary["offline"],
                snapshots_inserted=summary["snapshots_inserted"],
                synced_streamers=summary["synced_streamers"],
                errors=len(summary["errors"]),
                elapsed=elapsed,
            ),
            flush=True,
        )

        print_live_report(database)
        print_error_report(summary)
        return 0 if summary["status"] in {"success", "partial_success"} else 1
    finally:
        release_collection_lock(lock)


def main() -> int:
    configure_output_encoding()

    parser = argparse.ArgumentParser(description="Run collect_all repeatedly on this machine.")
    parser.add_argument("--database", default=DEFAULT_DATABASE)
    parser.add_argument("--config-database", default=DEFAULT_CONFIG_DATABASE)
    parser.add_argument("--interval-seconds", type=int, default=DEFAULT_INTERVAL_SECONDS)
    parser.add_argument(
        "--collection-timeout-seconds",
        type=int,
        default=DEFAULT_COLLECTION_TIMEOUT_SECONDS,
        help="Stop one collection run after this many seconds.",
    )
    parser.add_argument("--timezone", default=DEFAULT_TIMEZONE)
    parser.add_argument("--once", action="store_true", help="Run one collection and exit.")
    parser.add_argument(
        "--run-immediately",
        action="store_true",
        help="Run once immediately, then continue on the aligned schedule.",
    )
    parser.add_argument(
        "--skip-init",
        action="store_true",
        help="Do not initialize database schemas before collecting.",
    )
    args = parser.parse_args()

    if args.interval_seconds <= 0:
        parser.error("--interval-seconds must be greater than 0")
    if args.collection_timeout_seconds <= 0:
        parser.error("--collection-timeout-seconds must be greater than 0")

    if not args.skip_init:
        initialize_databases(args.database, args.config_database)

    cleaned_count = cleanup_stale_running_jobs(args.database, args.collection_timeout_seconds)
    if cleaned_count:
        print(
            f"[{now_text(args.timezone)}] cleaned stale running jobs: {cleaned_count}",
            flush=True,
        )

    print(
        f"[{now_text(args.timezone)}] scheduler timezone={args.timezone} "
        f"interval_seconds={args.interval_seconds} "
        f"collection_timeout_seconds={args.collection_timeout_seconds} aligned=true",
        flush=True,
    )

    exit_code = 0
    should_run_now = args.once or args.run_immediately
    while True:
        if should_run_now:
            try:
                exit_code = max(
                    exit_code,
                    run_once(
                        args.database,
                        args.config_database,
                        args.timezone,
                        args.collection_timeout_seconds,
                    ),
                )
            except KeyboardInterrupt:
                print(f"[{now_text(args.timezone)}] stopped by user", flush=True)
                return exit_code
            except Exception as exc:
                exit_code = 1
                print(
                    f"[{now_text(args.timezone)}] collect failed {type(exc).__name__}: {exc}",
                    file=sys.stderr,
                    flush=True,
                )
                traceback.print_exc()

            if args.once:
                return exit_code

        target = next_run_time(args.timezone, args.interval_seconds)
        sleep_seconds = seconds_until(target)
        print(
            f"[{now_text(args.timezone)}] next run at "
            f"{target.isoformat(timespec='seconds')} sleep {sleep_seconds:.0f} seconds",
            flush=True,
        )
        try:
            time.sleep(sleep_seconds)
        except KeyboardInterrupt:
            print(f"[{now_text(args.timezone)}] stopped by user", flush=True)
            return exit_code
        should_run_now = True


if __name__ == "__main__":
    multiprocessing.freeze_support()
    raise SystemExit(main())
