#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""
数字治理平台 V7 内网协同版服务器

V7 的核心变化：
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
import io
import json
import mimetypes
import re
import shutil
import sqlite3
import tempfile
import threading
import time
import traceback
import uuid
import zipfile
from collections import defaultdict
from datetime import datetime, timezone
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote, unquote, unquote_to_bytes, urlparse


APP_VERSION = "V7"
SERVER_VERSION = "TestChamberServer/V7"
ROOT_DIR = Path(__file__).resolve().parent
DATA_DIR = ROOT_DIR / "data"
SAMPLE_DATA_DIR = DATA_DIR / "samples"
BACKUP_DIR = ROOT_DIR / "backups"
DB_PATH = DATA_DIR / "testchamber.sqlite"
INDEX_PATH = ROOT_DIR / "index.html"
MAX_UPLOAD_BYTES = 80 * 1024 * 1024

DEPLOYMENT_FILE = DATA_DIR / "deployment.json"
DB_LOCK = threading.Lock()

# 导入预览缓存：{previewId: {data, expires_at}}
_IMPORT_PREVIEWS: dict[str, dict] = {}


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


def load_deployment_id() -> str:
    """读取部署身份文件，返回 deploymentId 或空字符串"""
    try:
        if DEPLOYMENT_FILE.is_file():
            meta = json.loads(DEPLOYMENT_FILE.read_text(encoding="utf-8"))
            return str(meta.get("deploymentId") or "")
    except Exception:
        pass
    return ""


def ensure_deployment_id() -> str:
    """确保部署身份文件存在，不存在则创建并返回新 ID"""
    existing = load_deployment_id()
    if existing:
        return existing
    did = f"deploy_{now_iso().replace('-','').replace(':','').replace('T','_')[:15]}_{uuid.uuid4().hex[:8]}"
    meta = {"deploymentId": did, "createdAt": now_iso(), "name": "未命名部署"}
    DEPLOYMENT_FILE.write_text(json_dumps(meta, pretty=True), encoding="utf-8")
    return did


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


def thumbnail_asset_id(photo_id: str) -> str:
    return f"{photo_id}__thumb"


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

# 文件名解析正则：testchamber_v7_rev{revision}_{YYYYMMDD}_{HHMMSS}.json
_BACKUP_FILE_PATTERN = re.compile(r"testchamber_v7_rev\d+_(\d{8})_(\d{6})\.json")


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
    path = BACKUP_DIR / f"testchamber_v7_rev{revision}_{ts}.json"
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
    """清理 testchamber_v7_rev*.json 备份。
    
    规则：
    1. 只处理文件名匹配 testchamber_v7_rev*.json 的文件。
       不删除 .gitkeep、非匹配文件、SQLite 数据库等。
    2. 按小时分组，优先从文件名解析时间，解析失败则 fallback 使用文件 mtime。
       同一小时内保留最新 BACKUPS_PER_HOUR_KEEP 个，删除其余。
    3. 再按全局数量限制，只保留最新 MAX_BACKUPS_KEEP 个。
    4. 删除失败只打印 warning，不影响服务运行。
    """
    # 收集所有匹配的 backup 文件，每条记录：(hour_bucket, sort_ts, path)
    entries: list[tuple[str, float, Path]] = []
    for p in BACKUP_DIR.glob("testchamber_v7_rev*.json"):
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
        BACKUP_DIR.glob("testchamber_v7_rev*.json"),
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
    thumb_id = str(photo.get("thumbId") or photo.get("thumbnailId") or "")
    name = str(photo.get("name") or photo.get("originalName") or "外观照片")
    mime_type = str(photo.get("type") or photo.get("mimeType") or mimetypes.guess_type(name)[0] or "application/octet-stream")
    relative_path = str(photo.get("relativePath") or "")
    size = int(photo.get("size") or 0)
    uploaded_at = str(photo.get("uploadedAt") or photo.get("createdAt") or now_iso())
    meta = {
        "id": photo_id,
        "name": name,
        "type": mime_type,
        "size": size,
        "url": str(photo.get("url") or url_for_asset(sample_id, photo_id)),
        "relativePath": relative_path,
        "uploadedAt": uploaded_at,
    }
    thumb_url = str(photo.get("thumbUrl") or photo.get("thumbnailUrl") or "")
    thumb_relative_path = str(photo.get("thumbRelativePath") or photo.get("thumbnailRelativePath") or "")
    if thumb_id or thumb_url or thumb_relative_path:
        thumb_id = thumb_id or thumbnail_asset_id(photo_id)
        meta.update({
            "thumbId": thumb_id,
            "thumbUrl": thumb_url or url_for_asset(sample_id, thumb_id),
            "thumbnailUrl": thumb_url or url_for_asset(sample_id, thumb_id),
            "thumbRelativePath": thumb_relative_path,
        })
    return meta


def attach_thumbnail_meta(photo_meta: dict, thumb_meta: dict | None) -> dict:
    if not thumb_meta:
        return photo_meta
    photo_meta["thumbId"] = thumb_meta["id"]
    photo_meta["thumbUrl"] = thumb_meta["url"]
    photo_meta["thumbnailUrl"] = thumb_meta["url"]
    photo_meta["thumbRelativePath"] = thumb_meta.get("relativePath", "")
    photo_meta["thumbType"] = thumb_meta.get("type", "")
    photo_meta["thumbSize"] = thumb_meta.get("size", 0)
    return photo_meta


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


