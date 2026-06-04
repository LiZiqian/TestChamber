"""Backup throttling and pruning for TestChamber runtime data."""

from __future__ import annotations

import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Callable


BACKUP_INTERVAL_SECONDS = 300
BACKUP_REVISION_GAP = 50
BACKUP_MIN_INTERVAL_SECONDS = 60
IMPORTANT_BACKUP_MIN_INTERVAL_SECONDS = 1
BACKUPS_PER_HOUR_KEEP = 5
MAX_BACKUPS_KEEP = 10
BACKUP_FILE_PATTERN = re.compile(r"testchamber_v7_rev\d+_(\d{8})_(\d{6})\.json")

_last_backup_time: float = 0.0
_last_backup_revision: int = 0


def should_backup(revision: int, *, is_important: bool = False) -> bool:
    now_ts = time.time()
    if is_important:
        return (now_ts - _last_backup_time) >= IMPORTANT_BACKUP_MIN_INTERVAL_SECONDS
    if (now_ts - _last_backup_time) >= BACKUP_INTERVAL_SECONDS:
        return True
    if (revision - _last_backup_revision) >= BACKUP_REVISION_GAP and (now_ts - _last_backup_time) >= BACKUP_MIN_INTERVAL_SECONDS:
        return True
    return False


def resolve_sort_ts(path: Path) -> float:
    match = BACKUP_FILE_PATTERN.match(path.name)
    if match:
        try:
            dt = datetime.strptime(f"{match.group(1)}{match.group(2)}", "%Y%m%d%H%M%S")
            return dt.timestamp()
        except ValueError:
            pass
    return path.stat().st_mtime


def prune_backups(backup_dir: Path) -> None:
    entries: list[tuple[str, float, Path]] = []
    for path in backup_dir.glob("testchamber_v7_rev*.json"):
        sort_ts = resolve_sort_ts(path)
        match = BACKUP_FILE_PATTERN.match(path.name)
        if match:
            hour_bucket = f"{match.group(1)}_{match.group(2)[:2]}"
        else:
            try:
                hour_bucket = datetime.fromtimestamp(sort_ts).strftime("%Y%m%d_%H")
            except Exception:
                hour_bucket = "unknown"
        entries.append((hour_bucket, sort_ts, path))

    by_hour: dict[str, list[tuple[float, Path]]] = defaultdict(list)
    for hour_bucket, sort_ts, path in entries:
        by_hour[hour_bucket].append((sort_ts, path))

    for items in by_hour.values():
        items.sort(key=lambda item: item[0], reverse=True)
        for _, path in items[BACKUPS_PER_HOUR_KEEP:]:
            try:
                path.unlink()
            except Exception as exc:
                print(f"[WARN] 删除旧备份 {path.name} 失败：{exc}")

    remaining = sorted(
        backup_dir.glob("testchamber_v7_rev*.json"),
        key=resolve_sort_ts,
        reverse=True,
    )
    for old in remaining[MAX_BACKUPS_KEEP:]:
        try:
            old.unlink()
        except Exception as exc:
            print(f"[WARN] 删除旧备份 {old.name} 失败：{exc}")


def write_backup(backup_dir: Path, data: dict, revision: int, json_dumps: Callable[..., str]) -> Path:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    backup_dir.mkdir(parents=True, exist_ok=True)
    path = backup_dir / f"testchamber_v7_rev{revision}_{ts}.json"
    path.write_text(json_dumps(data, pretty=True), encoding="utf-8")

    global _last_backup_time, _last_backup_revision
    _last_backup_time = time.time()
    _last_backup_revision = revision
    try:
        prune_backups(backup_dir)
    except Exception as exc:
        print(f"[WARN] 清理旧备份失败：{exc}")
    return path
