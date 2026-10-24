#!/usr/bin/env python3
"""Periodically publish changed collector SQLite data to Supabase."""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path


TOOL_DIR = Path(__file__).resolve().parents[1]
PROJECT_DIR = TOOL_DIR.parents[1] / "database/main"
DATA_DIR = TOOL_DIR.parents[1] / "database/published"


def clock_text(value: datetime | None = None) -> str:
    return (value or datetime.now().astimezone()).strftime("%H:%M:%S")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--interval-seconds", type=int, default=1800)
    parser.add_argument(
        "--minute-offset",
        type=int,
        default=3,
        help="align regular runs to this minute offset within the interval",
    )
    parser.add_argument(
        "--retry-interval-minutes",
        type=int,
        default=5,
        help="when collector is busy, retry at the next matching minute",
    )
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--force", action="store_true", help="upload even if sources are unchanged")
    parser.add_argument("--dry-run", action="store_true", help="build and validate without network access")
    parser.add_argument("--current", type=Path, default=PROJECT_DIR / "live_data.db")
    parser.add_argument("--audience", type=Path, default=PROJECT_DIR / "streamer_audience.db")
    return parser.parse_args()


def fingerprint(paths: tuple[Path, ...]) -> dict[str, dict[str, int]]:
    result = {}
    for path in paths:
        stat = path.resolve().stat()
        result[str(path.resolve())] = {"size": stat.st_size, "mtime_ns": stat.st_mtime_ns}
    return result


def run_script(name: str, *arguments: str) -> None:
    command = [sys.executable, str(TOOL_DIR / "scripts" / name), *arguments]
    subprocess.run(command, cwd=TOOL_DIR, check=True)


def collector_is_running(current: Path) -> bool:
    return Path(f"{current.resolve()}.collect.lock").exists()


def print_banner(interval_seconds: int, minute_offset: int) -> None:
    minutes = interval_seconds // 60
    print("=" * 60)
    print("  VTuber Supabase 定期更新程式")
    print("=" * 60)
    print(f"每 {minutes} 分鐘檢查一次 live_data.db，有變更才會上傳。")
    if interval_seconds == 1800:
        print(f"固定在每小時 {minute_offset:02d} 分及 {minute_offset + 30:02d} 分執行。")
    print("streamer_audience.db 只會讀取，不會重新抓取 audience。")
    print("外層 live_data.db 只會讀取，絕對不會修改。")
    print("視窗會顯示本次結果及下次預定更新時間。")
    print("請保持視窗開啟；按 Ctrl+C 可以停止排程。")


def publish(args: argparse.Namespace) -> str:
    current = args.current.resolve()
    audience = args.audience.resolve()
    if collector_is_running(current):
        print(f"[{clock_text()}] Collector 正在執行，本次上傳已安全延後。")
        return "deferred"

    state_path = TOOL_DIR.parents[1] / "other/log-data/periodic_upload_state-publish.json"
    before = fingerprint((current, audience))
    if state_path.is_file() and not args.force and not args.dry_run:
        state = json.loads(state_path.read_text(encoding="utf-8"))
        if state.get("sources") == before:
            print(f"[{clock_text()}] 資料沒有變更，本次不需要上傳。")
            return "complete"

    run_script(
        "prepare_current_database.py",
        "--current", str(current), "--audience", str(audience),
        "--output", str(DATA_DIR / "merged_live_data.db"),
    )
    run_script(
        "build_analytics_cache.py",
        "--source", str(DATA_DIR / "merged_live_data.db"),
        "--output", str(DATA_DIR / "merged_analytics_cache.db"),
    )
    sync_arguments = ["--dry-run"] if args.dry_run else ["--confirm-replace"]
    run_script("sync_merged_to_postgres.py", *sync_arguments)
    if not args.dry_run:
        state_path.parent.mkdir(parents=True, exist_ok=True)
        state_path.write_text(
            json.dumps(
                {"uploaded_at": datetime.now().astimezone().isoformat(timespec="seconds"), "sources": before},
                ensure_ascii=False,
                indent=2,
            ) + "\n",
            encoding="utf-8",
        )
        print(f"[{clock_text()}] 本次更新成功，Supabase 已更新。")
    else:
        print(f"[{clock_text()}] 離線測試成功，Supabase 沒有被修改。")
    return "complete"


def next_matching_time(interval_minutes: int, offset: int) -> datetime:
    candidate = datetime.now().astimezone().replace(second=0, microsecond=0) + timedelta(minutes=1)
    while candidate.minute % interval_minutes != offset % interval_minutes:
        candidate += timedelta(minutes=1)
    return candidate


def main() -> int:
    args = parse_args()
    if args.interval_seconds < 60 and not args.once:
        raise ValueError("interval must be at least 60 seconds")
    if args.interval_seconds % 60:
        raise ValueError("interval must be a whole number of minutes")
    if args.retry_interval_minutes < 1:
        raise ValueError("retry interval must be at least one minute")
    print_banner(args.interval_seconds, args.minute_offset)
    while True:
        started_at = datetime.now().astimezone()
        print("", flush=True)
        print("=" * 60, flush=True)
        print(f"本次更新時間：{clock_text(started_at)}", flush=True)
        result = "failed"
        try:
            result = publish(args)
        except Exception as exc:
            print(f"[{clock_text()}] 本次更新失敗：{exc}", file=sys.stderr, flush=True)
            if args.once:
                return 1
        if args.once:
            return 0
        if result == "deferred":
            next_check = next_matching_time(args.retry_interval_minutes, args.minute_offset)
            print("Collector 完成後會提早重試，不必等待完整半小時。", flush=True)
        else:
            next_check = next_matching_time(args.interval_seconds // 60, args.minute_offset)
        print(f"下次預定更新時間：{clock_text(next_check)}", flush=True)
        print("排程仍在執行中；按 Ctrl+C 可以停止。", flush=True)
        time.sleep(max(0, (next_check - datetime.now().astimezone()).total_seconds()))


if __name__ == "__main__":
    raise SystemExit(main())
