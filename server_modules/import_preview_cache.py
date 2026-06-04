"""Import preview cache helpers.

Preview cache entries remain owned by server.py for backward-compatible tests
and route code, while cleanup and payload persistence live here.
"""

from __future__ import annotations

import json
import shutil
import time
import uuid
from pathlib import Path
from typing import Callable


def preview_id() -> str:
    return f"import_preview_{uuid.uuid4().hex}"


def cleanup_preview_temp(entries: dict[str, dict], preview_id_value: str) -> None:
    entry = entries.get(preview_id_value)
    if not entry:
        return
    tmp_dir = entry.get("_tmp_dir")
    if tmp_dir and Path(tmp_dir).is_dir():
        shutil.rmtree(tmp_dir, ignore_errors=True)


def cleanup_expired_previews(
    entries: dict[str, dict],
    *,
    ttl_seconds: int,
    max_entries: int,
    max_cached_bytes: int,
) -> None:
    cutoff = time.time() - ttl_seconds
    expired = [key for key, value in entries.items() if value.get("_ts", 0) < cutoff]
    for key in expired:
        cleanup_preview_temp(entries, key)
        del entries[key]

    total_bytes = sum(int(value.get("_cache_bytes") or 0) for value in entries.values())
    if len(entries) <= max_entries and total_bytes <= max_cached_bytes:
        return

    ordered = sorted(entries.items(), key=lambda item: float(item[1].get("_ts") or 0))
    while ordered and (
        len(entries) > max_entries
        or sum(int(value.get("_cache_bytes") or 0) for value in entries.values()) > max_cached_bytes
    ):
        preview_id_to_remove, _ = ordered.pop(0)
        if preview_id_to_remove in entries:
            cleanup_preview_temp(entries, preview_id_to_remove)
            del entries[preview_id_to_remove]


def store_payload(tmp_path: Path, incoming: dict, result: dict, json_dumps: Callable[..., str]) -> Path:
    payload_path = tmp_path / "preview_payload.json"
    payload_path.write_text(
        json_dumps({"incoming": incoming, "result": result}),
        encoding="utf-8",
    )
    return payload_path


def load_payload(entry: dict) -> tuple[dict, dict]:
    if not entry:
        return {}, {}
    payload_path = entry.get("_payload_path")
    if payload_path and Path(payload_path).is_file():
        payload = json.loads(Path(payload_path).read_text(encoding="utf-8"))
        return payload.get("incoming") or {}, payload.get("result") or {}
    return entry.get("_incoming") or {}, entry.get("result") or {}
