#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数字治理平台 V6.1 内网协同版服务器

V6.1 的核心变化：
- 网页代码仍保存在项目根目录、js、css、templates 中。
- 业务数据统一放在 data/ 下。
- 样机库从大 JSON 中外置到 SQLite 表。
- 样机照片等大文件保存到 data/samples/<sampleId>/，SQLite 只保存索引。
"""

from __future__ import annotations

import argparse
import base64
import copy
import hashlib
import json
import mimetypes
import re
import sqlite3
import threading
import time
import uuid
from collections import defaultdict
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, unquote_to_bytes, urlparse


APP_VERSION = "6.1-intranet"
SERVER_VERSION = "TestChamberServer/6.1"
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
SAMPLE_DATA_DIR = DATA_DIR / "samples"
BACKUP_DIR = ROOT_DIR / "backups"
DB_PATH = DATA_DIR / "testchamber.sqlite"
INDEX_PATH = ROOT_DIR / "index.html"
MAX_UPLOAD_BYTES = 80 * 1024 * 1024

DB_LOCK = threading.Lock()


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def empty_data() -> dict:
    return {
        "version": APP_VERSION,
        "currentProjectId": None,
        "currentStageId": None,
        "users": [],
        "projects": [],
        "sampleLibrary": {"categories": [], "logs": []},
        "testCaseMaster": [],
    }


def ensure_dirs() -> None:
    DATA_DIR.mkdir(exist_ok=True)
    SAMPLE_DATA_DIR.mkdir(parents=True, exist_ok=True)
    BACKUP_DIR.mkdir(exist_ok=True)


def connect_db() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH, timeout=30, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA busy_timeout = 30000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn


def json_dumps(obj: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def stable_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_obj(text: str | None, fallback: object | None = None):
    try:
        return json.loads(text or "")
    except Exception:
        return copy.deepcopy(fallback)


def safe_segment(value: object, fallback: str = "item") -> str:
    text = str(value or "").strip()
    text = re.sub(r"[^A-Za-z0-9_.-]+", "_", text)
    text = text.strip("._-")
    return (text or fallback)[:96]


def url_for_asset(sample_id: str, asset_id: str) -> str:
    return f"/api/samples/{quote(str(sample_id), safe='')}/photos/{quote(str(asset_id), safe='')}"


def file_ext(original_name: str, mime_type: str) -> str:
    suffix = Path(original_name or "").suffix.lower()
    if suffix and re.fullmatch(r"\.[a-z0-9]{1,8}", suffix):
        return suffix
    guessed = mimetypes.guess_extension(mime_type or "") or ".bin"
    if guessed == ".jpe":
        guessed = ".jpg"
    return guessed


def path_inside_data(relative_path: str) -> Path:
    target = (DATA_DIR / relative_path).resolve()
    if DATA_DIR.resolve() not in target.parents and target != DATA_DIR.resolve():
        raise ValueError("非法文件路径")
    return target


def iter_samples(data: dict):
    for category in data.get("sampleLibrary", {}).get("categories", []) or []:
        for sample in category.get("samples", []) or []:
            yield category, sample


def find_sample(data: dict, sample_id: str) -> tuple[dict | None, dict | None]:
    for category, sample in iter_samples(data):
        if str(sample.get("id")) == str(sample_id):
            return category, sample
    return None, None


def split_state_for_storage(data: dict) -> dict:
    stored = copy.deepcopy(data)
    stored["version"] = APP_VERSION
    stored.pop("peoplePool", None)
    stored.pop("locationPool", None)
    stored["projects"] = []
    stored["projectsExternalized"] = {
        "schema": "project_tables_v1",
        "note": "Projects, stages, tasks and task logs are stored in normalized SQLite tables.",
    }
    stored["sampleLibrary"] = {
        "externalized": True,
        "schema": "sample_tables_v1",
        "note": "样机库数据已外置到 sample_categories / sample_records / sample_assets 表。",
    }
    return stored


# ── Backup 节流策略常量 ────────────────────────────────────────────────
# 普通保存（save_state）backup 条件：
#   (a) 距离上次 backup 超过 BACKUP_INTERVAL_SECONDS 秒（5 分钟）；或
#   (b) revision 距离上次 backup 超过 BACKUP_REVISION_GAP 次（50 次），
#       且距离上次 backup 至少超过 BACKUP_MIN_INTERVAL_SECONDS 秒（60 秒）。
# 重要操作（commit_data_mutation 且 action ∈ IMPORTANT_ACTIONS）：
#   距离上次 backup 超过 IMPORTANT_BACKUP_MIN_INTERVAL_SECONDS 秒即可。

BACKUP_INTERVAL_SECONDS = 300          # 普通保存最小时间间隔（秒）
BACKUP_REVISION_GAP = 50               # 普通保存最小 revision 间隔
BACKUP_MIN_INTERVAL_SECONDS = 60       # revision 间隔分支的最低时间门槛（秒）
IMPORTANT_BACKUP_MIN_INTERVAL_SECONDS = 1   # 重要操作的最低时间门槛（秒）

# 仅在有明确后端 action 的 commit_data_mutation 中生效
IMPORTANT_ACTIONS = {
    "upload_sample_photos",
    "delete_sample_photo",
}

# ── Backup 清理策略常量 ────────────────────────────────────────────────
BACKUPS_PER_HOUR_KEEP = 5   # 每小时最多保留的 backup 数量
MAX_BACKUPS_KEEP = 10       # 全局最多保留的 backup 数量

# ── Backup 节流状态（模块级）────────────────────────────────────────────
_last_backup_time: float = 0.0       # 上次成功写入 backup 的时间戳（time.time()）
_last_backup_revision: int = 0       # 上次成功写入 backup 时的 revision

# 文件名解析正则：testchamber_v61_rev{revision}_{YYYYMMDD}_{HHMMSS}.json
_BACKUP_FILE_PATTERN = re.compile(r"testchamber_v61_rev\d+_(\d{8})_(\d{6})\.json")


def _should_backup(action: str, revision: int, *, is_important: bool = False) -> bool:
    """判断是否应该生成一份 backup JSON 快照。"""
    now_ts = time.time()
    if is_important:
        return (now_ts - _last_backup_time) >= IMPORTANT_BACKUP_MIN_INTERVAL_SECONDS
    # 普通保存：时间间隔 ≥ 5 分钟
    if (now_ts - _last_backup_time) >= BACKUP_INTERVAL_SECONDS:
        return True
    # 普通保存：revision 间隔 ≥ 50 且距离上次 backup ≥ 60 秒
    if (revision - _last_backup_revision) >= BACKUP_REVISION_GAP and (now_ts - _last_backup_time) >= BACKUP_MIN_INTERVAL_SECONDS:
        return True
    return False


def write_backup(data: dict, revision: int) -> None:
    ts = datetime.now().strftime("%Y%m%d_%H%M%S")
    path = BACKUP_DIR / f"testchamber_v61_rev{revision}_{ts}.json"
    path.write_text(json_dumps(data, pretty=True), encoding="utf-8")
    # 写入成功后才更新节流状态
    global _last_backup_time, _last_backup_revision
    _last_backup_time = time.time()
    _last_backup_revision = revision
    try:
        prune_backups()
    except Exception as e:
        print(f"[WARN] 清理旧备份失败：{e}")


def _resolve_sort_ts(path: Path) -> float:
    """从文件名解析排序时间戳。解析成功返回 UTC timestamp，失败返回 mtime。"""
    m = _BACKUP_FILE_PATTERN.match(path.name)
    if m:
        try:
            dt = datetime.strptime(f"{m.group(1)}{m.group(2)}", "%Y%m%d%H%M%S")
            return dt.timestamp()
        except ValueError:
            pass
    return path.stat().st_mtime


def prune_backups() -> None:
    """清理 testchamber_v61_rev*.json 备份。
    
    规则：
    1. 只处理文件名匹配 testchamber_v61_rev*.json 的文件。
       不删除 .gitkeep、非匹配文件、SQLite 数据库等。
    2. 按小时分组，优先从文件名解析时间，解析失败则 fallback 使用文件 mtime。
       同一小时内保留最新 BACKUPS_PER_HOUR_KEEP 个，删除其余。
    3. 再按全局数量限制，只保留最新 MAX_BACKUPS_KEEP 个。
    4. 删除失败只打印 warning，不影响服务运行。
    """
    # 收集所有匹配的 backup 文件，每条记录：(hour_bucket, sort_ts, path)
    entries: list[tuple[str, float, Path]] = []
    for p in BACKUP_DIR.glob("testchamber_v61_rev*.json"):
        sort_ts = _resolve_sort_ts(p)
        m = _BACKUP_FILE_PATTERN.match(p.name)
        if m:
            hour_bucket = f"{m.group(1)}_{m.group(2)[:2]}"  # YYYYMMDD_HH
        else:
            try:
                hour_bucket = datetime.fromtimestamp(sort_ts).strftime("%Y%m%d_%H")
            except Exception:
                hour_bucket = "unknown"
        entries.append((hour_bucket, sort_ts, p))

    # 第一步：按小时分组，每小时保留最新 BACKUPS_PER_HOUR_KEEP 个
    by_hour: dict[str, list[tuple[float, Path]]] = defaultdict(list)
    for hour_bucket, sort_ts, path in entries:
        by_hour[hour_bucket].append((sort_ts, path))

    for items in by_hour.values():
        items.sort(key=lambda x: x[0], reverse=True)
        for _, path in items[BACKUPS_PER_HOUR_KEEP:]:
            try:
                path.unlink()
            except Exception as e:
                print(f"[WARN] 删除旧备份 {path.name} 失败：{e}")

    # 第二步：全局数量限制，只保留最新 MAX_BACKUPS_KEEP 个
    remaining = sorted(
        BACKUP_DIR.glob("testchamber_v61_rev*.json"),
        key=_resolve_sort_ts,
        reverse=True,
    )
    for old in remaining[MAX_BACKUPS_KEEP:]:
        try:
            old.unlink()
        except Exception as e:
            print(f"[WARN] 删除旧备份 {old.name} 失败：{e}")


def ensure_schema(conn: sqlite3.Connection) -> None:
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS app_state (
            id INTEGER PRIMARY KEY CHECK (id = 1),
            data_json TEXT NOT NULL,
            revision INTEGER NOT NULL DEFAULT 1,
            updated_at TEXT NOT NULL
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS audit_log (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            time TEXT NOT NULL,
            user TEXT,
            action TEXT,
            remark TEXT,
            revision_before INTEGER,
            revision_after INTEGER,
            client_ip TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_categories (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            description TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_records (
            id TEXT PRIMARY KEY,
            category_id TEXT NOT NULL,
            sample_no TEXT,
            sn TEXT,
            imei TEXT,
            status TEXT,
            location TEXT,
            owner TEXT,
            borrower TEXT,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            FOREIGN KEY(category_id) REFERENCES sample_categories(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category ON sample_records(category_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_sn ON sample_records(sn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_imei ON sample_records(imei)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_status ON sample_records(status)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_assets (
            id TEXT PRIMARY KEY,
            sample_id TEXT NOT NULL,
            kind TEXT NOT NULL,
            original_name TEXT,
            file_name TEXT NOT NULL,
            relative_path TEXT NOT NULL,
            mime_type TEXT,
            size INTEGER NOT NULL DEFAULT 0,
            created_at TEXT NOT NULL,
            created_by TEXT,
            deleted_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_assets_sample ON sample_assets(sample_id, kind, deleted_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS sample_events (
            id TEXT PRIMARY KEY,
            sample_id TEXT,
            time TEXT,
            event_type TEXT,
            project_id TEXT,
            stage_id TEXT,
            task_id TEXT,
            test_item TEXT,
            user TEXT,
            data_json TEXT NOT NULL
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_events_sample ON sample_events(sample_id, time)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_records (
            id TEXT PRIMARY KEY,
            name TEXT NOT NULL,
            code TEXT,
            owner TEXT,
            sort_order INTEGER NOT NULL DEFAULT 0,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_records_active ON project_records(deleted_at, sort_order)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_stages (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            name TEXT NOT NULL,
            sort_order INTEGER NOT NULL DEFAULT 0,
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            deleted_at TEXT,
            FOREIGN KEY(project_id) REFERENCES project_records(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_stages_project ON project_stages(project_id, deleted_at, sort_order)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_tasks (
            id TEXT PRIMARY KEY,
            project_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            progress_id TEXT,
            category TEXT,
            test_item TEXT,
            sku_index INTEGER,
            status TEXT,
            owner TEXT,
            sample_ids_json TEXT NOT NULL DEFAULT '[]',
            data_json TEXT NOT NULL,
            created_at TEXT,
            updated_at TEXT NOT NULL,
            completed_at TEXT,
            deleted_at TEXT,
            FOREIGN KEY(project_id) REFERENCES project_records(id),
            FOREIGN KEY(stage_id) REFERENCES project_stages(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage ON project_tasks(stage_id, deleted_at, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_progress ON project_tasks(progress_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id, deleted_at)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS task_logs (
            id TEXT PRIMARY KEY,
            task_id TEXT NOT NULL,
            project_id TEXT,
            stage_id TEXT,
            time TEXT,
            action TEXT,
            user TEXT,
            data_json TEXT NOT NULL,
            FOREIGN KEY(task_id) REFERENCES project_tasks(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_task ON task_logs(task_id, time)")


def normalize_photo_meta(sample_id: str, photo: dict) -> dict:
    photo_id = str(photo.get("id") or f"photo_{uuid.uuid4().hex}")
    name = str(photo.get("name") or photo.get("originalName") or "外观照片")
    mime_type = str(photo.get("type") or photo.get("mimeType") or mimetypes.guess_type(name)[0] or "application/octet-stream")
    relative_path = str(photo.get("relativePath") or "")
    size = int(photo.get("size") or 0)
    uploaded_at = str(photo.get("uploadedAt") or photo.get("createdAt") or now_iso())
    return {
        "id": photo_id,
        "name": name,
        "type": mime_type,
        "size": size,
        "url": str(photo.get("url") or url_for_asset(sample_id, photo_id)),
        "relativePath": relative_path,
        "uploadedAt": uploaded_at,
    }


def store_asset_bytes(
    conn: sqlite3.Connection,
    sample_id: str,
    content: bytes,
    original_name: str,
    mime_type: str,
    *,
    photo_id: str | None = None,
    uploaded_at: str | None = None,
    uploaded_by: str = "",
) -> dict:
    asset_id = photo_id or f"photo_{uuid.uuid4().hex}"
    ext = file_ext(original_name, mime_type)
    file_name = f"{safe_segment(asset_id, 'photo')}{ext}"
    target_dir = SAMPLE_DATA_DIR / safe_segment(sample_id, "sample") / "photos"
    target_dir.mkdir(parents=True, exist_ok=True)
    target = target_dir / file_name
    target.write_bytes(content)
    relative_path = target.relative_to(DATA_DIR).as_posix()
    created_at = uploaded_at or now_iso()
    meta = {
        "id": asset_id,
        "name": original_name or file_name,
        "type": mime_type or mimetypes.guess_type(file_name)[0] or "application/octet-stream",
        "size": len(content),
        "url": url_for_asset(sample_id, asset_id),
        "relativePath": relative_path,
        "uploadedAt": created_at,
    }
    conn.execute(
        """
        INSERT INTO sample_assets
        (id, sample_id, kind, original_name, file_name, relative_path, mime_type, size, created_at, created_by, deleted_at)
        VALUES (?, ?, 'photo', ?, ?, ?, ?, ?, ?, ?, NULL)
        ON CONFLICT(id) DO UPDATE SET
            sample_id = excluded.sample_id,
            kind = excluded.kind,
            original_name = excluded.original_name,
            file_name = excluded.file_name,
            relative_path = excluded.relative_path,
            mime_type = excluded.mime_type,
            size = excluded.size,
            created_at = excluded.created_at,
            created_by = excluded.created_by,
            deleted_at = NULL
        """,
        (
            asset_id,
            sample_id,
            meta["name"],
            file_name,
            relative_path,
            meta["type"],
            meta["size"],
            created_at,
            uploaded_by,
        ),
    )
    return meta


def materialize_data_url_photo(conn: sqlite3.Connection, sample_id: str, photo: dict) -> dict | None:
    data_url = str(photo.get("dataUrl") or "")
    match = re.match(r"^data:([^;,]+)?(;base64)?,(.*)$", data_url, flags=re.S)
    if not match:
        return None
    mime_type = match.group(1) or photo.get("type") or "application/octet-stream"
    is_base64 = bool(match.group(2))
    payload = match.group(3) or ""
    try:
        content = base64.b64decode(payload, validate=False) if is_base64 else unquote_to_bytes(payload)
    except Exception:
        return None
    return store_asset_bytes(
        conn,
        sample_id,
        content,
        str(photo.get("name") or "外观照片"),
        str(mime_type),
        photo_id=str(photo.get("id") or f"photo_{uuid.uuid4().hex}"),
        uploaded_at=str(photo.get("uploadedAt") or now_iso()),
    )


def upsert_existing_photo_asset(conn: sqlite3.Connection, sample_id: str, photo: dict) -> dict:
    meta = normalize_photo_meta(sample_id, photo)
    relative_path = meta.get("relativePath") or ""
    file_name = Path(relative_path).name if relative_path else safe_segment(meta["id"], "photo")
    conn.execute(
        """
        INSERT INTO sample_assets
        (id, sample_id, kind, original_name, file_name, relative_path, mime_type, size, created_at, created_by, deleted_at)
        VALUES (?, ?, 'photo', ?, ?, ?, ?, ?, ?, '', NULL)
        ON CONFLICT(id) DO UPDATE SET
            sample_id = excluded.sample_id,
            kind = excluded.kind,
            original_name = excluded.original_name,
            file_name = excluded.file_name,
            relative_path = excluded.relative_path,
            mime_type = excluded.mime_type,
            size = excluded.size,
            created_at = excluded.created_at,
            deleted_at = NULL
        """,
        (
            meta["id"],
            sample_id,
            meta["name"],
            file_name,
            relative_path,
            meta["type"],
            meta["size"],
            meta["uploadedAt"],
        ),
    )
    return meta


def normalize_sample_photos(conn: sqlite3.Connection, sample: dict) -> list[dict]:
    sample_id = str(sample.get("id") or f"sample_{uuid.uuid4().hex}")
    sample["id"] = sample_id
    normalized: list[dict] = []
    for raw_photo in sample.get("photos", []) or []:
        if not isinstance(raw_photo, dict):
            continue
        if raw_photo.get("dataUrl"):
            meta = materialize_data_url_photo(conn, sample_id, raw_photo)
            if meta:
                normalized.append(meta)
            continue
        if raw_photo.get("url") or raw_photo.get("relativePath"):
            normalized.append(upsert_existing_photo_asset(conn, sample_id, raw_photo))
    return normalized


def remove_empty_dirs_up_to(path: Path, stop_dir: Path) -> None:
    stop_dir = stop_dir.resolve()
    cur = path.resolve()
    while cur != stop_dir and stop_dir in cur.parents:
        try:
            cur.rmdir()
        except OSError:
            break
        cur = cur.parent


def cleanup_sample_asset_files(conn: sqlite3.Connection, sample_ids: list[str]) -> None:
    if not sample_ids:
        return
    placeholders = ",".join("?" for _ in sample_ids)
    rows = conn.execute(
        f"SELECT relative_path FROM sample_assets WHERE sample_id IN ({placeholders})",
        sample_ids,
    ).fetchall()
    for row in rows:
        try:
            target = path_inside_data(row["relative_path"])
            if target.is_file():
                target.unlink()
                remove_empty_dirs_up_to(target.parent, SAMPLE_DATA_DIR)
        except Exception as e:
            print(f"[WARN] Failed to remove sample asset file: {e}")


def sync_sample_library(conn: sqlite3.Connection, data: dict, *, allow_empty: bool = False) -> bool:
    library = data.get("sampleLibrary") or {}
    categories = library.get("categories") or []
    if library.get("externalized") and not categories and not allow_empty:
        return False

    ts = now_iso()
    active_category_ids: list[str] = []
    active_sample_ids: list[str] = []
    logs = list(library.get("logs") or [])

    for sort_order, category in enumerate(categories):
        if not isinstance(category, dict):
            continue
        cat_id = str(category.get("id") or f"cat_{uuid.uuid4().hex}")
        category["id"] = cat_id
        active_category_ids.append(cat_id)
        cat_json = copy.deepcopy(category)
        cat_json.pop("samples", None)
        conn.execute(
            """
            INSERT INTO sample_categories
            (id, name, description, sort_order, data_json, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                description = excluded.description,
                sort_order = excluded.sort_order,
                data_json = excluded.data_json,
                updated_at = excluded.updated_at,
                deleted_at = NULL
            """,
            (
                cat_id,
                str(category.get("name") or "未命名样机池"),
                str(category.get("description") or ""),
                sort_order,
                json_dumps(cat_json),
                str(category.get("createdAt") or ts),
                str(category.get("updatedAt") or ts),
            ),
        )

        for sample in category.get("samples", []) or []:
            if not isinstance(sample, dict):
                continue
            sample_id = str(sample.get("id") or f"sample_{uuid.uuid4().hex}")
            sample["id"] = sample_id
            sample["categoryId"] = cat_id
            sample["photos"] = normalize_sample_photos(conn, sample)
            active_sample_ids.append(sample_id)
            sample_json = copy.deepcopy(sample)
            sample_json.pop("photos", None)
            conn.execute(
                """
                INSERT INTO sample_records
                (id, category_id, sample_no, sn, imei, status, location, owner, borrower, data_json, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    category_id = excluded.category_id,
                    sample_no = excluded.sample_no,
                    sn = excluded.sn,
                    imei = excluded.imei,
                    status = excluded.status,
                    location = excluded.location,
                    owner = excluded.owner,
                    borrower = excluded.borrower,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at,
                    deleted_at = NULL
                """,
                (
                    sample_id,
                    cat_id,
                    str(sample.get("sampleNo") or ""),
                    str(sample.get("sn") or ""),
                    str(sample.get("imei") or ""),
                    str(sample.get("status") or ""),
                    str(sample.get("location") or ""),
                    str(sample.get("owner") or ""),
                    str(sample.get("borrower") or ""),
                    json_dumps(sample_json),
                    str(sample.get("createdAt") or ts),
                    str(sample.get("updatedAt") or ts),
                ),
            )
            for sample_log in sample.get("logs", []) or []:
                if isinstance(sample_log, dict):
                    logs.append(sample_log)

    if active_sample_ids:
        placeholders = ",".join("?" for _ in active_sample_ids)
        removed_rows = conn.execute(
            f"""
            SELECT id FROM sample_records WHERE id NOT IN ({placeholders})
            UNION
            SELECT sample_id AS id FROM sample_assets WHERE sample_id NOT IN ({placeholders})
            """,
            [*active_sample_ids, *active_sample_ids],
        ).fetchall()
        removed_sample_ids = [str(row["id"]) for row in removed_rows if row["id"]]
        cleanup_sample_asset_files(conn, removed_sample_ids)
        conn.execute(f"DELETE FROM sample_assets WHERE sample_id NOT IN ({placeholders})", active_sample_ids)
        conn.execute(f"DELETE FROM sample_events WHERE sample_id NOT IN ({placeholders})", active_sample_ids)
        conn.execute(f"DELETE FROM sample_records WHERE id NOT IN ({placeholders})", active_sample_ids)
    else:
        removed_rows = conn.execute(
            """
            SELECT id FROM sample_records
            UNION
            SELECT sample_id AS id FROM sample_assets
            """
        ).fetchall()
        removed_sample_ids = [str(row["id"]) for row in removed_rows if row["id"]]
        cleanup_sample_asset_files(conn, removed_sample_ids)
        conn.execute("DELETE FROM sample_assets")
        conn.execute("DELETE FROM sample_events")
        conn.execute("DELETE FROM sample_records")

    if active_category_ids:
        placeholders = ",".join("?" for _ in active_category_ids)
        conn.execute(f"DELETE FROM sample_categories WHERE id NOT IN ({placeholders})", active_category_ids)
    else:
        conn.execute("DELETE FROM sample_categories")

    conn.execute("DELETE FROM sample_events")
    seen_events = set()
    for log in logs:
        if not isinstance(log, dict):
            continue
        event_id = str(log.get("id") or f"event_{uuid.uuid4().hex}")
        if event_id in seen_events:
            continue
        seen_events.add(event_id)
        conn.execute(
            """
            INSERT INTO sample_events
            (id, sample_id, time, event_type, project_id, stage_id, task_id, test_item, user, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                str(log.get("sampleId") or ""),
                str(log.get("time") or ""),
                str(log.get("source") or log.get("eventType") or "sample_log"),
                str(log.get("projectId") or ""),
                str(log.get("stageId") or ""),
                str(log.get("taskId") or ""),
                str(log.get("testItem") or ""),
                str(log.get("user") or ""),
                json_dumps(log),
            ),
        )

    return True


def load_sample_photos(conn: sqlite3.Connection, sample_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT id, original_name, file_name, mime_type, size, relative_path, created_at
        FROM sample_assets
        WHERE sample_id = ? AND kind = 'photo' AND deleted_at IS NULL
        ORDER BY created_at, id
        """,
        (sample_id,),
    ).fetchall()
    return [
        {
            "id": row["id"],
            "name": row["original_name"] or row["file_name"] or "外观照片",
            "type": row["mime_type"] or "application/octet-stream",
            "size": int(row["size"] or 0),
            "url": url_for_asset(sample_id, row["id"]),
            "relativePath": row["relative_path"],
            "uploadedAt": row["created_at"],
        }
        for row in rows
    ]


def load_sample_library(conn: sqlite3.Connection) -> dict:
    category_rows = conn.execute(
        """
        SELECT id, name, description, data_json
        FROM sample_categories
        WHERE deleted_at IS NULL
        ORDER BY sort_order, id
        """
    ).fetchall()
    categories: list[dict] = []
    category_map: dict[str, dict] = {}
    for row in category_rows:
        try:
            cat = json.loads(row["data_json"] or "{}")
        except Exception:
            cat = {}
        cat.update({
            "id": row["id"],
            "name": row["name"],
            "description": row["description"] or "",
            "samples": [],
        })
        categories.append(cat)
        category_map[row["id"]] = cat

    sample_rows = conn.execute(
        """
        SELECT id, category_id, sample_no, sn, imei, status, location, owner, borrower, data_json
        FROM sample_records
        WHERE deleted_at IS NULL
        ORDER BY created_at, id
        """
    ).fetchall()
    for row in sample_rows:
        try:
            sample = json.loads(row["data_json"] or "{}")
        except Exception:
            sample = {}
        sample.update({
            "id": row["id"],
            "categoryId": row["category_id"],
            "sampleNo": row["sample_no"] or sample.get("sampleNo") or "",
            "sn": row["sn"] or sample.get("sn") or "",
            "imei": row["imei"] or sample.get("imei") or "",
            "status": row["status"] or sample.get("status") or "",
            "location": row["location"] or sample.get("location") or "",
            "owner": row["owner"] or sample.get("owner") or "",
            "borrower": row["borrower"] or sample.get("borrower") or "",
            "photos": load_sample_photos(conn, row["id"]),
        })
        category_map.get(row["category_id"], {}).setdefault("samples", []).append(sample)

    event_rows = conn.execute("SELECT data_json FROM sample_events ORDER BY time, id").fetchall()
    logs = []
    for row in event_rows:
        try:
            logs.append(json.loads(row["data_json"]))
        except Exception:
            pass
    return {"categories": categories, "logs": logs}


def list_item_key(item: object, index: int) -> str:
    if isinstance(item, dict) and item.get("id"):
        return str(item.get("id"))
    digest = hashlib.sha1(stable_json(item).encode("utf-8")).hexdigest()
    return f"__hash_{digest}_{index}"


def normalize_json_list(value: object) -> list:
    return value if isinstance(value, list) else []


def to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def merge_record(base: dict, new: dict, current: dict, child_specs: dict[str, dict] | None = None) -> dict:
    child_specs = child_specs or {}
    merged = copy.deepcopy(current if isinstance(current, dict) else {})
    base = base if isinstance(base, dict) else {}
    new = new if isinstance(new, dict) else {}

    for key in set(base.keys()) | set(new.keys()) | set(merged.keys()):
        if key in child_specs:
            continue
        base_val = base.get(key)
        new_has_key = key in new
        new_val = new.get(key)
        if new_has_key and stable_json(new_val) != stable_json(base_val):
            merged[key] = copy.deepcopy(new_val)

    for key, spec in child_specs.items():
        merged[key] = merge_list_by_id(
            normalize_json_list(base.get(key)),
            normalize_json_list(new.get(key)),
            normalize_json_list((current or {}).get(key) if isinstance(current, dict) else []),
            spec,
        )
    return merged


def merge_list_by_id(base_list: list, new_list: list, current_list: list, child_specs: dict[str, dict] | None = None) -> list:
    child_specs = child_specs or {}
    base_map = {list_item_key(item, idx): item for idx, item in enumerate(base_list)}
    new_map = {list_item_key(item, idx): item for idx, item in enumerate(new_list)}
    current_map = {list_item_key(item, idx): item for idx, item in enumerate(current_list)}
    merged_map: dict[str, object] = {key: copy.deepcopy(value) for key, value in current_map.items()}

    for idx, item in enumerate(new_list):
        key = list_item_key(item, idx)
        base_item = base_map.get(key)
        current_item = current_map.get(key)
        if base_item is None:
            if isinstance(item, dict) and isinstance(current_item, dict):
                merged_map[key] = merge_record({}, item, current_item, child_specs)
            elif key not in current_map:
                merged_map[key] = copy.deepcopy(item)
            continue
        if current_item is None:
            if stable_json(item) != stable_json(base_item):
                merged_map[key] = copy.deepcopy(item)
            continue
        if isinstance(item, dict) and isinstance(base_item, dict) and isinstance(current_item, dict):
            merged_map[key] = merge_record(base_item, item, current_item, child_specs)
        elif stable_json(item) != stable_json(base_item):
            merged_map[key] = copy.deepcopy(item)

    for idx, item in enumerate(base_list):
        key = list_item_key(item, idx)
        if key in new_map or key not in merged_map:
            continue
        current_item = current_map.get(key)
        if stable_json(current_item) == stable_json(item):
            merged_map.pop(key, None)

    ordered_keys: list[str] = []
    for idx, item in enumerate(new_list):
        key = list_item_key(item, idx)
        if key in merged_map and key not in ordered_keys:
            ordered_keys.append(key)
    for idx, item in enumerate(current_list):
        key = list_item_key(item, idx)
        if key in merged_map and key not in ordered_keys:
            ordered_keys.append(key)
    return [merged_map[key] for key in ordered_keys]


PROJECT_CHILDREN = {
    "stages": {
        "tasks": {
            "logs": {},
        },
    },
}


SAMPLE_CATEGORY_CHILDREN = {
    "samples": {
        "logs": {},
        "photos": {},
        "initialResults": {},
    },
}


def merge_sample_library(base_library: dict, new_library: dict, current_library: dict) -> dict:
    base_library = base_library if isinstance(base_library, dict) else {}
    new_library = new_library if isinstance(new_library, dict) else {}
    current_library = current_library if isinstance(current_library, dict) else {}
    merged = copy.deepcopy(current_library)
    merged["categories"] = merge_list_by_id(
        normalize_json_list(base_library.get("categories")),
        normalize_json_list(new_library.get("categories")),
        normalize_json_list(current_library.get("categories")),
        SAMPLE_CATEGORY_CHILDREN,
    )
    merged["logs"] = merge_list_by_id(
        normalize_json_list(base_library.get("logs")),
        normalize_json_list(new_library.get("logs")),
        normalize_json_list(current_library.get("logs")),
        {},
    )
    return merged


def merge_state(base_data: dict, new_data: dict, current_data: dict) -> dict:
    base_data = base_data if isinstance(base_data, dict) else empty_data()
    current_data = current_data if isinstance(current_data, dict) else empty_data()
    merged = copy.deepcopy(current_data)
    merged.pop("peoplePool", None)
    merged.pop("locationPool", None)
    for key in set(base_data.keys()) | set(new_data.keys()) | set(current_data.keys()):
        if key in ("projects", "sampleLibrary", "version", "peoplePool", "locationPool"):
            continue
        if stable_json(new_data.get(key)) != stable_json(base_data.get(key)):
            merged[key] = copy.deepcopy(new_data.get(key))

    merged["projects"] = merge_list_by_id(
        normalize_json_list(base_data.get("projects")),
        normalize_json_list(new_data.get("projects")),
        normalize_json_list(current_data.get("projects")),
        PROJECT_CHILDREN,
    )
    merged["sampleLibrary"] = merge_sample_library(
        base_data.get("sampleLibrary") or {},
        new_data.get("sampleLibrary") or {},
        current_data.get("sampleLibrary") or {},
    )
    merged["version"] = APP_VERSION
    return merged


def sync_project_library(conn: sqlite3.Connection, data: dict, *, allow_empty: bool = False) -> bool:
    projects = data.get("projects") or []
    if data.get("projectsExternalized") and not projects and not allow_empty:
        return False

    ts = now_iso()
    active_project_ids: list[str] = []
    active_stage_ids: list[str] = []
    active_task_ids: list[str] = []

    for project_order, project in enumerate(projects):
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("id") or f"project_{uuid.uuid4().hex}")
        project["id"] = project_id
        active_project_ids.append(project_id)
        project_json = copy.deepcopy(project)
        project_json.pop("stages", None)
        conn.execute(
            """
            INSERT INTO project_records
            (id, name, code, owner, sort_order, data_json, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            ON CONFLICT(id) DO UPDATE SET
                name = excluded.name,
                code = excluded.code,
                owner = excluded.owner,
                sort_order = excluded.sort_order,
                data_json = excluded.data_json,
                updated_at = excluded.updated_at,
                deleted_at = NULL
            """,
            (
                project_id,
                str(project.get("name") or "Untitled Project"),
                str(project.get("code") or ""),
                str(project.get("owner") or project.get("leader") or project.get("manager") or ""),
                project_order,
                json_dumps(project_json),
                str(project.get("createdAt") or ts),
                str(project.get("updatedAt") or ts),
            ),
        )

        for stage_order, stage in enumerate(project.get("stages", []) or []):
            if not isinstance(stage, dict):
                continue
            stage_id = str(stage.get("id") or f"stage_{uuid.uuid4().hex}")
            stage["id"] = stage_id
            stage["projectId"] = project_id
            active_stage_ids.append(stage_id)
            stage_json = copy.deepcopy(stage)
            stage_json.pop("tasks", None)
            conn.execute(
                """
                INSERT INTO project_stages
                (id, project_id, name, sort_order, data_json, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    project_id = excluded.project_id,
                    name = excluded.name,
                    sort_order = excluded.sort_order,
                    data_json = excluded.data_json,
                    updated_at = excluded.updated_at,
                    deleted_at = NULL
                """,
                (
                    stage_id,
                    project_id,
                    str(stage.get("name") or "Untitled Stage"),
                    stage_order,
                    json_dumps(stage_json),
                    str(stage.get("createdAt") or ts),
                    str(stage.get("updatedAt") or ts),
                ),
            )

            for task in stage.get("tasks", []) or []:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("id") or f"task_{uuid.uuid4().hex}")
                task["id"] = task_id
                task["projectId"] = project_id
                task["stageId"] = stage_id
                active_task_ids.append(task_id)
                sample_ids = [str(x) for x in (task.get("sampleIds") or [])]
                task_json = copy.deepcopy(task)
                task_logs = task_json.pop("logs", []) if isinstance(task_json.get("logs"), list) else []
                conn.execute(
                    """
                    INSERT INTO project_tasks
                    (id, project_id, stage_id, progress_id, category, test_item, sku_index, status, owner,
                     sample_ids_json, data_json, created_at, updated_at, completed_at, deleted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(id) DO UPDATE SET
                        project_id = excluded.project_id,
                        stage_id = excluded.stage_id,
                        progress_id = excluded.progress_id,
                        category = excluded.category,
                        test_item = excluded.test_item,
                        sku_index = excluded.sku_index,
                        status = excluded.status,
                        owner = excluded.owner,
                        sample_ids_json = excluded.sample_ids_json,
                        data_json = excluded.data_json,
                        updated_at = excluded.updated_at,
                        completed_at = excluded.completed_at,
                        deleted_at = NULL
                    """,
                    (
                        task_id,
                        project_id,
                        stage_id,
                        str(task.get("progressId") or ""),
                        str(task.get("category") or ""),
                        str(task.get("testItem") or ""),
                        to_int(task.get("skuIndex")),
                        str(task.get("status") or ""),
                        str(task.get("owner") or ""),
                        json_dumps(sample_ids),
                        json_dumps(task_json),
                        str(task.get("createdAt") or ts),
                        str(task.get("updatedAt") or ts),
                        str(task.get("completedAt") or task.get("endDate") or ""),
                    ),
                )
                conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
                seen_log_ids: set[str] = set()
                for log in task_logs:
                    if not isinstance(log, dict):
                        continue
                    log_id = str(log.get("id") or f"tasklog_{uuid.uuid4().hex}")
                    if log_id in seen_log_ids:
                        continue
                    seen_log_ids.add(log_id)
                    log["id"] = log_id
                    log["taskId"] = task_id
                    log["projectId"] = project_id
                    log["stageId"] = stage_id
                    conn.execute(
                        """
                        INSERT INTO task_logs
                        (id, task_id, project_id, stage_id, time, action, user, data_json)
                        VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                        """,
                        (
                            log_id,
                            task_id,
                            project_id,
                            stage_id,
                            str(log.get("time") or ""),
                            str(log.get("action") or ""),
                            str(log.get("user") or ""),
                            json_dumps(log),
                        ),
                    )

    if active_task_ids:
        placeholders = ",".join("?" for _ in active_task_ids)
        conn.execute(f"DELETE FROM task_logs WHERE task_id NOT IN ({placeholders})", active_task_ids)
        conn.execute(f"DELETE FROM project_tasks WHERE id NOT IN ({placeholders})", active_task_ids)
    else:
        conn.execute("DELETE FROM task_logs")
        conn.execute("DELETE FROM project_tasks")

    if active_stage_ids:
        placeholders = ",".join("?" for _ in active_stage_ids)
        conn.execute(f"DELETE FROM project_stages WHERE id NOT IN ({placeholders})", active_stage_ids)
    else:
        conn.execute("DELETE FROM project_stages")

    if active_project_ids:
        placeholders = ",".join("?" for _ in active_project_ids)
        conn.execute(f"DELETE FROM project_records WHERE id NOT IN ({placeholders})", active_project_ids)
    else:
        conn.execute("DELETE FROM project_records")

    return True


def load_project_library(conn: sqlite3.Connection) -> list[dict]:
    project_rows = conn.execute(
        """
        SELECT id, name, code, owner, data_json
        FROM project_records
        WHERE deleted_at IS NULL
        ORDER BY sort_order, id
        """
    ).fetchall()
    projects: list[dict] = []
    project_map: dict[str, dict] = {}
    for row in project_rows:
        project = json_obj(row["data_json"], {}) or {}
        project.update({
            "id": row["id"],
            "name": row["name"] or project.get("name") or "",
            "code": row["code"] or project.get("code") or "",
            "owner": row["owner"] or project.get("owner") or "",
            "stages": [],
        })
        projects.append(project)
        project_map[row["id"]] = project

    stage_rows = conn.execute(
        """
        SELECT id, project_id, name, data_json
        FROM project_stages
        WHERE deleted_at IS NULL
        ORDER BY sort_order, id
        """
    ).fetchall()
    stage_map: dict[str, dict] = {}
    for row in stage_rows:
        project = project_map.get(row["project_id"])
        if not project:
            continue
        stage = json_obj(row["data_json"], {}) or {}
        stage.update({
            "id": row["id"],
            "projectId": row["project_id"],
            "name": row["name"] or stage.get("name") or "",
            "tasks": [],
        })
        project.setdefault("stages", []).append(stage)
        stage_map[row["id"]] = stage

    log_rows = conn.execute("SELECT task_id, data_json FROM task_logs ORDER BY time, id").fetchall()
    logs_by_task: dict[str, list[dict]] = {}
    for row in log_rows:
        log = json_obj(row["data_json"], None)
        if isinstance(log, dict):
            logs_by_task.setdefault(row["task_id"], []).append(log)

    task_rows = conn.execute(
        """
        SELECT id, project_id, stage_id, progress_id, category, test_item, sku_index, status, owner,
               sample_ids_json, data_json, completed_at
        FROM project_tasks
        WHERE deleted_at IS NULL
        ORDER BY created_at, id
        """
    ).fetchall()
    for row in task_rows:
        stage = stage_map.get(row["stage_id"])
        if not stage:
            continue
        task = json_obj(row["data_json"], {}) or {}
        sample_ids = json_obj(row["sample_ids_json"], [])
        if not isinstance(sample_ids, list):
            sample_ids = []
        task.update({
            "id": row["id"],
            "projectId": row["project_id"],
            "stageId": row["stage_id"],
            "progressId": row["progress_id"] or task.get("progressId") or "",
            "category": row["category"] or task.get("category") or "",
            "testItem": row["test_item"] or task.get("testItem") or "",
            "skuIndex": to_int(row["sku_index"] if row["sku_index"] is not None else task.get("skuIndex")),
            "status": row["status"] or task.get("status") or "",
            "owner": row["owner"] or task.get("owner") or "",
            "sampleIds": sample_ids,
            "logs": logs_by_task.get(row["id"], []),
        })
        if row["completed_at"] and not task.get("completedAt"):
            task["completedAt"] = row["completed_at"]
        stage.setdefault("tasks", []).append(task)

    return projects


def compose_state(conn: sqlite3.Connection) -> tuple[dict, int, str]:
    row = conn.execute("SELECT data_json, revision, updated_at FROM app_state WHERE id = 1").fetchone()
    if row is None:
        return empty_data(), 1, now_iso()
    data = json_obj(row["data_json"], empty_data()) or empty_data()
    data["version"] = APP_VERSION
    data.pop("peoplePool", None)
    data.pop("locationPool", None)
    data["projects"] = load_project_library(conn)
    data["sampleLibrary"] = load_sample_library(conn)
    return data, int(row["revision"]), str(row["updated_at"])


def init_db() -> None:
    ensure_dirs()
    with DB_LOCK:
        with connect_db() as conn:
            ensure_schema(conn)
            row = conn.execute("SELECT data_json, revision FROM app_state WHERE id = 1").fetchone()
            if row is None:
                conn.execute(
                    "INSERT INTO app_state (id, data_json, revision, updated_at) VALUES (1, ?, 1, ?)",
                    (json_dumps(split_state_for_storage(empty_data())), now_iso()),
                )
            else:
                data = json.loads(row["data_json"])
                library = data.get("sampleLibrary") or {}
                migrated = False
                if (data.get("projects") or []) and not data.get("projectsExternalized"):
                    sync_project_library(conn, data)
                    migrated = True
                    print("[MIGRATE] Projects, stages, tasks and task logs externalized to SQLite tables.")
                if (library.get("categories") or []) and not library.get("externalized"):
                    sync_sample_library(conn, data)
                    migrated = True
                    print("[MIGRATE] Sample library externalized to SQLite tables and data/samples files.")
                if migrated:
                    revision = int(row["revision"]) + 1
                    conn.execute(
                        "UPDATE app_state SET data_json = ?, revision = ?, updated_at = ? WHERE id = 1",
                        (json_dumps(split_state_for_storage(data)), revision, now_iso()),
                    )
            conn.commit()


def get_state() -> tuple[dict, int, str]:
    with DB_LOCK:
        with connect_db() as conn:
            return compose_state(conn)


def save_state(
    new_data: dict,
    expected_revision: int | None,
    client_ip: str,
    remark: str = "",
    user: str = "",
    base_data: dict | None = None,
) -> tuple[bool, dict]:
    if not isinstance(new_data, dict):
        return False, {"status": 400, "error": "data 必须是 JSON 对象"}

    with DB_LOCK:
        with connect_db() as conn:
            current_data, current_revision, _ = compose_state(conn)
            action = "save_state"

            if expected_revision is not None and int(expected_revision) != current_revision and isinstance(base_data, dict):
                new_data = merge_state(base_data, new_data, current_data)
                action = "save_state_merge"

            if expected_revision is not None and int(expected_revision) != current_revision and not isinstance(base_data, dict):
                return False, {
                    "status": 409,
                    "error": "revision 冲突，服务器数据已被其他客户端更新",
                    "server_revision": current_revision,
                }

            new_revision = current_revision + 1
            updated_at = now_iso()
            new_data["version"] = APP_VERSION

            sync_project_library(conn, new_data, allow_empty=True)
            sync_sample_library(conn, new_data, allow_empty=True)
            stored_data = split_state_for_storage(new_data)

            conn.execute(
                "UPDATE app_state SET data_json = ?, revision = ?, updated_at = ? WHERE id = 1",
                (json_dumps(stored_data), new_revision, updated_at),
            )
            conn.execute(
                """
                INSERT INTO audit_log
                (time, user, action, remark, revision_before, revision_after, client_ip)
                VALUES (?, ?, ?, ?, ?, ?, ?)
                """,
                (updated_at, user, action, remark, current_revision, new_revision, client_ip),
            )
            conn.commit()

    # 普通保存：按节流策略决定是否生成 backup
    if _should_backup(action, new_revision):
        try:
            write_backup(new_data, new_revision)
        except Exception as e:
            print(f"[WARN] 写入备份失败：{e}")

    return True, {"revision": new_revision, "updated_at": updated_at}


def parse_multipart(headers, raw: bytes) -> tuple[dict[str, str], list[dict]]:
    content_type = headers.get("Content-Type", "")
    if "multipart/form-data" not in content_type:
        raise ValueError("请求必须使用 multipart/form-data")
    envelope = (
        f"Content-Type: {content_type}\r\nMIME-Version: 1.0\r\n\r\n".encode("utf-8")
        + raw
    )
    message = BytesParser(policy=email_policy).parsebytes(envelope)
    fields: dict[str, str] = {}
    files: list[dict] = []
    for part in message.iter_parts():
        disposition = part.get("Content-Disposition", "")
        if "form-data" not in disposition:
            continue
        name = part.get_param("name", header="content-disposition") or ""
        filename = part.get_filename()
        payload = part.get_payload(decode=True) or b""
        if filename:
            files.append({
                "field": name,
                "filename": filename,
                "mime_type": part.get_content_type() or "application/octet-stream",
                "content": payload,
            })
        else:
            fields[name] = payload.decode("utf-8", errors="replace")
    return fields, files


def commit_data_mutation(conn: sqlite3.Connection, data: dict, action: str, remark: str, client_ip: str) -> dict:
    row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
    current_revision = int(row["revision"]) if row else 1
    new_revision = current_revision + 1
    updated_at = now_iso()
    data["version"] = APP_VERSION
    sync_project_library(conn, data, allow_empty=True)
    sync_sample_library(conn, data, allow_empty=True)
    conn.execute(
        "UPDATE app_state SET data_json = ?, revision = ?, updated_at = ? WHERE id = 1",
        (json_dumps(split_state_for_storage(data)), new_revision, updated_at),
    )
    conn.execute(
        """
        INSERT INTO audit_log
        (time, user, action, remark, revision_before, revision_after, client_ip)
        VALUES (?, '', ?, ?, ?, ?, ?)
        """,
        (updated_at, action, remark, current_revision, new_revision, client_ip),
    )
    conn.commit()

    # 重要操作以宽松条件生成 backup，普通 mutation 仍按节流策略
    is_important = action in IMPORTANT_ACTIONS
    if _should_backup(action, new_revision, is_important=is_important):
        try:
            write_backup(data, new_revision)
        except Exception as e:
            print(f"[WARN] 写入备份失败：{e}")
    return {"revision": new_revision, "updated_at": updated_at}


class Handler(BaseHTTPRequestHandler):
    server_version = SERVER_VERSION

    def log_message(self, fmt: str, *args) -> None:
        print(f"[{now_iso()}] {self.client_address[0]} {fmt % args}")

    def _send_json(self, payload: dict, status: int = 200) -> None:
        data = json_dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(data)

    def _send_bytes(self, data: bytes, content_type: str, status: int = 200, cache: str = "no-store") -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.end_headers()
        self.wfile.write(data)

    def _read_body(self, max_bytes: int = MAX_UPLOAD_BYTES) -> bytes:
        length = int(self.headers.get("Content-Length", "0"))
        if length > max_bytes:
            raise ValueError(f"上传内容超过限制：{max_bytes // 1024 // 1024}MB")
        return self.rfile.read(length)

    def _sample_photo_route(self, path: str) -> tuple[str, str | None] | None:
        parts = path.strip("/").split("/")
        if len(parts) >= 4 and parts[0] == "api" and parts[1] == "samples" and parts[3] == "photos":
            sample_id = unquote(parts[2])
            photo_id = unquote(parts[4]) if len(parts) >= 5 else None
            return sample_id, photo_id
        return None

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/health":
            self._send_json({"ok": True, "version": APP_VERSION, "time": now_iso(), "data_dir": str(DATA_DIR)})
            return

        if path == "/api/state":
            try:
                data, revision, updated_at = get_state()
                self._send_json({"ok": True, "revision": revision, "updated_at": updated_at, "data": data})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        photo_route = self._sample_photo_route(path)
        if photo_route and photo_route[1]:
            sample_id, photo_id = photo_route
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        row = conn.execute(
                            """
                            SELECT relative_path, mime_type
                            FROM sample_assets
                            WHERE sample_id = ? AND id = ? AND kind = 'photo' AND deleted_at IS NULL
                            """,
                            (sample_id, photo_id),
                        ).fetchone()
                if not row:
                    self._send_json({"ok": False, "error": "照片不存在"}, 404)
                    return
                target = path_inside_data(row["relative_path"])
                if not target.is_file():
                    self._send_json({"ok": False, "error": "照片文件不存在"}, 404)
                    return
                self._send_bytes(target.read_bytes(), row["mime_type"] or "application/octet-stream", cache="private, max-age=3600")
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path in ("/", "/index.html"):
            if not INDEX_PATH.exists():
                self._send_json({"ok": False, "error": "index.html 不存在"}, 404)
                return
            self._send_bytes(INDEX_PATH.read_bytes(), "text/html; charset=utf-8")
            return

        rel = path.lstrip("/")
        target = (ROOT_DIR / rel).resolve()
        if ROOT_DIR not in target.parents and target != ROOT_DIR:
            self._send_json({"ok": False, "error": "非法路径"}, 403)
            return
        if target.is_file():
            content_type = mimetypes.guess_type(str(target))[0] or "application/octet-stream"
            self._send_bytes(target.read_bytes(), content_type)
            return

        self._send_json({"ok": False, "error": "Not Found"}, 404)

    def do_POST(self) -> None:
        parsed = urlparse(self.path)
        route = self._sample_photo_route(unquote(parsed.path))
        if not route or route[1] is not None:
            self._send_json({"ok": False, "error": "Not Found"}, 404)
            return

        sample_id, _ = route
        try:
            fields, files = parse_multipart(self.headers, self._read_body())
            image_files = [f for f in files if f["field"] in ("photos", "photo", "file")]
            if not image_files:
                self._send_json({"ok": False, "error": "没有收到照片文件"}, 400)
                return

            with DB_LOCK:
                with connect_db() as conn:
                    data, _, _ = compose_state(conn)
                    _, sample = find_sample(data, sample_id)
                    if not sample:
                        self._send_json({"ok": False, "error": "样机不存在"}, 404)
                        return
                    if not isinstance(sample.get("photos"), list):
                        sample["photos"] = []
                    uploaded = []
                    for file_item in image_files:
                        meta = store_asset_bytes(
                            conn,
                            sample_id,
                            file_item["content"],
                            file_item["filename"],
                            file_item["mime_type"],
                            uploaded_by=self.client_address[0],
                        )
                        uploaded.append(meta)
                        sample["photos"].append(meta)
                    sample["updatedAt"] = now_iso()
                    result = commit_data_mutation(conn, data, "upload_sample_photos", fields.get("remark", "上传样机外观照片"), self.client_address[0])
                    self._send_json({"ok": True, **result, "uploaded": uploaded, "photos": sample["photos"]})
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_DELETE(self) -> None:
        parsed = urlparse(self.path)
        route = self._sample_photo_route(unquote(parsed.path))
        if not route or not route[1]:
            self._send_json({"ok": False, "error": "Not Found"}, 404)
            return

        sample_id, photo_id = route
        try:
            with DB_LOCK:
                with connect_db() as conn:
                    data, _, _ = compose_state(conn)
                    _, sample = find_sample(data, sample_id)
                    if not sample:
                        self._send_json({"ok": False, "error": "样机不存在"}, 404)
                        return
                    asset = conn.execute(
                        "SELECT relative_path FROM sample_assets WHERE sample_id = ? AND id = ? AND kind = 'photo' AND deleted_at IS NULL",
                        (sample_id, photo_id),
                    ).fetchone()
                    if asset:
                        try:
                            target = path_inside_data(asset["relative_path"])
                            if target.is_file():
                                target.unlink()
                        except Exception as e:
                            print(f"[WARN] 删除照片文件失败：{e}")
                    conn.execute("UPDATE sample_assets SET deleted_at = ? WHERE sample_id = ? AND id = ? AND kind = 'photo'", (now_iso(), sample_id, photo_id))
                    sample["photos"] = [p for p in (sample.get("photos") or []) if str(p.get("id")) != str(photo_id)]
                    sample["updatedAt"] = now_iso()
                    result = commit_data_mutation(conn, data, "delete_sample_photo", "删除样机外观照片", self.client_address[0])
                    self._send_json({"ok": True, **result, "photos": sample["photos"]})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_PUT(self) -> None:
        parsed = urlparse(self.path)
        if parsed.path != "/api/state":
            self._send_json({"ok": False, "error": "Not Found"}, 404)
            return

        try:
            payload = json.loads(self._read_body(max_bytes=MAX_UPLOAD_BYTES).decode("utf-8"))
            expected_revision = payload.get("revision")
            data = payload.get("data")
            base_data = payload.get("baseData")
            remark = str(payload.get("remark") or "")
            user = str(payload.get("user") or "")

            ok, result = save_state(data, expected_revision, self.client_address[0], remark=remark, user=user, base_data=base_data)
            if not ok:
                self._send_json({"ok": False, **result}, int(result.get("status", 400)))
                return

            self._send_json({"ok": True, **result})
        except json.JSONDecodeError:
            self._send_json({"ok": False, "error": "请求体不是有效 JSON"}, 400)
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)


def main() -> None:
    parser = argparse.ArgumentParser(description="数字治理平台 V6.1 内网协同版服务器")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=9398, help="监听端口，默认 9398")
    args = parser.parse_args()

    init_db()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print("=" * 70)
    print("数字治理平台 V6.1 内网协同版服务器已启动")
    print(f"根目录: {ROOT_DIR}")
    print(f"数据库: {DB_PATH}")
    print(f"样机文件目录: {SAMPLE_DATA_DIR}")
    print(f"备份目录: {BACKUP_DIR}")
    print(f"监听: http://{args.host}:{args.port}/")
    print("同事访问时请使用这台电脑的内网 IP，例如：http://10.31.118.61:9398/")
    print("停止服务：在此窗口按 Ctrl+C")
    print("=" * 70)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。")


if __name__ == "__main__":
    main()