def store_thumbnail_bytes(
    conn: sqlite3.Connection,
    sample_id: str,
    photo_id: str,
    content: bytes,
    original_name: str,
    mime_type: str,
    *,
    uploaded_at: str | None = None,
    uploaded_by: str = "",
) -> dict:
    asset_id = thumbnail_asset_id(photo_id)
    ext = file_ext(original_name, mime_type)
    file_name = f"{safe_segment(asset_id, 'thumb')}{ext}"
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
        VALUES (?, ?, 'photo_thumb', ?, ?, ?, ?, ?, ?, ?, NULL)
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
    thumb_relative_path = meta.get("thumbRelativePath") or ""
    if thumb_relative_path:
        thumb_id = meta.get("thumbId") or thumbnail_asset_id(meta["id"])
        thumb_file_name = Path(thumb_relative_path).name
        conn.execute(
            """
            INSERT INTO sample_assets
            (id, sample_id, kind, original_name, file_name, relative_path, mime_type, size, created_at, created_by, deleted_at)
            VALUES (?, ?, 'photo_thumb', ?, ?, ?, ?, ?, ?, '', NULL)
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
                thumb_id,
                sample_id,
                str(photo.get("thumbName") or photo.get("thumbnailName") or f"{meta['name']} 缩略图"),
                thumb_file_name,
                thumb_relative_path,
                str(photo.get("thumbType") or photo.get("thumbnailType") or "image/jpeg"),
                int(photo.get("thumbSize") or photo.get("thumbnailSize") or 0),
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
            sample_json.pop("logs", None)
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
    photos: list[dict] = []
    for row in rows:
        meta = {
            "id": row["id"],
            "name": row["original_name"] or row["file_name"] or "外观照片",
            "type": row["mime_type"] or "application/octet-stream",
            "size": int(row["size"] or 0),
            "url": url_for_asset(sample_id, row["id"]),
            "relativePath": row["relative_path"],
            "uploadedAt": row["created_at"],
        }
        thumb_id = thumbnail_asset_id(row["id"])
        thumb = conn.execute(
            """
            SELECT id, mime_type, size, relative_path
            FROM sample_assets
            WHERE sample_id = ? AND id = ? AND kind = 'photo_thumb' AND deleted_at IS NULL
            """,
            (sample_id, thumb_id),
        ).fetchone()
        if thumb:
            meta.update({
                "thumbId": thumb["id"],
                "thumbUrl": url_for_asset(sample_id, thumb["id"]),
                "thumbnailUrl": url_for_asset(sample_id, thumb["id"]),
                "thumbRelativePath": thumb["relative_path"],
                "thumbType": thumb["mime_type"] or "image/jpeg",
                "thumbSize": int(thumb["size"] or 0),
            })
        photos.append(meta)
    return photos


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
    ensure_deployment_id()
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


# ── 导出/导入 bundle ────────────────────────────────────────────

def _preview_id() -> str:
    return f"pv_{uuid.uuid4().hex[:12]}"


def _cleanup_expired_previews() -> None:
    """清理过期的预览缓存（超过30分钟）"""
    cutoff = time.time() - 1800
    expired = [k for k, v in _IMPORT_PREVIEWS.items() if v.get("_ts", 0) < cutoff]
    for k in expired:
        _cleanup_preview_temp(k)
        del _IMPORT_PREVIEWS[k]


def _cleanup_preview_temp(preview_id: str) -> None:
    entry = _IMPORT_PREVIEWS.get(preview_id)
    if not entry:
        return
    tmp_dir = entry.get("_tmp_dir")
    if tmp_dir and Path(tmp_dir).is_dir():
        shutil.rmtree(tmp_dir, ignore_errors=True)


def _content_hash(data: object) -> str:
    return hashlib.sha256(stable_json(data).encode("utf-8")).hexdigest()[:16]


# ── ZIP 安全解压 ──

_ZIP_MAX_FILE_BYTES = 100 * 1024 * 1024   # 单个文件最大 100MB
_ZIP_MAX_TOTAL_BYTES = 500 * 1024 * 1024  # 总解压最大 500MB
_ZIP_ALLOWED_PREFIXES = (
    "manifest.json",
    "state.json",
    "checksums.json",
    "assets/samples/",
)

# 危险模式：路径穿越
_ZIP_DANGEROUS_RE = re.compile(
    r"(^|[/\\])\.\.[/\\]"       # ../ 或 ..\
    r"|^[/\\]"                   # 绝对路径
    r"|^[A-Za-z]:[/\\]"         # Windows 盘符 (C:\ D:/)
)
# 符号链接标志位（不同平台可能不同，这里只防御常见情况）
# ZipInfo.external_attr 高 16 位是 Unix 文件模式，symlink 是 0120000


def _safe_extract_zip(zf: zipfile.ZipFile, dest_dir: str) -> None:
    """安全解压 zip 到 dest_dir，防御路径穿越、符号链接、超大文件"""
    dest = Path(dest_dir).resolve()
    total_bytes = 0

    for entry in zf.infolist():
        name = entry.filename

        # 1. 拒绝危险路径模式
        if _ZIP_DANGEROUS_RE.search(name.replace("\\", "/")):
            raise ValueError(f"ZIP 包含不安全路径: {name}")

        # 2. 拒绝符号链接
        # Unix symlink: external_attr >> 16 & 0o170000 == 0o120000
        mode = (entry.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"ZIP 包含符号链接，拒绝: {name}")

        # 3. 白名单路径前缀
        allowed = any(name == p or name.startswith(p) for p in _ZIP_ALLOWED_PREFIXES)
        if not allowed:
            raise ValueError(f"ZIP 包含不允许的文件: {name}")

        # 4. 验证解压后仍在 dest 子树内
        # 先归一化路径再解析
        normalized = name.replace("\\", "/")
        target = (dest / normalized).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            raise ValueError(f"ZIP 路径越界: {name}")

        # 5. 大小检查
        file_size = entry.file_size
        if file_size > _ZIP_MAX_FILE_BYTES:
            raise ValueError(f"ZIP 文件过大 ({file_size} bytes): {name}")
        total_bytes += file_size
        if total_bytes > _ZIP_MAX_TOTAL_BYTES:
            raise ValueError(f"ZIP 总解压大小超过 {_ZIP_MAX_TOTAL_BYTES} bytes")

        # 6. 安全写入
        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(entry) as src, open(target, "wb") as dst:
                # 分块读取，避免大文件撑爆内存
                while True:
                    chunk = src.read(8192)
                    if not chunk:
                        break
                    dst.write(chunk)


def _entity_label_for_conflict(entity: str, item: dict) -> str:
    """生成冲突项的人类可读标签"""
    if entity == "project":
        return f"{item.get('name', '')} ({item.get('code', '')})"
    if entity == "stage":
        return item.get("name", "")
    if entity == "task":
        return f"{item.get('category', '')} - {item.get('testItem', '')}"
    if entity == "sample":
        parts = [s for s in [item.get("sn"), item.get("imei"), item.get("sampleNo")] if s]
        return " / ".join(parts) if parts else item.get("id", "")
    return item.get("id", "")


def _strip_view_state(data: dict) -> dict:
    """移除导出数据中的 UI 状态字段"""
    clean = copy.deepcopy(data)
    clean.pop("currentProjectId", None)
    clean.pop("currentStageId", None)
    clean.pop("peoplePool", None)
    clean.pop("locationPool", None)
    return clean


def _normalize_project(data: dict) -> dict:
    """确保项目数据结构完整"""
    data = copy.deepcopy(data)
    data.setdefault("members", [])
    data.setdefault("locations", [])
    for stage in data.get("stages") or []:
        stage.setdefault("skuNames", [])
        stage.setdefault("bom", [])
        stage.setdefault("strategy", [])
        stage.setdefault("progress", [])
        for task in stage.get("tasks") or []:
            task.setdefault("sampleIds", [])
            task.setdefault("logs", [])
            task.setdefault("removedSampleRecords", [])
            task.setdefault("sampleFaultRecords", [])
            task.setdefault("resultUploads", [])
    return data


def build_export_bundle() -> tuple[bytes, str]:
    """生成完整导出包 zip，返回 (bytes, filename)"""
    data, revision, _ = get_state()
    export_data = _strip_view_state(data)
    deployment_id = load_deployment_id()
    exported_at = now_iso()
    export_id = f"exp_{exported_at.replace('-','').replace(':','').replace('T','_')[:15]}_{uuid.uuid4().hex[:6]}"

    manifest = {
        "format": "testchamber-export-bundle-v1",
        "appVersion": APP_VERSION,
        "serverVersion": SERVER_VERSION,
        "exportedAt": exported_at,
        "exportId": export_id,
        "sourceDeploymentId": deployment_id,
        "sourceName": "",
        "revision": revision,
        "projectCount": len(export_data.get("projects") or []),
        "sampleCount": sum(
            len(c.get("samples") or [])
            for c in (export_data.get("sampleLibrary") or {}).get("categories") or []
        ),
    }

    state_json = json_dumps(export_data, pretty=True)
    manifest_json = json_dumps(manifest, pretty=True)

    checksums = {
        "manifest.json": _content_hash(manifest_json),
        "state.json": _content_hash(state_json),
    }

    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("manifest.json", manifest_json)
        zf.writestr("state.json", state_json)
        zf.writestr("checksums.json", json_dumps(checksums, pretty=True))

        # 收集照片资产（单个文件异常不中断整个导出）
        for cat in (export_data.get("sampleLibrary") or {}).get("categories") or []:
            for sample in cat.get("samples") or []:
                sid = sample.get("id")
                if not sid:
                    continue
                for photo in sample.get("photos") or []:
                    pid = photo.get("id")
                    if not pid:
                        continue
                    # 原图 — use relativePath to locate files on disk
                    rel = (photo.get("relativePath") or "").strip()
                    if rel:
                        try:
                            rp = path_inside_data(rel)
                            if rp.is_file():
                                zf.write(rp, f"assets/samples/{sid}/photos/{rp.name}")
                        except (ValueError, OSError, RuntimeError) as e:
                            print(f"[EXPORT] 跳过照片 {pid}: {e}")
                    # 缩略图 — use thumbRelativePath
                    thumb_rel = (photo.get("thumbRelativePath") or "").strip()
                    if thumb_rel:
                        try:
                            tp = path_inside_data(thumb_rel)
                            if tp.is_file():
                                zf.write(tp, f"assets/samples/{sid}/photos/{tp.name}")
                        except (ValueError, OSError, RuntimeError) as e:
                            print(f"[EXPORT] 跳过缩略图 {pid}: {e}")

    ts = exported_at.replace("-", "").replace(":", "")[:15]
    filename = f"testchamber_export_{ts}.zip"
    return buf.getvalue(), filename


def analyze_import_bundle(headers, raw_body: bytes) -> dict:
    """解压导入包，与主库对比生成 preview 分析结果"""
    _cleanup_expired_previews()

    # 使用已有 parse_multipart 提取 zip 文件
    _, files = parse_multipart(headers, raw_body)
    zip_raw = None
    for f in files:
        if f.get("filename", "").endswith(".zip"):
            zip_raw = f.get("content", b"")
            break
    if not zip_raw:
        # fallback: 取第一个文件
        for f in files:
            zip_raw = f.get("content", b"")
            break

    if not zip_raw or len(zip_raw) < 4:
        raise ValueError("未找到有效的 zip 文件内容")

    # 解压到临时目录
    tmp_dir = tempfile.mkdtemp(prefix="tcv7_import_")
    try:
        with zipfile.ZipFile(io.BytesIO(zip_raw), "r") as zf:
            _safe_extract_zip(zf, tmp_dir)

        tmp_path = Path(tmp_dir)

        # 解析 manifest
        manifest_path = tmp_path / "manifest.json"
        if not manifest_path.is_file():
            raise ValueError("导入包缺少 manifest.json")
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))

        # 解析 state
        state_path = tmp_path / "state.json"
        if not state_path.is_file():
            raise ValueError("导入包缺少 state.json")
        incoming_state = json.loads(state_path.read_text(encoding="utf-8"))

        # 获取主库当前数据
        current_data, current_revision, _ = get_state()

        # 分析
        result = _diff_import_bundle(current_data, incoming_state, manifest, tmp_path)
        preview_id = _preview_id()
        _IMPORT_PREVIEWS[preview_id] = {
            "_ts": time.time(),
            "_tmp_dir": str(tmp_path),
            "_incoming": incoming_state,
            "_revision": current_revision,
            "result": result,
        }
        # 不清理 tmp_dir（commit 时需要）
        result["previewId"] = preview_id
        return result
    except Exception:
        shutil.rmtree(tmp_dir, ignore_errors=True)
        raise


def _diff_import_bundle(current: dict, incoming: dict, manifest: dict, _tmp_path: Path) -> dict:
    """对比主库与导入数据，生成 autoApply / conflicts / blockers"""
    auto_apply: list[dict] = []
    conflicts: list[dict] = []
    conflict_idx = [0]

    def _next_conflict_id():
        conflict_idx[0] += 1
        return f"conflict_{conflict_idx[0]:04d}"

    # 构建主库索引
    curr_projects = {p["id"]: p for p in (current.get("projects") or [])}
    curr_project_codes = {p.get("code", ""): p for p in (current.get("projects") or []) if p.get("code")}
    curr_project_names = {p.get("name", "").strip().lower(): p for p in (current.get("projects") or []) if p.get("name")}

    # 构建导入样机索引（用于样机身份匹配）
    curr_samples: list[dict] = []
    for cat in (current.get("sampleLibrary") or {}).get("categories") or []:
        for s in cat.get("samples") or []:
            s_copy = dict(s)
            s_copy["_categoryName"] = cat.get("name", "")
            curr_samples.append(s_copy)
    curr_samples_by_id = {s["id"]: s for s in curr_samples}
    curr_samples_by_sn = {}
    curr_samples_by_imei = {}
    for s in curr_samples:
        sn = (s.get("sn") or "").strip()
        imei = (s.get("imei") or "").strip()
        sno = (s.get("sampleNo") or "").strip()
        if sn:
            curr_samples_by_sn.setdefault(sn, []).append(s)
        if imei:
            curr_samples_by_imei.setdefault(imei, []).append(s)
        if sno and not sn:
            curr_samples_by_sn.setdefault(sno, []).append(s)

    # 检查照片文件缺失
    missing_photo_assets: list[str] = []
    for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
        for sample in cat.get("samples") or []:
            sid = sample.get("id", "")
            for photo in sample.get("photos") or []:
                pid = photo.get("id", "")
                rel = photo.get("relativePath", "")
                if rel:
                    # 检查文件是否在 assets 目录中（相对于导入包）
                    fn = Path(rel).name
                    asset_path = _tmp_path / "assets" / "samples" / sid / "photos" / fn
                    if not asset_path.is_file():
                        missing_photo_assets.append(pid)

    blockers = []
    if missing_photo_assets:
        blockers.append({
            "type": "missing_photos",
            "assetIds": missing_photo_assets[:20],
            "count": len(missing_photo_assets),
        })

    # ── 项目匹配 ──
    matched_incoming_projects: dict[str, tuple[str, str | None]] = {}  # incomingId -> (targetId | newName)

    for proj in incoming.get("projects") or []:
        pid = proj.get("id", "")
        pname = (proj.get("name") or "").strip()
        pcode = (proj.get("code") or "").strip()

        # 1) ID 相同
        if pid and pid in curr_projects:
            curr_p = curr_projects[pid]
            field_diffs = _diff_fields(curr_p, proj, skip_keys={"stages", "tasks"})
            if field_diffs:
                conflicts.append({
                    "conflictId": _next_conflict_id(),
                    "type": "field_conflict",
                    "entity": "project",
                    "currentId": pid, "incomingId": pid,
                    "label": _entity_label_for_conflict("project", proj),
                    "current": {k: curr_p.get(k) for k in field_diffs},
                    "incoming": {k: proj.get(k) for k in field_diffs},
                    "diffFields": list(field_diffs),
                    "allowedActions": ["apply_field_choices"],
                })
            # 递归匹配阶段/任务
            _diff_stages(curr_p, proj, pid, pid, _next_conflict_id, conflicts, auto_apply)
            continue

        # 2) code 相同
        if pcode and pcode in curr_project_codes:
            curr_p = curr_project_codes[pcode]
            conflicts.append({
                "conflictId": _next_conflict_id(),
                "type": "project_name_conflict",
                "entity": "project",
                "currentId": curr_p["id"], "incomingId": pid,
                "label": f"{pname} (code: {pcode})",
                "current": {"name": curr_p.get("name"), "code": curr_p.get("code")},
                "incoming": {"name": pname, "code": pcode},
                "allowedActions": ["merge_into_existing", "rename_import", "skip"],
                "preferredMergeTarget": curr_p["id"],
            })
            continue

        # 3) name 相同（大小写不敏感）
        if pname and pname.lower() in curr_project_names:
            curr_p = curr_project_names[pname.lower()]
            conflicts.append({
                "conflictId": _next_conflict_id(),
                "type": "project_name_conflict",
                "entity": "project",
                "currentId": curr_p["id"], "incomingId": pid,
                "label": pname,
                "current": {"name": curr_p.get("name"), "code": curr_p.get("code")},
                "incoming": {"name": pname, "code": pcode},
                "allowedActions": ["merge_into_existing", "rename_import", "skip"],
                "preferredMergeTarget": curr_p["id"],
            })
            continue

        # 4) 新增项目
        auto_apply.append({"type": "new_project", "id": pid, "name": pname, "label": pname})
        matched_incoming_projects[pid] = (pid, None)  # 直接新增
        # 递归处理其内部阶段/任务（都作为新增）
        for stage in proj.get("stages") or []:
            auto_apply.append({"type": "new_stage", "id": stage.get("id"), "name": stage.get("name", ""), "projectId": pid})
            for task in stage.get("tasks") or []:
                auto_apply.append({"type": "new_task", "id": task.get("id"),
                    "label": f"{task.get('category','')}-{task.get('testItem','')}",
                    "projectId": pid, "stageId": stage.get("id")})

    # ── 样机匹配 ──
    for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
        cat_name = cat.get("name", "")
        for sample in cat.get("samples") or []:
            sid = sample.get("id", "")
            sn = (sample.get("sn") or "").strip()
            imei = (sample.get("imei") or "").strip()
            sno = (sample.get("sampleNo") or "").strip()

            # 1) ID 相同
            if sid and sid in curr_samples_by_id:
                curr_s = curr_samples_by_id[sid]
                field_diffs = _diff_fields(curr_s, sample, skip_keys={"photos", "logs", "problemRecords", "photos", "_categoryName"})
                if field_diffs:
                    conflicts.append({
                        "conflictId": _next_conflict_id(),
                        "type": "field_conflict",
                        "entity": "sample",
                        "currentId": sid, "incomingId": sid,
                        "label": _entity_label_for_conflict("sample", sample),
                        "current": {k: curr_s.get(k) for k in field_diffs},
                        "incoming": {k: sample.get(k) for k in field_diffs},
                        "diffFields": list(field_diffs),
                        "allowedActions": ["apply_field_choices"],
                        "mergeableFields": list(field_diffs),
                    })
                continue

            # 2) SN 相同
            if sn and sn in curr_samples_by_sn:
                curr_s = curr_samples_by_sn[sn][0]
                if curr_s["id"] != sid:
                    mergeable = ["location", "owner", "status", "borrower", "sourceStageName", "sourceSkuName"]
                    conflicts.append({
                        "conflictId": _next_conflict_id(),
                        "type": "sample_identity_conflict",
                        "entity": "sample",
                        "currentId": curr_s["id"], "incomingId": sid,
                        "matchBy": "sn",
                        "label": f"SN: {sn}",
                        "current": {k: curr_s.get(k) for k in mergeable if curr_s.get(k) != sample.get(k)},
                        "incoming": {k: sample.get(k) for k in mergeable if curr_s.get(k) != sample.get(k)},
                        "allowedActions": ["merge_into_existing", "import_as_new_with_identity_edit", "skip"],
                        "mergeableFields": mergeable,
                        "autoMergeSubData": ["logs", "photos", "problemRecords"],
                        "preferredMergeTarget": curr_s["id"],
                    })
                    continue

            # 3) IMEI 相同
            if imei and imei in curr_samples_by_imei:
                curr_s = curr_samples_by_imei[imei][0]
                if curr_s["id"] != sid:
                    mergeable = ["location", "owner", "status", "borrower", "sourceStageName", "sourceSkuName"]
                    conflicts.append({
                        "conflictId": _next_conflict_id(),
                        "type": "sample_identity_conflict",
                        "entity": "sample",
                        "currentId": curr_s["id"], "incomingId": sid,
                        "matchBy": "imei",
                        "label": f"IMEI: {imei}",
                        "current": {k: curr_s.get(k) for k in mergeable if curr_s.get(k) != sample.get(k)},
                        "incoming": {k: sample.get(k) for k in mergeable if curr_s.get(k) != sample.get(k)},
                        "allowedActions": ["merge_into_existing", "import_as_new_with_identity_edit", "skip"],
                        "mergeableFields": mergeable,
                        "autoMergeSubData": ["logs", "photos", "problemRecords"],
                        "preferredMergeTarget": curr_s["id"],
                    })
                    continue

            # 4) 新增样机
            auto_apply.append({"type": "new_sample", "id": sid, "sn": sn, "label": _entity_label_for_conflict("sample", sample), "categoryName": cat_name})

    # 任务占用冲突检测
    for proj in incoming.get("projects") or []:
        for stage in proj.get("stages") or []:
            for task in stage.get("tasks") or []:
                if task.get("status") in ("进行中", "阻塞中"):
                    for sid in task.get("sampleIds") or []:
                        if sid in curr_samples_by_id:
                            curr_s = curr_samples_by_id[sid]
                            if curr_s.get("currentTaskId") and curr_s["currentTaskId"] != task.get("id"):
                                conflicts.append({
                                    "conflictId": _next_conflict_id(),
                                    "type": "task_occupancy_conflict",
                                    "entity": "sample",
                                    "sampleId": sid,
                                    "label": _entity_label_for_conflict("sample", curr_s),
                                    "currentTaskId": curr_s["currentTaskId"],
                                    "incomingTaskId": task.get("id"),
                                    "incomingTaskLabel": _entity_label_for_conflict("task", task),
                                    "allowedActions": ["skip_occupancy", "import_no_occupy"],
                                })

    # 统计
    summary = {
        "projects": {
            "new": sum(1 for a in auto_apply if a["type"] == "new_project"),
            "conflict": sum(1 for c in conflicts if c["entity"] == "project"),
        },
        "stages": {
            "new": sum(1 for a in auto_apply if a["type"] == "new_stage"),
        },
        "tasks": {
            "new": sum(1 for a in auto_apply if a["type"] == "new_task"),
            "conflict": sum(1 for c in conflicts if c["entity"] == "task"),
        },
        "samples": {
            "new": sum(1 for a in auto_apply if a["type"] == "new_sample"),
            "conflict": sum(1 for c in conflicts if c["entity"] == "sample"),
        },
        "sampleIdentityConflicts": sum(1 for c in conflicts if c["type"] == "sample_identity_conflict"),
        "fieldConflicts": sum(1 for c in conflicts if c["type"] == "field_conflict"),
        "occupancyConflicts": sum(1 for c in conflicts if c["type"] == "task_occupancy_conflict"),
        "nameConflicts": sum(1 for c in conflicts if c["type"] in ("project_name_conflict", "stage_name_conflict")),
    }

    return {
        "source": {
            "deploymentId": manifest.get("sourceDeploymentId", ""),
            "revision": manifest.get("revision", 0),
            "exportedAt": manifest.get("exportedAt", ""),
            "appVersion": manifest.get("appVersion", ""),
        },
        "summary": summary,
        "autoApply": auto_apply,
        "conflicts": conflicts,
        "blockers": blockers,
    }


def _diff_stages(curr_proj: dict, incoming_proj: dict, curr_proj_id: str, inc_proj_id: str,
                  _next_id, conflicts: list, auto_apply: list):
    """递归比较阶段和任务"""
    curr_stages = {s["id"]: s for s in (curr_proj.get("stages") or [])}
    curr_stage_names = {s.get("name", "").strip().lower(): s for s in (curr_proj.get("stages") or []) if s.get("name")}

    for stage in incoming_proj.get("stages") or []:
        sid = stage.get("id", "")
        sname = (stage.get("name") or "").strip()

        if sid and sid in curr_stages:
            curr_s = curr_stages[sid]
            field_diffs = _diff_fields(curr_s, stage, skip_keys={"tasks"})
            if field_diffs:
                conflicts.append({
                    "conflictId": _next_id(),
                    "type": "field_conflict",
                    "entity": "stage",
                    "currentId": sid, "incomingId": sid,
                    "label": f"阶段: {sname}",
                    "current": {k: curr_s.get(k) for k in field_diffs},
                    "incoming": {k: stage.get(k) for k in field_diffs},
                    "diffFields": list(field_diffs),
                    "allowedActions": ["apply_field_choices"],
                })
            # 递归任务
            curr_tasks = {t["id"]: t for t in (curr_s.get("tasks") or [])}
            for task in stage.get("tasks") or []:
                tid = task.get("id", "")
                tlabel = f"{task.get('category','')}-{task.get('testItem','')}"
                if tid and tid in curr_tasks:
                    curr_t = curr_tasks[tid]
                    field_diffs = _diff_fields(curr_t, task, skip_keys={"logs", "sampleIds", "removedSampleRecords", "sampleFaultRecords", "resultUploads", "resultDraft"})
                    if field_diffs:
                        conflicts.append({
                            "conflictId": _next_id(),
                            "type": "field_conflict",
                            "entity": "task",
                            "currentId": tid, "incomingId": tid,
                            "label": tlabel,
                            "current": {k: curr_t.get(k) for k in field_diffs},
                            "incoming": {k: task.get(k) for k in field_diffs},
                            "diffFields": list(field_diffs),
                            "allowedActions": ["apply_field_choices"],
                            "mergeableFields": list(field_diffs),
                        })
                else:
                    # 检查是否有同名任务
                    matched = None
                    for ctid, ct in curr_tasks.items():
                        if ct.get("category") == task.get("category") and ct.get("testItem") == task.get("testItem") and ct.get("skuIndex") == task.get("skuIndex"):
                            matched = ct
                            break
                    if matched:
                        conflicts.append({
                            "conflictId": _next_id(),
                            "type": "task_name_conflict",
                            "entity": "task",
                            "currentId": matched["id"], "incomingId": tid,
                            "label": tlabel,
                            "current": {"category": matched.get("category"), "testItem": matched.get("testItem"), "status": matched.get("status")},
                            "incoming": {"category": task.get("category"), "testItem": task.get("testItem"), "status": task.get("status")},
                            "allowedActions": ["merge_into_existing", "rename_import", "skip"],
                            "preferredMergeTarget": matched["id"],
                        })
                    else:
                        auto_apply.append({"type": "new_task", "id": tid, "label": tlabel, "projectId": curr_proj_id, "stageId": sid})
            continue

        if sname and sname.lower() in curr_stage_names:
            curr_s = curr_stage_names[sname.lower()]
            conflicts.append({
                "conflictId": _next_id(),
                "type": "stage_name_conflict",
                "entity": "stage",
                "currentId": curr_s["id"], "incomingId": sid,
                "label": sname,
                "current": {"name": curr_s.get("name")},
                "incoming": {"name": sname},
                "allowedActions": ["merge_into_existing", "rename_import", "skip"],
                "preferredMergeTarget": curr_s["id"],
            })
            continue

        # 新增阶段
        auto_apply.append({"type": "new_stage", "id": sid, "name": sname, "projectId": curr_proj_id})
        for task in stage.get("tasks") or []:
            auto_apply.append({"type": "new_task", "id": task.get("id"),
                "label": f"{task.get('category','')}-{task.get('testItem','')}",
                "projectId": curr_proj_id, "stageId": sid})


def _diff_fields(current_item: dict, incoming_item: dict, skip_keys: set = set()) -> set:
    """返回两个字典中有差异的字段名集合（排除 skip_keys）"""
    diffs = set()
    all_keys = set(current_item.keys()) | set(incoming_item.keys())
    for k in all_keys:
        if k in skip_keys or k.startswith("_"):
            continue
        cv = current_item.get(k)
        iv = incoming_item.get(k)
        if stable_json(cv) != stable_json(iv):
            diffs.add(k)
    return diffs


def commit_import_bundle(payload: dict) -> dict:
    """执行导入写入"""
    preview_id = payload.get("previewId", "")
    decisions = payload.get("decisions") or {}

    _cleanup_expired_previews()
    entry = _IMPORT_PREVIEWS.get(preview_id)
    if not entry:
        return {"ok": False, "error": "previewId 无效或已过期", "status": 400}

    result = entry.get("result") or {}
    blockers = result.get("blockers") or []
    if blockers:
        return {"ok": False, "error": "存在阻断项（如缺失照片），无法提交导入", "blockers": blockers, "status": 400}

    # ── Revision 校验：commit 时主库 revision 必须与 preview 时一致 ──
    preview_revision = entry.get("_revision")
    if preview_revision is not None:
        _, current_revision_check, _ = get_state()
        if current_revision_check != preview_revision:
            return {"ok": False,
                    "error": "服务器数据在预览后被其他用户修改，请重新选择文件导入。",
                    "error_code": "IMPORT_REVISION_CONFLICT",
                    "server_revision": current_revision_check,
                    "status": 409}

    # 验证所有 conflict 都有 decision
    for c in result.get("conflicts") or []:
        cid = c.get("conflictId")
        if cid not in decisions:
            return {"ok": False, "error": f"冲突 {cid} 尚未处理", "status": 400}
        d = decisions[cid]
        action = d.get("action", "")
        if action == "rename_import":
            # 项目/阶段/任务改名导入：必须有 newName
            if not d.get("newName", "").strip():
                return {"ok": False, "error": f"冲突 {cid} 选择改名导入但未提供新名称", "status": 400}
        elif action == "import_as_new_with_identity_edit":
            # 样机标识编辑导入：必须有至少一个新标识字段
            new_sn = (d.get("newSN") or "").strip()
            new_imei = (d.get("newIMEI") or "").strip()
            new_sample_no = (d.get("newSampleNo") or "").strip()
            if not new_sn and not new_imei and not new_sample_no:
                return {"ok": False, "error": f"冲突 {cid} 选择编辑标识导入但未提供新 SN/IMEI/编号", "status": 400}

    # 先备份
    current_data, current_revision, _ = get_state()
    write_backup(current_data, current_revision)

    incoming = copy.deepcopy(entry["_incoming"])
    tmp_dir = Path(entry["_tmp_dir"])
    source_manifest = (result.get("source") or {})

    # 构建决策索引
    decision_map: dict[str, dict] = {}
    for c in result.get("conflicts") or []:
        cid = c.get("conflictId", "")
        if cid in decisions:
            decision_map[cid] = decisions[cid]

    # ── 处理项目 ──
    curr_projects = {p["id"]: p for p in (current_data.setdefault("projects", []))}
    incoming_projects_by_id = {p["id"]: p for p in (incoming.get("projects") or [])}

    stats = {"projectsAdded": 0, "projectsMerged": 0, "stagesAdded": 0, "stagesMerged": 0,
             "tasksAdded": 0, "tasksMerged": 0, "samplesAdded": 0, "samplesMerged": 0,
             "photosAdded": 0, "skipped": 0}

    # ── ID 映射表（incoming → target），所有写入必须经此重映射 ──
    project_id_map: dict[str, str] = {}  # incomingPID → targetPID
    stage_id_map: dict[str, str] = {}    # incomingSID → targetSID
    task_id_map: dict[str, str] = {}     # incomingTID → targetTID
    sample_id_map: dict[str, str] = {}   # incomingSampleID → targetSampleID

    for auto in result.get("autoApply") or []:
        atype = auto["type"]
        if atype == "new_project":
            pid = auto["id"]
            if pid not in curr_projects and pid in incoming_projects_by_id:
                curr_projects[pid] = _normalize_project(incoming_projects_by_id[pid])
                stats["projectsAdded"] += 1
                project_id_map[pid] = pid
        elif atype == "new_stage":
            proj_id = auto.get("projectId", "")
            sid = auto["id"]
            if proj_id in curr_projects and proj_id in incoming_projects_by_id:
                inc_proj = incoming_projects_by_id[proj_id]
                for inc_stage in inc_proj.get("stages") or []:
                    if inc_stage.get("id") == sid:
                        curr_projects[proj_id].setdefault("stages", []).append(copy.deepcopy(inc_stage))
                        stats["stagesAdded"] += 1
                        stage_id_map[sid] = sid
                        break
        elif atype == "new_task":
            proj_id = auto.get("projectId", "")
            stage_id = auto.get("stageId", "")
            tid = auto["id"]
            if proj_id in curr_projects and proj_id in incoming_projects_by_id:
                inc_proj = incoming_projects_by_id[proj_id]
                for inc_stage in inc_proj.get("stages") or []:
                    if inc_stage.get("id") == stage_id:
                        for inc_task in inc_stage.get("tasks") or []:
                            if inc_task.get("id") == tid:
                                curr_stages = curr_projects[proj_id].setdefault("stages", [])
                                for cs in curr_stages:
                                    if cs.get("id") == stage_id:
                                        cs.setdefault("tasks", []).append(copy.deepcopy(inc_task))
                                        stats["tasksAdded"] += 1
                                        task_id_map[tid] = tid
                                        break
                                break
                        break
        elif atype == "new_sample":
            sid = auto["id"]
            # 稍后处理

    # 处理样机类别索引（field_conflict 中 sample 类型需要）
    curr_categories = {c["id"]: c for c in (current_data.setdefault("sampleLibrary", {})).setdefault("categories", [])}
    incoming_cats_by_id = {}
    for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
        incoming_cats_by_id[cat["id"]] = cat
        for s in cat.get("samples") or []:
            incoming_cats_by_id[s["id"]] = s

    # 处理项目级冲突
    for c in result.get("conflicts") or []:
        cid = c["conflictId"]
        d = decision_map.get(cid, {})
        action = d.get("action", "skip")
        etype = c.get("entity")

        # ── 硬规则：未实现冲突类型必须报错 ──
        ctype = c.get("type", "unknown")
        SUPPORTED = ("field_conflict", "project_name_conflict",
                     "stage_name_conflict", "task_name_conflict",
                     "sample_identity_conflict", "task_occupancy_conflict")
        if ctype not in SUPPORTED:
            return {"ok": False,
                    "error": f"不支持的冲突类型: {ctype} (冲突 {cid})",
                    "error_code": "UNSUPPORTED_IMPORT_CONFLICT", "status": 400}

        # ── field_conflict：统一处理所有实体类型 ──
        if c.get("type") == "field_conflict":
            if action == "apply_field_choices":
                field_choices = d.get("fieldChoices", {})
                target_id = c.get("currentId")
                inc_id = c.get("incomingId")
                if etype == "project":
                    if target_id in curr_projects and inc_id in incoming_projects_by_id:
                        curr_p = curr_projects[target_id]
                        inc_p = incoming_projects_by_id[inc_id]
                        for fname in c.get("diffFields", []):
                            choice = field_choices.get(fname, "current")
                            if choice == "incoming" and fname in inc_p:
                                curr_p[fname] = inc_p[fname]
                        stats["projectsMerged"] += 1
                        project_id_map[inc_id] = target_id
                elif etype == "stage":
                    # 在当前主库中查找 stage
                    for proj_id, proj in curr_projects.items():
                        for stage in proj.get("stages") or []:
                            if stage.get("id") == target_id:
                                inc_stage = _find_incoming_stage(incoming_projects_by_id, inc_id)
                                if inc_stage:
                                    for fname in c.get("diffFields", []):
                                        choice = field_choices.get(fname, "current")
                                        if choice == "incoming" and fname in inc_stage:
                                            stage[fname] = inc_stage[fname]
                                break
                elif etype == "task":
                    for proj_id, proj in curr_projects.items():
                        for stage in proj.get("stages") or []:
                            for task in stage.get("tasks") or []:
                                if task.get("id") == target_id:
                                    inc_task = _find_incoming_task(incoming_projects_by_id, inc_id)
                                    if inc_task:
                                        for fname in c.get("diffFields", []):
                                            choice = field_choices.get(fname, "current")
                                            if choice == "incoming" and fname in inc_task:
                                                task[fname] = inc_task[fname]
                                    break
                elif etype == "sample":
                    for cat_id, cat in curr_categories.items():
                        for cs in cat.get("samples") or []:
                            if cs.get("id") == target_id:
                                inc_sample = incoming_cats_by_id.get(inc_id)
                                if inc_sample and isinstance(inc_sample, dict):
                                    for fname in c.get("diffFields", []):
                                        choice = field_choices.get(fname, "current")
                                        if choice == "incoming" and fname in inc_sample:
                                            cs[fname] = inc_sample[fname]
                                break
            elif action == "skip":
                stats["skipped"] += 1
            continue  # field_conflict 已处理，跳过后续 entity 特定逻辑

        if etype == "project":
            ipid = c.get("incomingId")
            if action == "merge_into_existing":
                target_id = d.get("targetId") or c.get("preferredMergeTarget") or c.get("currentId")
                if ipid in incoming_projects_by_id and target_id in curr_projects:
                    # 合并：追加子数据（阶段/任务），不覆盖项目主字段
                    inc_proj = incoming_projects_by_id[ipid]
                    curr_proj = curr_projects[target_id]
                    _merge_project_sub_data(curr_proj, inc_proj)
                    stats["projectsMerged"] += 1
                    project_id_map[ipid] = target_id
            elif action == "rename_import":
                new_name = d.get("newName", "").strip()
                if new_name and ipid in incoming_projects_by_id:
                    inc_proj = incoming_projects_by_id[ipid]
                    inc_proj["name"] = new_name
                    curr_projects[ipid] = _normalize_project(inc_proj)
                    stats["projectsAdded"] += 1
                    project_id_map[ipid] = ipid
            elif action == "skip":
                stats["skipped"] += 1

        # ── stage_name_conflict ──
        elif c.get("type") == "stage_name_conflict":
            inc_sid = c.get("incomingId")
            inc_stage = _find_incoming_stage(incoming_projects_by_id, inc_sid)
            if action == "merge_into_existing":
                target_id = d.get("targetId") or c.get("preferredMergeTarget") or c.get("currentId")
                if inc_stage and target_id:
                    for proj_id, proj in curr_projects.items():
                        for st in proj.get("stages") or []:
                            if st.get("id") == target_id:
                                existing_task_ids = {t.get("id") for t in (st.get("tasks") or [])}
                                for inc_task in inc_stage.get("tasks") or []:
                                    tid = inc_task.get("id", "")
                                    if tid and tid not in existing_task_ids:
                                        st.setdefault("tasks", []).append(copy.deepcopy(inc_task))
                                        stats["tasksAdded"] += 1
                                        existing_task_ids.add(tid)
                                stats["stagesMerged"] += 1
                                stage_id_map[inc_sid] = target_id
                                break
            elif action == "rename_import":
                new_name = d.get("newName", "").strip()
                if new_name and inc_stage and inc_sid:
                    inc_stage["name"] = new_name
                    # 查找 stage 所属的 incoming project，经 project_id_map 定位 target project
                    for inc_pid, inc_proj in incoming_projects_by_id.items():
                        found = any(s.get("id") == inc_sid for s in (inc_proj.get("stages") or []))
                        if found:
                            target_pid = project_id_map.get(inc_pid, inc_pid)
                            if target_pid in curr_projects:
                                curr_projects[target_pid].setdefault("stages", []).append(copy.deepcopy(inc_stage))
                                stats["stagesAdded"] += 1
                                stage_id_map[inc_sid] = inc_sid
                            break
            elif action == "skip":
                stats["skipped"] += 1

        # ── task_name_conflict ──
        elif c.get("type") == "task_name_conflict":
            inc_tid = c.get("incomingId")
            inc_task = _find_incoming_task(incoming_projects_by_id, inc_tid)
            if action == "merge_into_existing":
                target_id = d.get("targetId") or c.get("preferredMergeTarget") or c.get("currentId")
                if inc_task and target_id:
                    for proj_id, proj in curr_projects.items():
                        for st in proj.get("stages") or []:
                            for tk in st.get("tasks") or []:
                                if tk.get("id") == target_id:
                                    # 合并日志/结果
                                    for subkey in ("logs", "resultUploads", "sampleFaultRecords", "removedSampleRecords"):
                                        existing_hashes = {_content_hash(x) for x in (tk.get(subkey) or [])}
                                        for item in (inc_task.get(subkey) or []):
                                            if _content_hash(item) not in existing_hashes:
                                                tk.setdefault(subkey, []).append(copy.deepcopy(item))
                                                existing_hashes.add(_content_hash(item))
                                    stats["tasksMerged"] += 1
                                    task_id_map[inc_tid] = target_id
                                    break
            elif action == "rename_import":
                new_name = d.get("newName", "").strip()
                if new_name and inc_task and inc_tid:
                    inc_task["testItem"] = new_name
                    # 找到 task 所属的 stage → project，经映射定位
                    for inc_pid, inc_proj in incoming_projects_by_id.items():
                        for inc_st in (inc_proj.get("stages") or []):
                            for inc_tk in (inc_st.get("tasks") or []):
                                if inc_tk.get("id") == inc_tid:
                                    target_pid = project_id_map.get(inc_pid, inc_pid)
                                    target_sid = stage_id_map.get(inc_st.get("id"), inc_st.get("id"))
                                    if target_pid in curr_projects:
                                        for cs in curr_projects[target_pid].get("stages") or []:
                                            if cs.get("id") == target_sid:
                                                cs.setdefault("tasks", []).append(copy.deepcopy(inc_task))
                                                stats["tasksAdded"] += 1
                                                task_id_map[inc_tid] = inc_tid
                                                break
                                    break
            elif action == "skip":
                stats["skipped"] += 1

        # ── task_occupancy_conflict ──
        elif c.get("type") == "task_occupancy_conflict":
            sid = c.get("sampleId")
            if action in ("skip_occupancy", "import_no_occupy", "skip"):
                if action == "skip_occupancy" and sid:
                    # 清除导入样机的占用字段
                    for inc_cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
                        for inc_s in inc_cat.get("samples") or []:
                            if inc_s.get("id") == sid:
                                inc_s["currentTaskId"] = None
                                inc_s["currentProjectId"] = None
                                inc_s["currentStageId"] = None
                                inc_s["currentTestItem"] = None
                                break
                stats["skipped"] += 1

    # 处理样机
    curr_categories = {c["id"]: c for c in (current_data.setdefault("sampleLibrary", {})).setdefault("categories", [])}
    incoming_cats_by_id = {}
    for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
        incoming_cats_by_id[cat["id"]] = cat
        for s in cat.get("samples") or []:
            incoming_cats_by_id[s["id"]] = s  # 也索引样机

    # 新增样机
    for auto in result.get("autoApply") or []:
        if auto["type"] == "new_sample":
            sid = auto["id"]
            # 找到样机所属类别并添加
            for inc_cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
                for inc_s in inc_cat.get("samples") or []:
                    if inc_s.get("id") == sid:
                        cat_name = inc_cat.get("name", "")
                        # 找到或创建主库类别
                        target_cat = None
                        for cid, c in curr_categories.items():
                            if c.get("name") == cat_name:
                                target_cat = c
                                break
                        if not target_cat:
                            new_cat_id = f"cat_{uuid.uuid4().hex[:12]}"
                            target_cat = {"id": new_cat_id, "name": cat_name, "description": "", "samples": []}
                            curr_categories[new_cat_id] = target_cat
                        target_cat.setdefault("samples", []).append(copy.deepcopy(inc_s))
                        stats["samplesAdded"] += 1
                        sample_id_map[sid] = sid
                        break

    # 处理样机冲突
    for c in result.get("conflicts") or []:
        if c.get("entity") != "sample":
            continue
        cid = c["conflictId"]
        d = decision_map.get(cid, {})
        action = d.get("action", "skip")

        if c["type"] == "sample_identity_conflict":
            if action == "merge_into_existing":
                target_id = d.get("targetId") or c.get("preferredMergeTarget") or c.get("currentId")
                inc_id = c.get("incomingId")
                # 找到导入样机
                inc_sample = None
                for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
                    for s in cat.get("samples") or []:
                        if s.get("id") == inc_id:
                            inc_sample = s
                            break
                if inc_sample and target_id:
                    # 找到主库样机并合并
                    for cat_id, cat in curr_categories.items():
                        for cs in cat.get("samples") or []:
                            if cs.get("id") == target_id:
                                # 逐字段选择
                                field_choices = d.get("fieldChoices", {})
                                for fname in c.get("mergeableFields", []):
                                    choice = field_choices.get(fname, "current")
                                    if choice == "incoming" and fname in inc_sample:
                                        cs[fname] = inc_sample[fname]
                                # 追加子数据
                                sub_data_keys = c.get("autoMergeSubData", [])
                                for subk in sub_data_keys:
                                    if subk == "photos":
                                        existing = {p.get("id"): p for p in (cs.get("photos") or [])}
                                        for p in inc_sample.get("photos") or []:
                                            if p.get("id") not in existing:
                                                cs.setdefault("photos", []).append(copy.deepcopy(p))
                                                stats["photosAdded"] += 1
                                    elif subk == "problemRecords":
                                        existing_hashes = {_content_hash(pr) for pr in (cs.get("problemRecords") or [])}
                                        for pr in inc_sample.get("problemRecords") or []:
                                            if _content_hash(pr) not in existing_hashes:
                                                cs.setdefault("problemRecords", []).append(copy.deepcopy(pr))
                                                existing_hashes.add(_content_hash(pr))
                                    elif subk == "logs":
                                        existing_hashes = {_content_hash(log) for log in (cs.get("logs") or [])}
                                        for log in inc_sample.get("logs") or []:
                                            if _content_hash(log) not in existing_hashes:
                                                cs.setdefault("logs", []).append(copy.deepcopy(log))
                                                existing_hashes.add(_content_hash(log))
                                stats["samplesMerged"] += 1
                                sample_id_map[inc_id] = target_id
                                break
            elif action == "import_as_new_with_identity_edit":
                inc_id = c.get("incomingId")
                new_sn = d.get("newSN", "").strip()
                new_imei = d.get("newIMEI", "").strip()
                new_sample_no = d.get("newSampleNo", "").strip()
                # 找到导入样机
                inc_sample = None
                inc_cat_name = ""
                for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
                    for s in cat.get("samples") or []:
                        if s.get("id") == inc_id:
                            inc_sample = s
                            inc_cat_name = cat.get("name", "")
                            break
                if inc_sample:
                    if new_sn:
                        inc_sample["sn"] = new_sn
                    if new_imei:
                        inc_sample["imei"] = new_imei
                    if new_sample_no:
                        inc_sample["sampleNo"] = new_sample_no
                    # 添加到类别
                    target_cat = None
                    for cid, cat in curr_categories.items():
                        if cat.get("name") == inc_cat_name:
                            target_cat = cat
                            break
                    if not target_cat:
                        new_cat_id = f"cat_{uuid.uuid4().hex[:12]}"
                        target_cat = {"id": new_cat_id, "name": inc_cat_name, "description": "", "samples": []}
                        curr_categories[new_cat_id] = target_cat
                    target_cat.setdefault("samples", []).append(copy.deepcopy(inc_sample))
                    stats["samplesAdded"] += 1
                    sample_id_map[inc_id] = inc_id
            elif action == "skip":
                stats["skipped"] += 1

    # ── 复制照片资产文件（经 sample_id_map 定位源文件）──
    # 反向映射：target sample ID → incoming sample ID
    target_to_incoming_sample: dict[str, str] = {v: k for k, v in sample_id_map.items()}
    for cat in curr_categories.values():
        for sample in cat.get("samples") or []:
            target_sid = sample.get("id", "")
            # 查找照片在导入包中对应的 incoming 样机 ID
            inc_sid = target_to_incoming_sample.get(target_sid, target_sid)
            for photo in sample.get("photos") or []:
                photo_id = photo.get("id", "")
                # 原图：用 relativePath 获取真实文件名（含扩展名）
                rel = photo.get("relativePath", "")
                if rel:
                    fn = Path(rel).name
                    asset_src = tmp_dir / "assets" / "samples" / inc_sid / "photos" / fn
                    if asset_src.is_file():
                        dest_dir = SAMPLE_DATA_DIR / target_sid / "photos"
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        dest_path = dest_dir / fn
                        if not dest_path.exists():
                            shutil.copy2(asset_src, dest_path)
                            stats["photosAdded"] += 1
                        # 重写 4 个路径字段，全部基于 target_sid
                        photo["relativePath"] = f"samples/{target_sid}/photos/{fn}"
                        photo["url"] = f"/api/samples/{target_sid}/photos/{photo_id}"
                    else:
                        # 文件缺失：清除路径引用避免 404
                        photo["url"] = ""
                        photo["relativePath"] = ""
                else:
                    photo["url"] = ""
                    photo["relativePath"] = ""
                # 缩略图：用 thumbRelativePath
                thumb_rel = photo.get("thumbRelativePath", "")
                if thumb_rel:
                    thumb_fn = Path(thumb_rel).name
                    thumb_src = tmp_dir / "assets" / "samples" / inc_sid / "photos" / thumb_fn
                    if thumb_src.is_file():
                        dest_dir = SAMPLE_DATA_DIR / target_sid / "photos"
                        dest_dir.mkdir(parents=True, exist_ok=True)
                        thumb_dest = dest_dir / thumb_fn
                        if not thumb_dest.exists():
                            shutil.copy2(thumb_src, thumb_dest)
                        # 重写缩略图路径
                        photo["thumbRelativePath"] = f"samples/{target_sid}/photos/{thumb_fn}"
                        photo["thumbUrl"] = url_for_asset(target_sid, thumbnail_asset_id(photo_id))
                    else:
                        photo["thumbUrl"] = ""
                        photo["thumbRelativePath"] = ""
                else:
                    photo["thumbUrl"] = ""
                    photo["thumbRelativePath"] = ""

    # ── 重新生成样机数据，同步到 SQLite ──
    # 将 categories dict 转回 list
    current_data["sampleLibrary"]["categories"] = list(curr_categories.values())
    current_data["projects"] = list(curr_projects.values())

    # ── 统一 ID 重映射：所有交叉引用经映射表重写 ──
    _apply_id_maps(current_data, project_id_map, stage_id_map, task_id_map, sample_id_map)

    import_remark = f"导入数据包 (deployment={source_manifest.get('sourceDeploymentId','?')})"
    ok, resp = save_state(current_data, preview_revision, "import-bundle", remark=import_remark, user="数据导入")

    if not ok:
        _cleanup_preview_temp(preview_id)
        del _IMPORT_PREVIEWS[preview_id]
        return {"ok": False, "error": resp.get("error", "写入失败"), "status": resp.get("status", 500)}

    _cleanup_preview_temp(preview_id)
    del _IMPORT_PREVIEWS[preview_id]

    return {"ok": True, "stats": stats, "newRevision": resp.get("revision", 0), "updated_at": resp.get("updated_at", "")}


def _find_incoming_stage(incoming_projects_by_id: dict, stage_id: str) -> dict | None:
    """在导入数据中查找指定 ID 的 stage"""
    for proj in incoming_projects_by_id.values():
        for stage in (proj.get("stages") or []):
            if stage.get("id") == stage_id:
                return stage
    return None


def _find_incoming_task(incoming_projects_by_id: dict, task_id: str) -> dict | None:
    """在导入数据中查找指定 ID 的 task"""
    for proj in incoming_projects_by_id.values():
        for stage in (proj.get("stages") or []):
            for task in (stage.get("tasks") or []):
                if task.get("id") == task_id:
                    return task
    return None


def _apply_id_maps(data: dict, project_id_map: dict, stage_id_map: dict,
                   task_id_map: dict, sample_id_map: dict) -> None:
    """统一重映射所有交叉引用 ID（传入的 data 原地修改）"""
    # 1. 项目：重映射 stage/task 中的引用
    for proj in data.get("projects") or []:
        for stage in proj.get("stages") or []:
            for task in stage.get("tasks") or []:
                # 任务 sampleIds 经 sample_id_map 重映射
                if task.get("sampleIds"):
                    task["sampleIds"] = [sample_id_map.get(sid, sid) for sid in task["sampleIds"]]
                # 任务日志
                for log in task.get("logs") or []:
                    _remap_log_ids(log, project_id_map, stage_id_map, task_id_map, sample_id_map)
                # removedSampleRecords
                for rec in task.get("removedSampleRecords") or []:
                    old_sid = rec.get("sampleId")
                    if old_sid and old_sid in sample_id_map:
                        rec["sampleId"] = sample_id_map[old_sid]
                # sampleFaultRecords
                for rec in task.get("sampleFaultRecords") or []:
                    old_sid = rec.get("sampleId")
                    if old_sid and old_sid in sample_id_map:
                        rec["sampleId"] = sample_id_map[old_sid]

    # 2. 样机：重映射占用字段
    for cat in (data.get("sampleLibrary") or {}).get("categories") or []:
        for sample in cat.get("samples") or []:
            cp = sample.get("currentProjectId")
            if cp and cp in project_id_map:
                sample["currentProjectId"] = project_id_map[cp]
            cs = sample.get("currentStageId")
            if cs and cs in stage_id_map:
                sample["currentStageId"] = stage_id_map[cs]
            ct = sample.get("currentTaskId")
            if ct and ct in task_id_map:
                sample["currentTaskId"] = task_id_map[ct]


def _remap_log_ids(log: dict, project_id_map: dict, stage_id_map: dict,
                   task_id_map: dict, sample_id_map: dict) -> None:
    """重映射单条日志中的 ID 引用"""
    for field, id_map in [("sampleId", sample_id_map), ("projectId", project_id_map),
                           ("stageId", stage_id_map), ("taskId", task_id_map)]:
        old_val = log.get(field)
        if old_val and old_val in id_map:
            log[field] = id_map[old_val]


def _merge_project_sub_data(target: dict, source: dict) -> None:
    """将 source 项目的阶段/任务追加合并到 target 项目（不覆盖主字段）"""
    target_stages = {s["id"]: s for s in (target.get("stages") or [])}
    for stage in source.get("stages") or []:
        sid = stage.get("id", "")
        if sid and sid in target_stages:
            # 已存在阶段：合并任务
            target_tasks = {t["id"]: t for t in (target_stages[sid].get("tasks") or [])}
            for task in stage.get("tasks") or []:
                tid = task.get("id", "")
                if tid and tid not in target_tasks:
                    target_stages[sid].setdefault("tasks", []).append(copy.deepcopy(task))
        else:
            # 新阶段
            target.setdefault("stages", []).append(copy.deepcopy(stage))
    # 合并 members 和 locations（去重）
    existing_members = {(m.get("employeeNo"), m.get("name")) for m in (target.get("members") or [])}
    for m in source.get("members") or []:
        key = (m.get("employeeNo"), m.get("name"))
        if key not in existing_members:
            target.setdefault("members", []).append(copy.deepcopy(m))
            existing_members.add(key)
    existing_locs = set(target.get("locations") or [])
    for loc in source.get("locations") or []:
        if loc not in existing_locs:
            target.setdefault("locations", []).append(loc)
            existing_locs.add(loc)

FINISHED_TASK_STATUSES = {"正常完成", "异常终止"}


def detect_sample_occupancy_conflicts(data: dict) -> list[dict]:
    """C1：检测同一样机被多个未完成任务占用的冲突。

    未完成任务定义：未被标记 archived/completed，且 status 不在 FINISHED_TASK_STATUSES，
    且 sampleIds 非空。返回冲突列表，每项含 sampleId 与占用它的任务列表。
    无冲突返回空列表。
    """
    if not isinstance(data, dict):
        return []
    occupancy: dict[str, list[dict]] = defaultdict(list)
    for project in data.get("projects", []) or []:
        if not isinstance(project, dict):
            continue
        for stage in project.get("stages", []) or []:
            if not isinstance(stage, dict):
                continue
            for task in stage.get("tasks", []) or []:
                if not isinstance(task, dict):
                    continue
                if task.get("archived") or task.get("completed"):
                    continue
                status = str(task.get("status") or "").strip()
                if status in FINISHED_TASK_STATUSES:
                    continue
                sample_ids = task.get("sampleIds") or []
                if not isinstance(sample_ids, list):
                    continue
                for sid in sample_ids:
                    sid = str(sid)
                    if not sid:
                        continue
                    occupancy[sid].append({
                        "taskId": str(task.get("id") or ""),
                        "projectId": str(project.get("id") or ""),
                        "stageId": str(stage.get("id") or ""),
                        "testItem": str(task.get("testItem") or ""),
                        "status": status,
                    })
    conflicts = []
    for sid, tasks in occupancy.items():
        if len(tasks) > 1:
            conflicts.append({"sampleId": sid, "tasks": tasks})
    return conflicts


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

            # C1：并发样机占用校验——同一样机不能被多个未完成任务同时占用
            conflict = detect_sample_occupancy_conflicts(new_data)
            if conflict:
                return False, {
                    "status": 409,
                    "error_code": "SAMPLE_OCCUPANCY_CONFLICT",
                    "error": "样机占用冲突：同一样机被多个未完成任务占用，已拒绝保存。",
                    "conflicts": conflict,
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

    # ---- 静态文件白名单 ----
    ALLOWED_STATIC_PREFIXES = ("/js/", "/css/", "/templates/")
    FORBIDDEN_SEGMENT_PREFIXES = ("data", "backups", ".git", ".claude", "docs")
    FORBIDDEN_EXTENSIONS = {".sqlite", ".db", ".py", ".bat", ".ps1", ".md", ".json", ".log", ".zip"}

    @staticmethod
    def _is_public_static_path(path: str) -> bool:
        """只允许前端运行必需资源被访问。"""
        # 1. 路径白名单前缀
        if not any(path.startswith(p) for p in Handler.ALLOWED_STATIC_PREFIXES):
            return False
        # 2. 拒绝路径片段以 "." 开头（隐藏文件/目录 + 路径穿越 ".."）
        parts = path.lstrip("/").split("/")
        if any(p.startswith(".") for p in parts):
            return False
        # 3. 拒绝敏感顶级目录名
        if parts and parts[0] in Handler.FORBIDDEN_SEGMENT_PREFIXES:
            return False
        # 4. 拒绝危险后缀
        if Path(path).suffix.lower() in Handler.FORBIDDEN_EXTENSIONS:
            return False
        return True

    def do_GET(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)

        if path == "/api/health":
            self._send_json({"ok": True, "version": APP_VERSION, "time": now_iso(), "data_dir": str(DATA_DIR), "deploymentId": load_deployment_id()})
            return

        if path == "/api/export-bundle":
            try:
                zip_bytes, filename = build_export_bundle()
                self.send_response(200)
                self.send_header("Content-Type", "application/zip")
                self.send_header("Content-Disposition", f'attachment; filename="{filename}"')
                self.send_header("Content-Length", str(len(zip_bytes)))
                self.send_header("Cache-Control", "no-cache")
                self.end_headers()
                self.wfile.write(zip_bytes)
            except Exception as e:
                traceback.print_exc()
                self._send_json({"ok": False, "error": str(e), "errorCode": "EXPORT_FAILED"}, 500)
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
                            WHERE sample_id = ? AND id = ? AND kind IN ('photo', 'photo_thumb') AND deleted_at IS NULL
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

        # 静态文件服务 — 白名单模式，禁止访问敏感路径
        if not self._is_public_static_path(path):
            self._send_json({"ok": False, "error": "禁止访问"}, 403)
            return

        rel = path.lstrip("/")
        target = (ROOT_DIR / rel).resolve()
        # 路径穿越兜底检查（即使白名单通过也要防）
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
        path = unquote(parsed.path)

        if path == "/api/import-bundle/preview":
            try:
                result = analyze_import_bundle(self.headers, self._read_body())
                self._send_json({"ok": True, **result})
            except ValueError as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/import-bundle/commit":
            try:
                payload = json.loads(self._read_body(max_bytes=MAX_UPLOAD_BYTES).decode("utf-8"))
                result = commit_import_bundle(payload)
                if result.get("status"):
                    self._send_json(result, result["status"])
                else:
                    self._send_json({"ok": True, **result})
            except ValueError as e:
                self._send_json({"ok": False, "error": str(e)}, 400)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        route = self._sample_photo_route(unquote(parsed.path))
        if not route or route[1] is not None:
            self._send_json({"ok": False, "error": "Not Found"}, 404)
            return

        sample_id, _ = route
        try:
            fields, files = parse_multipart(self.headers, self._read_body())
            image_files = [f for f in files if f["field"] in ("photos", "photo", "file")]
            thumb_files = {}
            for f in files:
                m = re.match(r"^thumb_(\d+)$", str(f.get("field") or ""))
                if m:
                    thumb_files[int(m.group(1))] = f
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
                    for idx, file_item in enumerate(image_files):
                        meta = store_asset_bytes(
                            conn,
                            sample_id,
                            file_item["content"],
                            file_item["filename"],
                            file_item["mime_type"],
                            uploaded_by=self.client_address[0],
                        )
                        thumb_item = thumb_files.get(idx)
                        if thumb_item:
                            thumb_meta = store_thumbnail_bytes(
                                conn,
                                sample_id,
                                meta["id"],
                                thumb_item["content"],
                                thumb_item["filename"],
                                thumb_item["mime_type"],
                                uploaded_at=meta.get("uploadedAt"),
                                uploaded_by=self.client_address[0],
                            )
                            attach_thumbnail_meta(meta, thumb_meta)
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
                    asset_rows = conn.execute(
                        """
                        SELECT relative_path FROM sample_assets
                        WHERE sample_id = ? AND id IN (?, ?) AND kind IN ('photo', 'photo_thumb') AND deleted_at IS NULL
                        """,
                        (sample_id, photo_id, thumbnail_asset_id(photo_id)),
                    ).fetchall()
                    for asset in asset_rows:
                        try:
                            target = path_inside_data(asset["relative_path"])
                            if target.is_file():
                                target.unlink()
                        except Exception as e:
                            print(f"[WARN] 删除照片文件失败：{e}")
                    conn.execute(
                        """
                        UPDATE sample_assets SET deleted_at = ?
                        WHERE sample_id = ? AND id IN (?, ?) AND kind IN ('photo', 'photo_thumb')
                        """,
                        (now_iso(), sample_id, photo_id, thumbnail_asset_id(photo_id)),
                    )
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
    parser = argparse.ArgumentParser(description="数字治理平台 V7 内网协同版服务器")
    parser.add_argument("--host", default="0.0.0.0", help="监听地址，默认 0.0.0.0")
    parser.add_argument("--port", type=int, default=9398, help="监听端口，默认 9398")
    args = parser.parse_args()

    init_db()

    httpd = ThreadingHTTPServer((args.host, args.port), Handler)
    print("=" * 70)
    print("数字治理平台 V7 内网协同版服务器已启动")
    print(f"根目录: {ROOT_DIR}")
    print(f"数据库: {DB_PATH}")
    print(f"样机文件目录: {SAMPLE_DATA_DIR}")
    print(f"备份目录: {BACKUP_DIR}")
    print(f"监听: http://localhost:{args.port}/")
    print("同事访问时请使用这台电脑的内网 IP，例如：http://10.31.118.61:9398/")
    print("停止服务：在此窗口按 Ctrl+C")
    print("=" * 70)

    try:
        httpd.serve_forever()
    except KeyboardInterrupt:
        print("\n服务器已停止。")


if __name__ == "__main__":
    main()
