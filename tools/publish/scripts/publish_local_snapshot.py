#!/usr/bin/env python3
"""Build and atomically activate a versioned local API database snapshot."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import time
import uuid
from datetime import datetime
from pathlib import Path


ROOT = Path(__file__).resolve().parents[3]
DEFAULT_MAIN = ROOT / "database" / "main"
DEFAULT_PUBLISHED = ROOT / "database" / "published"
MANIFEST_NAME = "current_snapshot.json"
LIVE_PATTERN = re.compile(r"^merged_live_data\.(.+)\.db$")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--current", type=Path, default=DEFAULT_MAIN / "live_data.db")
    parser.add_argument(
        "--audience", type=Path, default=DEFAULT_MAIN / "streamer_audience.db"
    )
    parser.add_argument("--publish-dir", type=Path, default=DEFAULT_PUBLISHED)
    return parser.parse_args()


def read_current_manifest(manifest: Path) -> dict | None:
    try:
        data = json.loads(manifest.read_text(encoding="utf-8"))
        database_name = data["database"]
        cache_name = data["analytics_cache"]
    except (OSError, json.JSONDecodeError, KeyError, TypeError):
        return None
    if Path(database_name).name != database_name or Path(cache_name).name != cache_name:
        return None
    if not (manifest.parent / database_name).is_file():
        return None
    if not (manifest.parent / cache_name).is_file():
        return None
    return data


def replace_manifest(temporary: Path, manifest: Path) -> None:
    deadline = time.monotonic() + 30
    while True:
        try:
            os.replace(temporary, manifest)
            return
        except PermissionError:
            if time.monotonic() >= deadline:
                raise
            time.sleep(0.25)


def cleanup_old_generations(publish_dir: Path, keep: set[str]) -> None:
    generations: dict[str, float] = {}
    for path in publish_dir.glob("merged_live_data.*.db"):
        match = LIVE_PATTERN.match(path.name)
        if match:
            generations[match.group(1)] = path.stat().st_mtime
    ordered = sorted(generations, key=generations.get, reverse=True)
    for generation in ordered:
        if len(keep) >= 2:
            break
        keep.add(generation)
    removed = 0
    deferred = 0
    for generation in ordered:
        if generation in keep:
            continue
        for prefix in ("merged_live_data", "merged_analytics_cache"):
            old_file = publish_dir / f"{prefix}.{generation}.db"
            try:
                old_file.unlink(missing_ok=True)
                removed += 1
            except PermissionError:
                deferred += 1
    print(
        f"Snapshot cleanup: removed_files={removed}, deferred_locked_files={deferred}",
        flush=True,
    )


def main() -> int:
    args = parse_args()
    current = args.current.resolve()
    audience = args.audience.resolve()
    publish_dir = args.publish_dir.resolve()
    if not current.is_file():
        raise FileNotFoundError(f"Current database not found: {current}")
    if not audience.is_file():
        raise FileNotFoundError(f"Audience database not found: {audience}")
    publish_dir.mkdir(parents=True, exist_ok=True)

    manifest = publish_dir / MANIFEST_NAME
    previous = read_current_manifest(manifest)
    preserve_from = (
        publish_dir / previous["database"]
        if previous
        else publish_dir / "merged_live_data.db"
    )
    generation = datetime.now().strftime("%Y%m%dT%H%M%S%f")
    live_name = f"merged_live_data.{generation}.db"
    cache_name = f"merged_analytics_cache.{generation}.db"
    live_path = publish_dir / live_name
    cache_path = publish_dir / cache_name
    scripts = Path(__file__).resolve().parent

    commands = [
        [
            sys.executable,
            str(scripts / "prepare_current_database.py"),
            "--current",
            str(current),
            "--audience",
            str(audience),
            "--output",
            str(live_path),
            "--preserve-from",
            str(preserve_from),
        ],
        [
            sys.executable,
            str(scripts / "build_analytics_cache.py"),
            "--source",
            str(live_path),
            "--output",
            str(cache_path),
        ],
    ]
    for command in commands:
        subprocess.run(command, cwd=ROOT, check=True)

    active = {
        "generation": generation,
        "database": live_name,
        "analytics_cache": cache_name,
        "published_at": datetime.now().astimezone().isoformat(timespec="seconds"),
    }
    temporary_manifest = publish_dir / f"{MANIFEST_NAME}.{uuid.uuid4().hex}.tmp"
    temporary_manifest.write_text(
        json.dumps(active, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    replace_manifest(temporary_manifest, manifest)
    print(f"Active API snapshot: {live_path}", flush=True)
    print(f"Active analytics cache: {cache_path}", flush=True)

    keep = {generation}
    if previous:
        keep.add(previous["generation"])
    cleanup_old_generations(publish_dir, keep)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
