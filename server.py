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
from urllib.parse import parse_qs, quote, unquote, unquote_to_bytes, urlparse


APP_VERSION = "7.1.0"
SERVER_VERSION = "TestChamberServer/7.1.0"
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


def ensure_table_column(conn: sqlite3.Connection, table: str, column: str, definition: str) -> None:
    existing = {str(row["name"]) for row in conn.execute(f"PRAGMA table_info({table})").fetchall()}
    if column not in existing:
        conn.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")


def backfill_query_state_columns(conn: sqlite3.Connection) -> None:
    task_rows = conn.execute(
        """
        SELECT id, status, data_json
        FROM project_tasks
        WHERE COALESCE(flow_status, '') = ''
        """
    ).fetchall()
    for row in task_rows:
        task = json_obj(row["data_json"], {}) or {}
        task["status"] = row["status"] or task.get("status") or ""
        conn.execute(
            "UPDATE project_tasks SET flow_status = ? WHERE id = ?",
            (task_flow_status(task), row["id"]),
        )

    sample_rows = conn.execute(
        """
        SELECT id, status, has_problem, effective_status, data_json
        FROM sample_records
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    for row in sample_rows:
        sample = json_obj(row["data_json"], {}) or {}
        sample["status"] = row["status"] or sample.get("status") or ""
        has_problem = 1 if sample_has_problem(sample) else 0
        effective_status = sample_effective_status(sample)
        if int(row["has_problem"] or 0) != has_problem or str(row["effective_status"] or "") != effective_status:
            conn.execute(
                "UPDATE sample_records SET has_problem = ?, effective_status = ? WHERE id = ?",
                (has_problem, effective_status, row["id"]),
            )


def backfill_sample_identity_columns(conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, data_json, board_sn, is_reassembled
        FROM sample_records
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        sample = json_obj(row["data_json"], {}) or {}
        board_sn = str(sample.get("boardSn") or "").strip()
        is_reassembled = 1 if sample_is_reassembled(sample) else 0
        if str(row["board_sn"] or "") != board_sn or int(row["is_reassembled"] or 0) != is_reassembled:
            conn.execute(
                "UPDATE sample_records SET board_sn = ?, is_reassembled = ? WHERE id = ?",
                (board_sn, is_reassembled, row["id"]),
            )


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
            board_sn TEXT,
            is_reassembled INTEGER NOT NULL DEFAULT 0,
            status TEXT,
            has_problem INTEGER NOT NULL DEFAULT 0,
            effective_status TEXT,
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
    ensure_table_column(conn, "sample_records", "has_problem", "INTEGER NOT NULL DEFAULT 0")
    ensure_table_column(conn, "sample_records", "effective_status", "TEXT")
    ensure_table_column(conn, "sample_records", "board_sn", "TEXT")
    ensure_table_column(conn, "sample_records", "is_reassembled", "INTEGER NOT NULL DEFAULT 0")
    backfill_sample_identity_columns(conn)
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category ON sample_records(category_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_sn ON sample_records(sn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_imei ON sample_records(imei)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_board_sn ON sample_records(board_sn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_identity_active ON sample_records(deleted_at, is_reassembled, sn, imei, board_sn)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_status ON sample_records(status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_active ON sample_records(category_id, deleted_at, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_created ON sample_records(category_id, deleted_at, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_effective_created ON sample_records(category_id, deleted_at, effective_status, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_problem_created ON sample_records(category_id, deleted_at, has_problem, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_owner_created ON sample_records(category_id, deleted_at, owner, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_category_borrower_created ON sample_records(category_id, deleted_at, borrower, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_owner ON sample_records(owner)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_sample_records_borrower ON sample_records(borrower)")
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
            flow_status TEXT,
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
    ensure_table_column(conn, "project_tasks", "flow_status", "TEXT")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage ON project_tasks(stage_id, deleted_at, status)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_progress ON project_tasks(progress_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_project ON project_tasks(project_id, deleted_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_sku ON project_tasks(stage_id, deleted_at, sku_index)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_owner ON project_tasks(stage_id, deleted_at, owner)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_updated ON project_tasks(stage_id, deleted_at, updated_at)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_created ON project_tasks(stage_id, deleted_at, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_flow_created ON project_tasks(stage_id, deleted_at, flow_status, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_stage_sku_created ON project_tasks(stage_id, deleted_at, sku_index, created_at, id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_tasks_project_created ON project_tasks(project_id, deleted_at, created_at, id)")
    conn.execute(
        """
        CREATE TABLE IF NOT EXISTS project_task_samples (
            task_id TEXT NOT NULL,
            sample_id TEXT NOT NULL,
            project_id TEXT NOT NULL,
            stage_id TEXT NOT NULL,
            test_item TEXT,
            status TEXT,
            flow_status TEXT,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(task_id, sample_id),
            FOREIGN KEY(task_id) REFERENCES project_tasks(id)
        )
        """
    )
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_task_samples_sample ON project_task_samples(sample_id, flow_status, task_id)")
    conn.execute("CREATE INDEX IF NOT EXISTS idx_project_task_samples_task ON project_task_samples(task_id)")
    backfill_project_task_samples(conn)
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
    conn.execute("CREATE INDEX IF NOT EXISTS idx_task_logs_stage ON task_logs(stage_id, time)")
    backfill_query_state_columns(conn)


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
                (id, category_id, sample_no, sn, imei, board_sn, is_reassembled, status, has_problem, effective_status, location, owner, borrower, data_json, created_at, updated_at, deleted_at)
                VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                ON CONFLICT(id) DO UPDATE SET
                    category_id = excluded.category_id,
                    sample_no = excluded.sample_no,
                    sn = excluded.sn,
                    imei = excluded.imei,
                    board_sn = excluded.board_sn,
                    is_reassembled = excluded.is_reassembled,
                    status = excluded.status,
                    has_problem = excluded.has_problem,
                    effective_status = excluded.effective_status,
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
                    str(sample.get("boardSn") or ""),
                    1 if sample_is_reassembled(sample) else 0,
                    str(sample.get("status") or ""),
                    1 if sample_has_problem(sample) else 0,
                    sample_effective_status(sample),
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


def load_sample_photo_counts(conn: sqlite3.Connection) -> dict[str, int]:
    rows = conn.execute(
        """
        SELECT sample_id, COUNT(*) AS count
        FROM sample_assets
        WHERE kind = 'photo' AND deleted_at IS NULL
        GROUP BY sample_id
        """
    ).fetchall()
    return {str(row["sample_id"]): int(row["count"] or 0) for row in rows}


def load_sample_events(conn: sqlite3.Connection, sample_id: str) -> list[dict]:
    rows = conn.execute(
        """
        SELECT data_json
        FROM sample_events
        WHERE sample_id = ?
        ORDER BY time, id
        """,
        (sample_id,),
    ).fetchall()
    logs = []
    for row in rows:
        log = json_obj(row["data_json"], None)
        if isinstance(log, dict):
            logs.append(log)
    return logs


def load_sample_library(conn: sqlite3.Connection, *, include_photos: bool = True, include_logs: bool = True) -> dict:
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
        SELECT id, category_id, sample_no, sn, imei, board_sn, is_reassembled, status, location, owner, borrower, data_json
        FROM sample_records
        WHERE deleted_at IS NULL
        ORDER BY created_at, id
        """
    ).fetchall()
    photo_counts = load_sample_photo_counts(conn) if not include_photos else {}
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
            "boardSn": row["board_sn"] or sample.get("boardSn") or "",
            "isReassembled": bool(row["is_reassembled"]) if row["is_reassembled"] is not None else sample_is_reassembled(sample),
            "status": row["status"] or sample.get("status") or "",
            "location": row["location"] or sample.get("location") or "",
            "owner": row["owner"] or sample.get("owner") or "",
            "borrower": row["borrower"] or sample.get("borrower") or "",
        })
        if include_photos:
            sample["photos"] = load_sample_photos(conn, row["id"])
            sample["photoCount"] = len(sample["photos"])
            sample["photosLoaded"] = True
        else:
            sample["photos"] = []
            sample["photoCount"] = photo_counts.get(str(row["id"]), 0)
            sample["photosLoaded"] = False
        category_map.get(row["category_id"], {}).setdefault("samples", []).append(sample)

    logs = []
    if include_logs:
        event_rows = conn.execute("SELECT data_json FROM sample_events ORDER BY time, id").fetchall()
        for row in event_rows:
            log = json_obj(row["data_json"], None)
            if isinstance(log, dict):
                logs.append(log)
    return {
        "categories": categories,
        "logs": logs,
        "photosExternalized": not include_photos,
        "eventsExternalized": not include_logs,
    }


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
                    (id, project_id, stage_id, progress_id, category, test_item, sku_index, status, flow_status, owner,
                     sample_ids_json, data_json, created_at, updated_at, completed_at, deleted_at)
                    VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
                    ON CONFLICT(id) DO UPDATE SET
                        project_id = excluded.project_id,
                        stage_id = excluded.stage_id,
                        progress_id = excluded.progress_id,
                        category = excluded.category,
                        test_item = excluded.test_item,
                        sku_index = excluded.sku_index,
                        status = excluded.status,
                        flow_status = excluded.flow_status,
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
                        task_flow_status(task),
                        str(task.get("owner") or ""),
                        json_dumps(sample_ids),
                        json_dumps(task_json),
                        str(task.get("createdAt") or ts),
                        str(task.get("updatedAt") or ts),
                        str(task.get("completedAt") or task.get("endDate") or ""),
                    ),
                )
                replace_task_sample_links(conn, task_id, project_id, stage_id, task, sample_ids)
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
        conn.execute(f"DELETE FROM project_task_samples WHERE task_id NOT IN ({placeholders})", active_task_ids)
        conn.execute(f"DELETE FROM project_tasks WHERE id NOT IN ({placeholders})", active_task_ids)
    else:
        conn.execute("DELETE FROM task_logs")
        conn.execute("DELETE FROM project_task_samples")
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


def load_project_detail(conn: sqlite3.Connection, project_id: str, *, include_tasks: bool = False) -> dict | None:
    project_row = conn.execute(
        """
        SELECT id, name, code, owner, data_json
        FROM project_records
        WHERE id = ? AND deleted_at IS NULL
        """,
        (project_id,),
    ).fetchone()
    if not project_row:
        return None

    project = json_obj(project_row["data_json"], {}) or {}
    project.update({
        "id": project_row["id"],
        "name": project_row["name"] or project.get("name") or "",
        "code": project_row["code"] or project.get("code") or "",
        "owner": project_row["owner"] or project.get("owner") or "",
        "stages": [],
    })

    stage_rows = conn.execute(
        """
        SELECT id, project_id, name, data_json
        FROM project_stages
        WHERE project_id = ? AND deleted_at IS NULL
        ORDER BY sort_order, id
        """,
        (project_id,),
    ).fetchall()
    stage_map: dict[str, dict] = {}
    for row in stage_rows:
        stage = json_obj(row["data_json"], {}) or {}
        stage.update({
            "id": row["id"],
            "projectId": row["project_id"],
            "name": row["name"] or stage.get("name") or "",
            "tasks": [],
        })
        project.setdefault("stages", []).append(stage)
        stage_map[row["id"]] = stage

    if stage_map:
        for stage in stage_map.values():
            stage["statusCounts"] = {}
            stage["taskCount"] = 0
            stage["ownerNames"] = []

        status_rows = conn.execute(
            """
            SELECT stage_id, COALESCE(flow_status, '待下发') AS flow_status, COUNT(*) AS count
            FROM project_tasks
            WHERE project_id = ? AND deleted_at IS NULL
            GROUP BY stage_id, flow_status
            """,
            (project_id,),
        ).fetchall()
        for row in status_rows:
            stage = stage_map.get(row["stage_id"])
            if not stage:
                continue
            counts = stage.setdefault("statusCounts", {})
            count = int(row["count"] or 0)
            counts[str(row["flow_status"] or "待下发")] = count
            stage["taskCount"] = int(stage.get("taskCount") or 0) + count

        owner_rows = conn.execute(
            """
            SELECT stage_id, owner
            FROM project_tasks
            WHERE project_id = ? AND deleted_at IS NULL AND COALESCE(owner, '') <> ''
            GROUP BY stage_id, owner
            ORDER BY owner
            """,
            (project_id,),
        ).fetchall()
        for row in owner_rows:
            stage = stage_map.get(row["stage_id"])
            if not stage:
                continue
            stage.setdefault("ownerNames", []).append(str(row["owner"] or ""))

    if not include_tasks or not stage_map:
        return project

    task_rows = conn.execute(
        """
        SELECT id, project_id, stage_id, progress_id, category, test_item, sku_index, status, owner,
               sample_ids_json, data_json, completed_at
        FROM project_tasks
        WHERE project_id = ? AND deleted_at IS NULL
        ORDER BY created_at, id
        """,
        (project_id,),
    ).fetchall()
    task_ids = [str(row["id"]) for row in task_rows]
    logs_by_task = load_task_logs_for(conn, task_ids)
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
    return project


def first_query_value(query: dict[str, list[str]], name: str, default: str = "") -> str:
    values = query.get(name)
    if not values:
        return default
    return str(values[0] if values[0] is not None else default)


def parse_page_params(query: dict[str, list[str]], *, default_size: int = 100, max_size: int = 500) -> tuple[int, int]:
    page = to_int(first_query_value(query, "page", "1"), 1)
    page_size = to_int(first_query_value(query, "pageSize", str(default_size)), default_size)
    page = max(1, page)
    page_size = max(1, min(max_size, page_size))
    return page, page_size


def paginate_list(items: list[dict], page: int, page_size: int) -> tuple[list[dict], dict]:
    total = len(items)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    start = (page - 1) * page_size
    end = start + page_size
    return items[start:end], {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
    }


def task_flow_status(task: dict) -> str:
    status = str(task.get("status") or "").strip()
    if status in ("异常完成", "异常终止", "失败", "Fail"):
        return "异常终止"
    if task.get("completed") or status in ("正常完成", "已完成", "通过", "Pass"):
        return "正常完成"
    if status in ("阻塞", "阻塞中"):
        return "阻塞中"
    if status in ("进行中", "Testing"):
        return "进行中"
    return "待下发"


def replace_task_sample_links(
    conn: sqlite3.Connection,
    task_id: str,
    project_id: str,
    stage_id: str,
    task: dict,
    sample_ids: list[str] | None = None,
) -> None:
    task_id = str(task_id or "")
    if not task_id:
        return
    conn.execute("DELETE FROM project_task_samples WHERE task_id = ?", (task_id,))
    ids = sample_ids if sample_ids is not None else [str(x) for x in (task.get("sampleIds") or [])]
    seen: set[str] = set()
    ts = str(task.get("updatedAt") or now_iso())
    flow_status = task_flow_status(task)
    for sample_id in ids:
        sid = str(sample_id or "").strip()
        if not sid or sid in seen:
            continue
        seen.add(sid)
        conn.execute(
            """
            INSERT INTO project_task_samples
            (task_id, sample_id, project_id, stage_id, test_item, status, flow_status, updated_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                task_id,
                sid,
                str(project_id or ""),
                str(stage_id or ""),
                str(task.get("testItem") or ""),
                str(task.get("status") or ""),
                flow_status,
                ts,
            ),
        )


def backfill_project_task_samples(conn: sqlite3.Connection) -> None:
    existing = conn.execute("SELECT COUNT(*) AS count FROM project_task_samples").fetchone()
    if int(existing["count"] if existing else 0) > 0:
        return
    rows = conn.execute(
        """
        SELECT id, project_id, stage_id, test_item, status, sample_ids_json, data_json
        FROM project_tasks
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        task = json_obj(row["data_json"], {}) or {}
        task["id"] = row["id"]
        task["projectId"] = row["project_id"]
        task["stageId"] = row["stage_id"]
        task["testItem"] = row["test_item"] or task.get("testItem") or ""
        task["status"] = row["status"] or task.get("status") or ""
        sample_ids = json_obj(row["sample_ids_json"], [])
        if not isinstance(sample_ids, list):
            sample_ids = []
        replace_task_sample_links(conn, str(row["id"] or ""), str(row["project_id"] or ""), str(row["stage_id"] or ""), task, [str(x) for x in sample_ids])


def person_name_from_text(text: object) -> str:
    raw = str(text or "").strip()
    if "/" in raw:
        return raw.split("/", 1)[0].strip()
    return raw


def task_search_text(task: dict, progress: dict | None = None) -> str:
    issue = task.get("issueRecord") if isinstance(task.get("issueRecord"), dict) else {}
    chunks = [
        task.get("category"),
        task.get("testItem"),
        task.get("owner"),
        issue.get("dtsNo"),
        issue.get("issueNote"),
        task.get("result"),
        task.get("resultSummary"),
        task.get("completionType"),
    ]
    if progress:
        chunks.extend([progress.get("category"), progress.get("testItem")])
    for upload in task.get("resultUploads") or []:
        if isinstance(upload, dict):
            chunks.extend([upload.get("reason"), upload.get("summary"), upload.get("result")])
    for fault in task.get("sampleFaultRecords") or []:
        if isinstance(fault, dict):
            chunks.extend([fault.get("problem"), fault.get("sampleNo"), fault.get("sn"), fault.get("imei")])
    return " ".join(str(x or "") for x in chunks).lower()


def task_matches_query(task: dict, progress: dict | None, query: dict[str, list[str]]) -> bool:
    sku = first_query_value(query, "sku", "")
    sku_index = str(task.get("skuIndex") or (progress or {}).get("skuIndex") or "")
    if sku and sku != sku_index:
        return False

    flow_status = first_query_value(query, "flowStatus", "")
    if flow_status and task_flow_status(task) != flow_status:
        return False

    owner_name = first_query_value(query, "ownerName", "")
    if owner_name and person_name_from_text(task.get("owner")) != owner_name:
        return False

    category_kw = first_query_value(query, "categoryKeyword", "").strip().lower()
    category = str(task.get("category") or (progress or {}).get("category") or "").lower()
    if category_kw and category_kw not in category:
        return False

    case_kw = first_query_value(query, "caseKeyword", "").strip().lower()
    test_item = str(task.get("testItem") or (progress or {}).get("testItem") or "").lower()
    if case_kw and case_kw not in test_item:
        return False

    dts_kw = first_query_value(query, "dtsKeyword", "").strip().lower()
    issue = task.get("issueRecord") if isinstance(task.get("issueRecord"), dict) else {}
    if dts_kw and dts_kw not in str(issue.get("dtsNo") or "").lower():
        return False

    result_kw = first_query_value(query, "resultKeyword", "").strip().lower()
    if result_kw and result_kw not in task_search_text(task, progress):
        return False

    return True


def query_value_present(query: dict[str, list[str]], name: str) -> bool:
    return bool(first_query_value(query, name, "").strip())


def task_query_requires_python_scan(query: dict[str, list[str]]) -> bool:
    return any(query_value_present(query, key) for key in ("categoryKeyword", "caseKeyword", "dtsKeyword", "resultKeyword"))


def task_sql_filter_parts(stage_id: str, query: dict[str, list[str]], *, include_flow_status: bool = True) -> tuple[list[str], list[object]]:
    where = ["stage_id = ?", "deleted_at IS NULL"]
    args: list[object] = [stage_id]
    sku = first_query_value(query, "sku", "")
    if sku:
        where.append("sku_index = ?")
        args.append(to_int(sku, 0))
    owner_name = first_query_value(query, "ownerName", "").strip()
    if owner_name:
        where.append("(owner = ? OR owner LIKE ?)")
        args.extend([owner_name, f"{owner_name}/%"])
    if include_flow_status:
        flow_status = first_query_value(query, "flowStatus", "").strip()
        if flow_status:
            where.append("flow_status = ?")
            args.append(flow_status)
    return where, args


def task_from_db_row(row: sqlite3.Row) -> dict:
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
    })
    if row["completed_at"] and not task.get("completedAt"):
        task["completedAt"] = row["completed_at"]
    return task


def load_task_logs_for(conn: sqlite3.Connection, task_ids: list[str]) -> dict[str, list[dict]]:
    if not task_ids:
        return {}
    placeholders = ",".join("?" for _ in task_ids)
    rows = conn.execute(
        f"""
        SELECT task_id, data_json
        FROM task_logs
        WHERE task_id IN ({placeholders})
        ORDER BY time, id
        """,
        task_ids,
    ).fetchall()
    logs_by_task: dict[str, list[dict]] = {}
    for row in rows:
        log = json_obj(row["data_json"], None)
        if isinstance(log, dict):
            logs_by_task.setdefault(row["task_id"], []).append(log)
    return logs_by_task


def list_stage_tasks_page(conn: sqlite3.Connection, stage_id: str, query: dict[str, list[str]]) -> dict:
    page, page_size = parse_page_params(query, default_size=100, max_size=500)
    stage_row = conn.execute(
        """
        SELECT id, project_id, name, data_json
        FROM project_stages
        WHERE id = ? AND deleted_at IS NULL
        """,
        (stage_id,),
    ).fetchone()
    if not stage_row:
        raise KeyError("阶段不存在")

    stage = json_obj(stage_row["data_json"], {}) or {}
    progress_items = stage.get("progress") if isinstance(stage.get("progress"), list) else []
    progress_by_id = {str(p.get("id")): p for p in progress_items if isinstance(p, dict) and p.get("id")}

    if not task_query_requires_python_scan(query):
        where, args = task_sql_filter_parts(stage_id, query, include_flow_status=True)
        base_where, base_args = task_sql_filter_parts(stage_id, query, include_flow_status=False)
        total = int(conn.execute(
            f"SELECT COUNT(*) AS count FROM project_tasks WHERE {' AND '.join(where)}",
            args,
        ).fetchone()["count"] or 0)
        base_total = int(conn.execute(
            f"SELECT COUNT(*) AS count FROM project_tasks WHERE {' AND '.join(base_where)}",
            base_args,
        ).fetchone()["count"] or 0)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(max(1, page), total_pages)
        offset = (page - 1) * page_size

        status_rows = conn.execute(
            f"""
            SELECT COALESCE(flow_status, '待下发') AS flow_status, COUNT(*) AS count
            FROM project_tasks
            WHERE {" AND ".join(base_where)}
            GROUP BY flow_status
            """,
            base_args,
        ).fetchall()
        status_counts = {str(row["flow_status"] or "待下发"): int(row["count"] or 0) for row in status_rows}
        owner_rows = conn.execute(
            f"""
            SELECT owner
            FROM project_tasks
            WHERE {" AND ".join(base_where)} AND COALESCE(owner, '') <> ''
            GROUP BY owner
            ORDER BY owner
            """,
            base_args,
        ).fetchall()
        owner_names = [str(row["owner"] or "") for row in owner_rows if str(row["owner"] or "").strip()]

        rows = conn.execute(
            f"""
            SELECT id, project_id, stage_id, progress_id, category, test_item, sku_index, status, flow_status, owner,
                   sample_ids_json, data_json, completed_at
            FROM project_tasks
            WHERE {" AND ".join(where)}
            ORDER BY created_at, id
            LIMIT ? OFFSET ?
            """,
            [*args, page_size, offset],
        ).fetchall()

        page_rows: list[dict] = []
        for idx, row in enumerate(rows):
            task = task_from_db_row(row)
            progress = progress_by_id.get(str(task.get("progressId") or ""))
            page_rows.append({
                "key": task.get("id") or f"task_{idx}",
                "task": task,
                "progress": progress,
                "flowStatus": row["flow_status"] or task_flow_status(task),
            })

        logs_by_task = load_task_logs_for(conn, [str(row["task"].get("id")) for row in page_rows if row.get("task")])
        for row in page_rows:
            task = row.get("task") or {}
            task["logs"] = logs_by_task.get(str(task.get("id")), [])

        return {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
            "stage": {
                "id": stage_row["id"],
                "projectId": stage_row["project_id"],
                "name": stage_row["name"] or stage.get("name") or "",
            },
            "stats": {
                "totalInStage": base_total,
                "filtered": total,
                "statusCounts": status_counts,
                "ownerNames": owner_names,
            },
            "rows": page_rows,
        }

    where = ["stage_id = ?", "deleted_at IS NULL"]
    args: list[object] = [stage_id]
    sku = first_query_value(query, "sku", "")
    if sku:
        where.append("sku_index = ?")
        args.append(to_int(sku, 0))
    category_kw = first_query_value(query, "categoryKeyword", "").strip().lower()
    if category_kw:
        where.append("(LOWER(category) LIKE ? OR LOWER(data_json) LIKE ?)")
        like = f"%{category_kw}%"
        args.extend([like, like])
    case_kw = first_query_value(query, "caseKeyword", "").strip().lower()
    if case_kw:
        where.append("(LOWER(test_item) LIKE ? OR LOWER(data_json) LIKE ?)")
        like = f"%{case_kw}%"
        args.extend([like, like])
    owner_name = first_query_value(query, "ownerName", "").strip().lower()
    if owner_name:
        where.append("LOWER(owner) LIKE ?")
        args.append(f"%{owner_name}%")

    rows = conn.execute(
        f"""
        SELECT id, project_id, stage_id, progress_id, category, test_item, sku_index, status, owner,
               sample_ids_json, data_json, completed_at
        FROM project_tasks
        WHERE {" AND ".join(where)}
        ORDER BY created_at, id
        """,
        args,
    ).fetchall()

    all_rows: list[dict] = []
    status_counts: dict[str, int] = {}
    owner_names: set[str] = set()
    for idx, row in enumerate(rows):
        task = task_from_db_row(row)
        owner = str(task.get("owner") or "").strip()
        if owner:
            owner_names.add(owner)
        progress = progress_by_id.get(str(task.get("progressId") or ""))
        flow_status = task_flow_status(task)
        status_counts[flow_status] = status_counts.get(flow_status, 0) + 1
        if not task_matches_query(task, progress, query):
            continue
        all_rows.append({
            "key": task.get("id") or f"task_{idx}",
            "task": task,
            "progress": progress,
            "flowStatus": flow_status,
        })

    page_rows, meta = paginate_list(all_rows, page, page_size)
    logs_by_task = load_task_logs_for(conn, [str(row["task"].get("id")) for row in page_rows if row.get("task")])
    for row in page_rows:
        task = row.get("task") or {}
        task["logs"] = logs_by_task.get(str(task.get("id")), [])

    return {
        **meta,
        "stage": {
            "id": stage_row["id"],
            "projectId": stage_row["project_id"],
            "name": stage_row["name"] or stage.get("name") or "",
        },
        "stats": {
            "totalInStage": len(rows),
            "filtered": len(all_rows),
            "statusCounts": status_counts,
            "ownerNames": sorted(owner_names),
        },
        "rows": page_rows,
    }


def load_sample_photo_counts_for(conn: sqlite3.Connection, sample_ids: list[str]) -> dict[str, int]:
    if not sample_ids:
        return {}
    placeholders = ",".join("?" for _ in sample_ids)
    rows = conn.execute(
        f"""
        SELECT sample_id, COUNT(*) AS count
        FROM sample_assets
        WHERE kind = 'photo' AND deleted_at IS NULL AND sample_id IN ({placeholders})
        GROUP BY sample_id
        """,
        sample_ids,
    ).fetchall()
    return {str(row["sample_id"]): int(row["count"] or 0) for row in rows}


def sample_has_problem(sample: dict) -> bool:
    if sample.get("hasProblem") in (True, 1, "1"):
        return True
    for record in sample.get("problemRecords") or []:
        if isinstance(record, dict) and str(record.get("description") or "").strip():
            return True
        if isinstance(record, str) and record.strip():
            return True
    return False


def sample_is_reassembled(sample: dict) -> bool:
    raw = sample.get("isReassembled") if isinstance(sample, dict) else False
    if isinstance(raw, bool):
        return raw
    if isinstance(raw, (int, float)):
        return raw == 1
    text = str(raw or "").strip().lower()
    return text in {"是", "yes", "y", "true", "1", "重组", "reassembled"}


def sample_usage_status(sample: dict) -> str:
    raw = str(sample.get("status") or "").strip()
    aliases = {
        "已分配": "在位等待",
        "进入测试任务": "测试中",
        "已归还": "闲置",
        "借出": "取走分析",
        "已借出": "取走分析",
        "待维修": "闲置",
        "报废": "闲置",
        "故障": "闲置",
    }
    status = aliases.get(raw, raw or "闲置")
    return status if status in {"测试中", "闲置", "在位等待", "已退库", "取走分析"} else "闲置"


def sample_effective_status(sample: dict) -> str:
    return sample_usage_status(sample)


def sample_usage_status_sql_expr(column: str = "status") -> str:
    value = f"TRIM(COALESCE({column}, ''))"
    return f"""
        CASE
            WHEN {value} IN ('测试中', '闲置', '在位等待', '已退库', '取走分析') THEN {value}
            WHEN {value} IN ('已分配') THEN '在位等待'
            WHEN {value} IN ('进入测试任务') THEN '测试中'
            WHEN {value} IN ('借出', '已借出') THEN '取走分析'
            ELSE '闲置'
        END
    """


def sample_search_text(sample: dict) -> str:
    chunks = [
        sample.get("sampleNo"),
        sample.get("sn"),
        sample.get("imei"),
        sample.get("boardSn"),
        sample.get("model"),
        sample.get("config"),
        sample.get("tag"),
        sample.get("schemeNo"),
        sample.get("sourceStageName"),
        sample.get("sourceSkuName"),
        sample.get("notes"),
        sample.get("owner"),
        sample.get("borrower"),
        sample.get("location"),
    ]
    for record in sample.get("problemRecords") or []:
        if isinstance(record, dict):
            chunks.extend([record.get("description"), record.get("source"), record.get("taskLabel")])
        else:
            chunks.append(record)
    return " ".join(str(x or "") for x in chunks).lower()


def sample_matches_query(sample: dict, query: dict[str, list[str]]) -> bool:
    keyword = first_query_value(query, "keyword", "").strip().lower()
    if keyword and keyword not in sample_search_text(sample):
        return False
    status = first_query_value(query, "status", "")
    if status and sample_effective_status(sample) != status:
        return False
    problem_state = sample_problem_state(query)
    if problem_state == "fault" and not sample_has_problem(sample):
        return False
    if problem_state == "ok" and sample_has_problem(sample):
        return False
    owner = first_query_value(query, "owner", "")
    if owner and owner not in str(sample.get("owner") or ""):
        return False
    borrower = first_query_value(query, "borrower", "")
    if borrower and borrower not in str(sample.get("borrower") or ""):
        return False
    return True


def sample_query_requires_python_scan(query: dict[str, list[str]]) -> bool:
    return query_value_present(query, "keyword")


def sample_problem_state(query: dict[str, list[str]]) -> str:
    value = first_query_value(query, "problemState", "").strip().lower()
    if value in ("fault", "problem", "bad", "fail", "故障"):
        return "fault"
    if value in ("ok", "pass", "normal", "good", "无故障"):
        return "ok"
    return ""


def sample_sql_filter_parts(category_id: str, query: dict[str, list[str]], *, include_status: bool = True, include_problem: bool = True) -> tuple[list[str], list[object]]:
    where = ["category_id = ?", "deleted_at IS NULL"]
    args: list[object] = [category_id]
    if include_status:
        status = first_query_value(query, "status", "").strip()
        if status:
            where.append(f"{sample_usage_status_sql_expr()} = ?")
            args.append(status)
    if include_problem:
        problem_state = sample_problem_state(query)
        if problem_state == "fault":
            where.append("has_problem = 1")
        elif problem_state == "ok":
            where.append("has_problem = 0")
    owner = first_query_value(query, "owner", "").strip()
    if owner:
        where.append("owner LIKE ?")
        args.append(f"%{owner}%")
    borrower = first_query_value(query, "borrower", "").strip()
    if borrower:
        where.append("borrower LIKE ?")
        args.append(f"%{borrower}%")
    return where, args


def sample_from_db_row(row: sqlite3.Row) -> dict:
    sample = json_obj(row["data_json"], {}) or {}
    keys = set(row.keys())
    sample.update({
        "id": row["id"],
        "categoryId": row["category_id"],
        "sampleNo": row["sample_no"] or sample.get("sampleNo") or "",
        "sn": row["sn"] or sample.get("sn") or "",
        "imei": row["imei"] or sample.get("imei") or "",
        "boardSn": (row["board_sn"] if "board_sn" in keys else None) or sample.get("boardSn") or "",
        "isReassembled": bool(row["is_reassembled"]) if "is_reassembled" in keys and row["is_reassembled"] is not None else sample_is_reassembled(sample),
        "status": row["status"] or sample.get("status") or "",
        "location": row["location"] or sample.get("location") or "",
        "owner": row["owner"] or sample.get("owner") or "",
        "borrower": row["borrower"] or sample.get("borrower") or "",
        "photos": [],
        "photosLoaded": False,
    })
    if "effective_status" in keys:
        sample["effectiveStatus"] = sample_effective_status(sample)
    if "has_problem" in keys:
        sample["hasProblem"] = bool(row["has_problem"])
    return sample


def list_sample_categories_summary(conn: sqlite3.Connection) -> list[dict]:
    rows = conn.execute(
        """
        SELECT c.id, c.name, c.description, c.data_json, COUNT(r.id) AS sample_count
        FROM sample_categories c
        LEFT JOIN sample_records r ON r.category_id = c.id AND r.deleted_at IS NULL
        WHERE c.deleted_at IS NULL
        GROUP BY c.id
        ORDER BY c.sort_order, c.id
        """
    ).fetchall()
    usage_status_expr = sample_usage_status_sql_expr("status")
    status_rows = conn.execute(
        """
        SELECT category_id, {usage_status_expr} AS effective_status, COUNT(*) AS count
        FROM sample_records
        WHERE deleted_at IS NULL
        GROUP BY category_id, effective_status
        """.format(usage_status_expr=usage_status_expr)
    ).fetchall()
    status_by_category: dict[str, dict[str, int]] = {}
    for row in status_rows:
        status_by_category.setdefault(str(row["category_id"]), {})[str(row["effective_status"] or "闲置")] = int(row["count"] or 0)
    problem_rows = conn.execute(
        """
        SELECT category_id, has_problem, COUNT(*) AS count
        FROM sample_records
        WHERE deleted_at IS NULL
        GROUP BY category_id, has_problem
        """
    ).fetchall()
    problem_by_category: dict[str, dict[str, int]] = {}
    for row in problem_rows:
        key = "fault" if int(row["has_problem"] or 0) else "ok"
        problem_by_category.setdefault(str(row["category_id"]), {})[key] = int(row["count"] or 0)

    result = []
    for row in rows:
        cat = json_obj(row["data_json"], {}) or {}
        result.append({
            "id": row["id"],
            "name": row["name"] or cat.get("name") or "",
            "description": row["description"] or cat.get("description") or "",
            "sampleCount": int(row["sample_count"] or 0),
            "statusCounts": status_by_category.get(str(row["id"]), {}),
            "problemCounts": problem_by_category.get(str(row["id"]), {}),
        })
    return result


def list_samples_page(conn: sqlite3.Connection, category_id: str, query: dict[str, list[str]]) -> dict:
    page, page_size = parse_page_params(query, default_size=100, max_size=500)
    category_row = conn.execute(
        """
        SELECT id, name, description, data_json
        FROM sample_categories
        WHERE id = ? AND deleted_at IS NULL
        """,
        (category_id,),
    ).fetchone()
    if not category_row:
        raise KeyError("样机池不存在")

    if not sample_query_requires_python_scan(query):
        where, args = sample_sql_filter_parts(category_id, query, include_status=True)
        status_where, status_args = sample_sql_filter_parts(category_id, query, include_status=False)
        problem_where, problem_args = sample_sql_filter_parts(category_id, query, include_problem=False)
        total_in_category = int(conn.execute(
            "SELECT COUNT(*) AS count FROM sample_records WHERE category_id = ? AND deleted_at IS NULL",
            (category_id,),
        ).fetchone()["count"] or 0)
        total = int(conn.execute(
            f"SELECT COUNT(*) AS count FROM sample_records WHERE {' AND '.join(where)}",
            args,
        ).fetchone()["count"] or 0)
        total_pages = max(1, (total + page_size - 1) // page_size)
        page = min(max(1, page), total_pages)
        offset = (page - 1) * page_size

        usage_status_expr = sample_usage_status_sql_expr("status")
        status_rows = conn.execute(
            f"""
            SELECT {usage_status_expr} AS effective_status, COUNT(*) AS count
            FROM sample_records
            WHERE {" AND ".join(status_where)}
            GROUP BY effective_status
            """,
            status_args,
        ).fetchall()
        status_counts = {str(row["effective_status"] or "闲置"): int(row["count"] or 0) for row in status_rows}
        problem_rows = conn.execute(
            f"""
            SELECT has_problem, COUNT(*) AS count
            FROM sample_records
            WHERE {" AND ".join(problem_where)}
            GROUP BY has_problem
            """,
            problem_args,
        ).fetchall()
        problem_counts = {
            ("fault" if int(row["has_problem"] or 0) else "ok"): int(row["count"] or 0)
            for row in problem_rows
        }

        rows = conn.execute(
            f"""
            SELECT id, category_id, sample_no, sn, imei, board_sn, is_reassembled, status, has_problem, effective_status, location, owner, borrower, data_json
            FROM sample_records
            WHERE {" AND ".join(where)}
            ORDER BY created_at, id
            LIMIT ? OFFSET ?
            """,
            [*args, page_size, offset],
        ).fetchall()

        page_items = [sample_from_db_row(row) for row in rows]
        photo_counts = load_sample_photo_counts_for(conn, [str(item.get("id")) for item in page_items])
        for item in page_items:
            item["photoCount"] = photo_counts.get(str(item.get("id")), 0)

        cat = json_obj(category_row["data_json"], {}) or {}
        return {
            "page": page,
            "pageSize": page_size,
            "total": total,
            "totalPages": total_pages,
            "category": {
                "id": category_row["id"],
                "name": category_row["name"] or cat.get("name") or "",
                "description": category_row["description"] or cat.get("description") or "",
            },
            "stats": {
                "totalInCategory": total_in_category,
                "filtered": total,
                "statusCounts": status_counts,
                "problemCounts": problem_counts,
            },
            "items": page_items,
        }

    where = ["category_id = ?", "deleted_at IS NULL"]
    args: list[object] = [category_id]
    keyword = first_query_value(query, "keyword", "").strip().lower()
    if keyword:
        where.append(
            """
            (LOWER(sample_no) LIKE ? OR LOWER(sn) LIKE ? OR LOWER(imei) LIKE ?
             OR LOWER(owner) LIKE ? OR LOWER(borrower) LIKE ? OR LOWER(location) LIKE ?
             OR LOWER(data_json) LIKE ?)
            """
        )
        like = f"%{keyword}%"
        args.extend([like, like, like, like, like, like, like])
    owner = first_query_value(query, "owner", "").strip().lower()
    if owner:
        where.append("LOWER(owner) LIKE ?")
        args.append(f"%{owner}%")
    borrower = first_query_value(query, "borrower", "").strip().lower()
    if borrower:
        where.append("LOWER(borrower) LIKE ?")
        args.append(f"%{borrower}%")
    problem_state = sample_problem_state(query)
    if problem_state == "fault":
        where.append("has_problem = 1")
    elif problem_state == "ok":
        where.append("has_problem = 0")

    rows = conn.execute(
        f"""
        SELECT id, category_id, sample_no, sn, imei, board_sn, is_reassembled, status, has_problem, effective_status, location, owner, borrower, data_json
        FROM sample_records
        WHERE {" AND ".join(where)}
        ORDER BY created_at, id
        """,
        args,
    ).fetchall()

    all_items: list[dict] = []
    status_counts: dict[str, int] = {}
    problem_counts = {"ok": 0, "fault": 0}
    for row in rows:
        sample = sample_from_db_row(row)
        effective = sample_effective_status(sample)
        status_counts[effective] = status_counts.get(effective, 0) + 1
        if sample_has_problem(sample):
            problem_counts["fault"] = problem_counts.get("fault", 0) + 1
        else:
            problem_counts["ok"] = problem_counts.get("ok", 0) + 1
        if not sample_matches_query(sample, query):
            continue
        sample["effectiveStatus"] = effective
        all_items.append(sample)

    page_items, meta = paginate_list(all_items, page, page_size)
    photo_counts = load_sample_photo_counts_for(conn, [str(item.get("id")) for item in page_items])
    for item in page_items:
        item["photoCount"] = photo_counts.get(str(item.get("id")), 0)

    cat = json_obj(category_row["data_json"], {}) or {}
    return {
        **meta,
        "category": {
            "id": category_row["id"],
            "name": category_row["name"] or cat.get("name") or "",
            "description": category_row["description"] or cat.get("description") or "",
        },
        "stats": {
            "totalInCategory": len(rows),
            "filtered": len(all_items),
            "statusCounts": status_counts,
            "problemCounts": problem_counts,
        },
        "items": page_items,
    }


def query_id_list(query: dict[str, list[str]], name: str, *, max_items: int = 500) -> list[str]:
    result: list[str] = []
    seen: set[str] = set()
    for raw in query.get(name) or []:
        for part in str(raw or "").split(","):
            value = part.strip()
            if not value or value in seen:
                continue
            seen.add(value)
            result.append(value)
            if len(result) >= max_items:
                return result
    return result


def sample_candidate_keyword_where(keyword: str, *, negate: bool = False) -> tuple[str, list[object]]:
    like = f"%{keyword.lower()}%"
    expr = """
        (LOWER(r.sample_no) LIKE ? OR LOWER(r.sn) LIKE ? OR LOWER(r.imei) LIKE ?
         OR LOWER(r.owner) LIKE ? OR LOWER(r.borrower) LIKE ? OR LOWER(r.location) LIKE ?
         OR LOWER(c.name) LIKE ? OR LOWER(r.data_json) LIKE ?)
    """
    if negate:
        expr = f"NOT {expr}"
    return expr, [like, like, like, like, like, like, like, like]


def open_task_occupancy_for_sample_ids(conn: sqlite3.Connection, sample_ids: list[str], *, exclude_task_id: str = "") -> dict[str, list[dict]]:
    ids = [str(x or "").strip() for x in sample_ids if str(x or "").strip()]
    if not ids:
        return {}
    placeholders = ",".join("?" for _ in ids)
    where = [
        f"sample_id IN ({placeholders})",
        "flow_status NOT IN ('正常完成', '异常终止')",
    ]
    args: list[object] = [*ids]
    if exclude_task_id:
        where.append("task_id != ?")
        args.append(exclude_task_id)
    rows = conn.execute(
        f"""
        SELECT sample_id, task_id, project_id, stage_id, test_item, status
        FROM project_task_samples
        WHERE {" AND ".join(where)}
        ORDER BY updated_at DESC, task_id
        """,
        args,
    ).fetchall()
    occupancy: dict[str, list[dict]] = {}
    for row in rows:
        sid = str(row["sample_id"] or "")
        if not sid:
            continue
        occupancy.setdefault(sid, []).append({
            "taskId": str(row["task_id"] or ""),
            "projectId": str(row["project_id"] or ""),
            "stageId": str(row["stage_id"] or ""),
            "testItem": str(row["test_item"] or ""),
            "status": str(row["status"] or ""),
        })
    return occupancy


def task_sample_candidate_from_row(row: sqlite3.Row) -> dict:
    sample = sample_from_db_row(row)
    sample["categoryName"] = row["category_name"] or ""
    sample["effectiveStatus"] = sample_effective_status(sample)
    sample["hasProblem"] = sample_has_problem(sample)
    return sample


def decorate_task_sample_candidates(
    samples: list[dict],
    *,
    selected_ids: set[str],
    occupancy: dict[str, list[dict]],
) -> list[dict]:
    for sample in samples:
        sid = str(sample.get("id") or "")
        selected = sid in selected_ids
        status = sample_record_status(sample)
        occupied_tasks = occupancy.get(sid, [])
        status_blocked = status != "闲置"
        selectable = selected or (not status_blocked and not occupied_tasks)
        if selected:
            disabled_reason = ""
        elif occupied_tasks:
            disabled_reason = "样机已被其他未完成任务占用"
        elif status_blocked:
            disabled_reason = f"当前状态为「{status}」，不能加入测试任务"
        else:
            disabled_reason = ""
        sample["alreadySelected"] = selected
        sample["selectable"] = selectable
        sample["disabledReason"] = disabled_reason
        sample["occupyingTasks"] = occupied_tasks
    return samples


def sample_identity_value(value: object) -> str:
    return str(value or "").strip()


def sample_identity_key(value: object) -> str:
    return sample_identity_value(value).lower()


def sample_identity_fields(sample: dict) -> list[dict]:
    return [
        {"field": "sn", "label": "SN", "value": sample_identity_value(sample.get("sn"))},
        {"field": "imei", "label": "IMEI", "value": sample_identity_value(sample.get("imei"))},
        {"field": "boardSn", "label": "主板SN", "value": sample_identity_value(sample.get("boardSn"))},
    ]


def sample_display_code(sample: dict) -> str:
    sn = sample_identity_value(sample.get("sn"))
    imei = sample_identity_value(sample.get("imei"))
    board_sn = sample_identity_value(sample.get("boardSn"))
    if sn:
        return f"SN#{sn[-6:]}"
    if imei:
        return f"IMEI#{imei[-6:]}"
    if board_sn:
        return f"主板SN#{board_sn[-6:]}"
    return sample_identity_value(sample.get("sampleNo")) or "未录入SN/IMEI/主板SN"


def compact_sample_identity_row(row: sqlite3.Row) -> dict:
    sample = sample_from_db_row(row)
    return {
        "id": str(sample.get("id") or ""),
        "categoryId": str(sample.get("categoryId") or ""),
        "categoryName": str(row["category_name"] or "") if "category_name" in row.keys() else "",
        "sampleNo": str(sample.get("sampleNo") or ""),
        "sn": str(sample.get("sn") or ""),
        "imei": str(sample.get("imei") or ""),
        "boardSn": str(sample.get("boardSn") or ""),
        "isReassembled": sample_is_reassembled(sample),
        "status": str(sample.get("status") or ""),
        "code": sample_display_code(sample),
    }


def sample_identity_match_field(sample: dict, key: str) -> dict | None:
    for item in sample_identity_fields(sample):
        if item["value"] and item["value"].lower() == key:
            return item
    return None


def check_sample_identity_conflicts(conn: sqlite3.Connection, payload: dict) -> dict:
    raw_samples = payload.get("samples")
    if not isinstance(raw_samples, list):
        raw_samples = [payload]
    default_category_id = str(payload.get("categoryId") or payload.get("excludeCategoryId") or "")
    entries: list[dict] = []
    values: list[str] = []
    seen_values: set[str] = set()
    for pos, raw in enumerate(raw_samples):
        if not isinstance(raw, dict):
            continue
        sample = dict(raw)
        sample["_index"] = raw.get("index", pos)
        sample["_categoryId"] = str(raw.get("categoryId") or default_category_id or "")
        sample["_excludeSampleId"] = str(raw.get("excludeSampleId") or "")
        if sample_is_reassembled(sample):
            continue
        for field in sample_identity_fields(sample):
            key = field["value"].lower()
            if not key:
                continue
            entry = {"sample": sample, "field": field, "key": key}
            entries.append(entry)
            if key not in seen_values:
                seen_values.add(key)
                values.append(key)

    results = [{
        "index": raw.get("index", pos) if isinstance(raw, dict) else pos,
        "hasConflict": False,
        "conflict": None,
    } for pos, raw in enumerate(raw_samples)]
    if not entries:
        return {"results": results, "conflicts": [], "count": 0}

    entries_by_key: dict[str, list[dict]] = {}
    for entry in entries:
        entries_by_key.setdefault(entry["key"], []).append(entry)

    conflicts_by_index: dict[object, dict] = {}
    chunk_size = 250
    for start in range(0, len(values), chunk_size):
        chunk = values[start:start + chunk_size]
        placeholders = ",".join("?" for _ in chunk)
        rows = conn.execute(
            f"""
            SELECT r.id, r.category_id, c.name AS category_name,
                   r.sample_no, r.sn, r.imei, r.board_sn, r.is_reassembled,
                   r.status, r.has_problem, r.effective_status, r.location, r.owner, r.borrower, r.data_json
            FROM sample_records r
            JOIN sample_categories c ON c.id = r.category_id
            WHERE r.deleted_at IS NULL
              AND c.deleted_at IS NULL
              AND COALESCE(r.is_reassembled, 0) = 0
              AND (
                r.sn COLLATE NOCASE IN ({placeholders})
                OR r.imei COLLATE NOCASE IN ({placeholders})
                OR r.board_sn COLLATE NOCASE IN ({placeholders})
              )
            ORDER BY c.sort_order, c.id, r.created_at, r.id
            """,
            [*chunk, *chunk, *chunk],
        ).fetchall()
        for row in rows:
            existing = compact_sample_identity_row(row)
            existing_fields = sample_identity_fields(existing)
            for existing_field in existing_fields:
                existing_key = existing_field["value"].lower()
                if not existing_key or existing_key not in entries_by_key:
                    continue
                for entry in entries_by_key[existing_key]:
                    incoming = entry["sample"]
                    index = incoming["_index"]
                    if index in conflicts_by_index:
                        continue
                    if incoming.get("_excludeSampleId") and str(existing["id"]) == incoming["_excludeSampleId"]:
                        continue
                    category_id = str(incoming.get("_categoryId") or "")
                    scope = "category" if category_id and str(existing["categoryId"]) == category_id else "global"
                    conflicts_by_index[index] = {
                        "index": index,
                        "scope": scope,
                        "categoryId": existing["categoryId"],
                        "categoryName": existing["categoryName"],
                        "sample": existing,
                        "conflictId": existing_field["value"],
                        "incomingField": entry["field"]["field"],
                        "incomingLabel": entry["field"]["label"],
                        "existingField": existing_field["field"],
                        "existingLabel": existing_field["label"],
                    }

    for result in results:
        index = result["index"]
        conflict = conflicts_by_index.get(index)
        if conflict:
            result["hasConflict"] = True
            result["conflict"] = conflict

    conflicts = [result["conflict"] for result in results if result.get("conflict")]
    return {"results": results, "conflicts": conflicts, "count": len(conflicts)}


def list_task_sample_candidates_page(conn: sqlite3.Connection, query: dict[str, list[str]]) -> dict:
    page, page_size = parse_page_params(query, default_size=50, max_size=100)
    task_id = first_query_value(query, "taskId", "").strip()
    selected_ids = query_id_list(query, "selectedIds", max_items=500)
    selected_set = set(selected_ids)
    category_id = first_query_value(query, "categoryId", "").strip()
    keyword = first_query_value(query, "keyword", "").strip().lower()
    exclude_keyword = first_query_value(query, "excludeKeyword", "").strip().lower()
    status = first_query_value(query, "status", "").strip()

    categories = list_sample_categories_summary(conn)
    where = ["r.deleted_at IS NULL", "c.deleted_at IS NULL"]
    args: list[object] = []
    if category_id:
        where.append("r.category_id = ?")
        args.append(category_id)
    if selected_ids:
        placeholders = ",".join("?" for _ in selected_ids)
        where.append(f"r.id NOT IN ({placeholders})")
        args.extend(selected_ids)
    if status:
        where.append(f"{sample_usage_status_sql_expr('r.status')} = ?")
        args.append(status)
    if keyword:
        expr, expr_args = sample_candidate_keyword_where(keyword)
        where.append(expr)
        args.extend(expr_args)
    if exclude_keyword:
        expr, expr_args = sample_candidate_keyword_where(exclude_keyword, negate=True)
        where.append(expr)
        args.extend(expr_args)

    total = int(conn.execute(
        f"""
        SELECT COUNT(*) AS count
        FROM sample_records r
        JOIN sample_categories c ON c.id = r.category_id
        WHERE {" AND ".join(where)}
        """,
        args,
    ).fetchone()["count"] or 0)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    offset = (page - 1) * page_size

    rows = conn.execute(
        f"""
        SELECT r.id, r.category_id, c.name AS category_name,
               r.sample_no, r.sn, r.imei, r.board_sn, r.is_reassembled, r.status, r.has_problem, r.effective_status,
               r.location, r.owner, r.borrower, r.data_json
        FROM sample_records r
        JOIN sample_categories c ON c.id = r.category_id
        WHERE {" AND ".join(where)}
        ORDER BY c.sort_order, c.id, r.created_at, r.id
        LIMIT ? OFFSET ?
        """,
        [*args, page_size, offset],
    ).fetchall()
    items = [task_sample_candidate_from_row(row) for row in rows]

    selected_items: list[dict] = []
    if selected_ids:
        placeholders = ",".join("?" for _ in selected_ids)
        selected_rows = conn.execute(
            f"""
            SELECT r.id, r.category_id, c.name AS category_name,
                   r.sample_no, r.sn, r.imei, r.board_sn, r.is_reassembled, r.status, r.has_problem, r.effective_status,
                   r.location, r.owner, r.borrower, r.data_json
            FROM sample_records r
            JOIN sample_categories c ON c.id = r.category_id
            WHERE r.deleted_at IS NULL AND c.deleted_at IS NULL AND r.id IN ({placeholders})
            ORDER BY c.sort_order, c.id, r.created_at, r.id
            """,
            selected_ids,
        ).fetchall()
        selected_by_id = {str(row["id"] or ""): task_sample_candidate_from_row(row) for row in selected_rows}
        selected_items = [selected_by_id[sid] for sid in selected_ids if sid in selected_by_id]

    all_candidate_ids = [str(item.get("id") or "") for item in [*items, *selected_items]]
    occupancy = open_task_occupancy_for_sample_ids(conn, all_candidate_ids, exclude_task_id=task_id)
    decorate_task_sample_candidates(items, selected_ids=selected_set, occupancy=occupancy)
    decorate_task_sample_candidates(selected_items, selected_ids=selected_set, occupancy=occupancy)

    return {
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        "items": items,
        "selectedItems": selected_items,
        "selectedCount": len(selected_ids),
        "categories": categories,
        "filters": {
            "taskId": task_id,
            "categoryId": category_id,
            "keyword": keyword,
            "excludeKeyword": exclude_keyword,
            "status": status,
        },
    }


def sample_task_result_photos(task: dict, sample_id: str, photos_by_id: dict[str, dict]) -> list[dict]:
    photos: list[dict] = []
    for upload in task.get("resultUploads") or []:
        if not isinstance(upload, dict):
            continue
        for item in upload.get("samples") or []:
            if not isinstance(item, dict) or str(item.get("sampleId") or item.get("sid") or "") != str(sample_id):
                continue
            for ref in item.get("photos") or []:
                if not isinstance(ref, dict) or not ref.get("id"):
                    continue
                full = photos_by_id.get(str(ref.get("id") or ""), {})
                photos.append({
                    "id": str(ref.get("id") or ""),
                    "name": str(ref.get("name") or full.get("name") or "结果图片"),
                    "url": str(ref.get("url") or full.get("url") or ""),
                    "thumbUrl": str(ref.get("thumbUrl") or ref.get("thumbnailUrl") or full.get("thumbUrl") or full.get("thumbnailUrl") or ""),
                    "thumbnailUrl": str(ref.get("thumbnailUrl") or ref.get("thumbUrl") or full.get("thumbnailUrl") or full.get("thumbUrl") or ""),
                    "uploadedAt": str(ref.get("uploadedAt") or full.get("uploadedAt") or upload.get("time") or ""),
                    "result": str(upload.get("result") or ""),
                    "user": str(upload.get("user") or ""),
                    "uploadTime": str(upload.get("time") or ""),
                })
    seen: set[str] = set()
    unique: list[dict] = []
    for photo in photos:
        key = f"{photo.get('uploadTime') or ''}_{photo.get('id') or ''}"
        if key in seen:
            continue
        seen.add(key)
        unique.append(photo)
    return unique


def sample_history_row_for(sample_id: str, item: dict, photos_by_id: dict[str, dict]) -> dict:
    task = item.get("task") if isinstance(item.get("task"), dict) else None
    logs = item.get("logs") if isinstance(item.get("logs"), list) else []
    project_name = str(item.get("projectName") or "")
    stage_name = str(item.get("stageName") or "")
    test_item = str(item.get("testItem") or "")
    if task:
        test_item = str(task.get("testItem") or test_item or "-")
        result = str(task.get("latestResult") or task.get("result") or "-")
        date = str(task.get("resultDate") or task.get("completedAt") or task.get("planDate") or (logs[-1].get("time") if logs else "") or "-")
        sample_ids = {str(x) for x in task.get("sampleIds") or [] if str(x or "")}
        sample_ids.update(str(x.get("sampleId") or "") for x in task.get("removedSampleRecords") or [] if isinstance(x, dict) and x.get("sampleId"))
        task_sample_count = len(sample_ids)
        sample_fault_records = [x for x in task.get("sampleFaultRecords") or [] if isinstance(x, dict) and str(x.get("sampleId") or "") == str(sample_id)]
        fault_marked = any(log.get("faultMarked") or log.get("flowStatus") == "故障" for log in logs)
        fault_marked = fault_marked or bool((task.get("sampleFaults") or {}).get(sample_id, {}).get("fault"))
        fault_marked = fault_marked or any(x.get("fault") or x.get("problem") for x in sample_fault_records)
        problems = []
        for value in [
            *[log.get("problemDescription") for log in logs],
            (task.get("sampleFaults") or {}).get(sample_id, {}).get("problem"),
            *[x.get("problem") for x in sample_fault_records],
        ]:
            text = str(value or "").strip()
            if text and text not in problems:
                problems.append(text)
        result_photos = sample_task_result_photos(task, sample_id, photos_by_id)
        status = task_flow_status(task)
    else:
        result = "-"
        date = str((logs[-1].get("time") if logs else "") or "-")
        task_sample_count = 0
        fault_marked = any(log.get("faultMarked") or log.get("flowStatus") == "故障" for log in logs)
        problems = []
        for log in logs:
            text = str(log.get("problemDescription") or "").strip()
            if text and text not in problems:
                problems.append(text)
        result_photos = []
        status = "历史记录"

    return {
        "key": str(item.get("key") or (task or {}).get("id") or ""),
        "task": task,
        "projectName": project_name or "-",
        "stageName": stage_name or "-",
        "testItem": test_item or "-",
        "logs": logs,
        "status": status,
        "result": result,
        "date": date,
        "taskSampleCount": task_sample_count,
        "faultMarked": bool(fault_marked),
        "problems": problems,
        "resultPhotos": result_photos,
        "sortTime": str((task or {}).get("completedAt") or (task or {}).get("resultDate") or (task or {}).get("startDate") or (logs[-1].get("time") if logs else "") or ""),
    }


def list_sample_history_page(conn: sqlite3.Connection, sample_id: str, query: dict[str, list[str]]) -> dict:
    sample_id = str(sample_id or "")
    if not sample_id:
        raise KeyError("缺少样机 ID")
    sample_row = conn.execute(
        "SELECT id FROM sample_records WHERE id = ? AND deleted_at IS NULL",
        (sample_id,),
    ).fetchone()
    if not sample_row:
        raise KeyError("样机不存在")

    page, page_size = parse_page_params(query, default_size=20, max_size=50)
    event_rows = conn.execute(
        """
        SELECT id, time, task_id, project_id, stage_id, test_item, data_json
        FROM sample_events
        WHERE sample_id = ?
        ORDER BY time, id
        """,
        (sample_id,),
    ).fetchall()
    rows_by_key: dict[str, dict] = {}
    task_ids: set[str] = set()
    for row in event_rows:
        log = json_obj(row["data_json"], None)
        if not isinstance(log, dict):
            continue
        task_id = str(row["task_id"] or log.get("taskId") or "")
        key = task_id or f"log_{row['id']}"
        if task_id:
            task_ids.add(task_id)
        item = rows_by_key.setdefault(key, {
            "key": key,
            "task": None,
            "projectName": str(log.get("projectName") or ""),
            "stageName": str(log.get("stageName") or ""),
            "testItem": str(row["test_item"] or log.get("testItem") or "-"),
            "logs": [],
        })
        item["logs"].append(log)
        item["projectName"] = item["projectName"] or str(log.get("projectName") or "")
        item["stageName"] = item["stageName"] or str(log.get("stageName") or "")

    link_rows = conn.execute(
        "SELECT DISTINCT task_id FROM project_task_samples WHERE sample_id = ?",
        (sample_id,),
    ).fetchall()
    for row in link_rows:
        tid = str(row["task_id"] or "")
        if tid:
            task_ids.add(tid)

    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        task_rows = conn.execute(
            f"""
            SELECT t.id, t.project_id, t.stage_id, t.progress_id, t.category, t.test_item, t.sku_index,
                   t.status, t.flow_status, t.owner, t.sample_ids_json, t.data_json,
                   t.created_at, t.updated_at, t.completed_at, t.deleted_at,
                   p.name AS project_name, s.name AS stage_name
            FROM project_tasks t
            LEFT JOIN project_records p ON p.id = t.project_id
            LEFT JOIN project_stages s ON s.id = t.stage_id
            WHERE t.id IN ({placeholders})
            """,
            list(task_ids),
        ).fetchall()
        for row in task_rows:
            task = task_from_db_row(row)
            key = str(task.get("id") or "")
            item = rows_by_key.setdefault(key, {
                "key": key,
                "task": None,
                "projectName": "",
                "stageName": "",
                "testItem": "",
                "logs": [],
            })
            item["task"] = task
            item["projectName"] = str(row["project_name"] or item.get("projectName") or "")
            item["stageName"] = str(row["stage_name"] or item.get("stageName") or "")
            item["testItem"] = str(task.get("testItem") or item.get("testItem") or "-")

    photos_by_id = {str(photo.get("id") or ""): photo for photo in load_sample_photos(conn, sample_id)}
    history_rows = [sample_history_row_for(sample_id, item, photos_by_id) for item in rows_by_key.values()]
    history_rows.sort(key=lambda item: str(item.get("sortTime") or ""), reverse=True)
    total = len(history_rows)
    total_pages = max(1, (total + page_size - 1) // page_size)
    page = min(max(1, page), total_pages)
    offset = (page - 1) * page_size
    page_items = history_rows[offset:offset + page_size]
    for item in page_items:
        item.pop("sortTime", None)
    return {
        "sampleId": sample_id,
        "page": page,
        "pageSize": page_size,
        "total": total,
        "totalPages": total_pages,
        "items": page_items,
    }


def load_sample_category_detail(conn: sqlite3.Connection, category_id: str, *, include_photos: bool = False) -> dict | None:
    category_row = conn.execute(
        """
        SELECT id, name, description, data_json
        FROM sample_categories
        WHERE id = ? AND deleted_at IS NULL
        """,
        (category_id,),
    ).fetchone()
    if not category_row:
        return None

    category = json_obj(category_row["data_json"], {}) or {}
    category.update({
        "id": category_row["id"],
        "name": category_row["name"] or category.get("name") or "",
        "description": category_row["description"] or category.get("description") or "",
        "samples": [],
    })

    photo_counts = {} if include_photos else load_sample_photo_counts_for(conn, [])
    sample_rows = conn.execute(
        """
        SELECT id, category_id, sample_no, sn, imei, board_sn, is_reassembled, status, location, owner, borrower, data_json
        FROM sample_records
        WHERE category_id = ? AND deleted_at IS NULL
        ORDER BY created_at, id
        """,
        (category_id,),
    ).fetchall()
    if not include_photos:
        photo_counts = load_sample_photo_counts_for(conn, [str(row["id"]) for row in sample_rows])
    for row in sample_rows:
        sample = json_obj(row["data_json"], {}) or {}
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
        })
        if include_photos:
            sample["photos"] = load_sample_photos(conn, row["id"])
            sample["photoCount"] = len(sample["photos"])
            sample["photosLoaded"] = True
        else:
            sample["photos"] = []
            sample["photoCount"] = photo_counts.get(str(row["id"]), 0)
            sample["photosLoaded"] = False
        category["samples"].append(sample)
    category["sampleCount"] = len(category["samples"])
    category["samplesLoaded"] = True
    return category


def list_project_summary(conn: sqlite3.Connection) -> list[dict]:
    project_rows = conn.execute(
        """
        SELECT id, name, code, owner, data_json
        FROM project_records
        WHERE deleted_at IS NULL
        ORDER BY sort_order, id
        """
    ).fetchall()
    stage_rows = conn.execute(
        """
        SELECT project_id, COUNT(*) AS count
        FROM project_stages
        WHERE deleted_at IS NULL
        GROUP BY project_id
        """
    ).fetchall()
    task_rows = conn.execute(
        """
        SELECT project_id, COUNT(*) AS count
        FROM project_tasks
        WHERE deleted_at IS NULL
        GROUP BY project_id
        """
    ).fetchall()
    stages_by_project = {str(row["project_id"]): int(row["count"] or 0) for row in stage_rows}
    tasks_by_project = {str(row["project_id"]): int(row["count"] or 0) for row in task_rows}

    projects = []
    for row in project_rows:
        project = json_obj(row["data_json"], {}) or {}
        projects.append({
            "id": row["id"],
            "name": row["name"] or project.get("name") or "",
            "code": row["code"] or project.get("code") or "",
            "owner": row["owner"] or project.get("owner") or "",
            "stageCount": stages_by_project.get(str(row["id"]), 0),
            "taskCount": tasks_by_project.get(str(row["id"]), 0),
        })
    return projects


def compose_bootstrap_state(conn: sqlite3.Connection) -> tuple[dict, int, str]:
    row = conn.execute("SELECT data_json, revision, updated_at FROM app_state WHERE id = 1").fetchone()
    if row is None:
        data = empty_data()
        revision = 1
        updated_at = now_iso()
    else:
        stored = json_obj(row["data_json"], empty_data()) or empty_data()
        data = empty_data()
        data["currentProjectId"] = stored.get("currentProjectId")
        data["currentStageId"] = stored.get("currentStageId")
        data["eventSchema"] = stored.get("eventSchema") or "sample_events_v2"
        data["users"] = stored.get("users") if isinstance(stored.get("users"), list) else []
        revision = int(row["revision"])
        updated_at = str(row["updated_at"])

    data["projects"] = [
        {**project, "stages": [], "_summaryOnly": True, "_detailLoaded": False}
        for project in list_project_summary(conn)
    ]
    data["sampleLibrary"] = {
        "categories": [
            {**category, "samples": [], "_summaryOnly": True, "samplesLoaded": False}
            for category in list_sample_categories_summary(conn)
        ],
        "logs": [],
        "photosExternalized": True,
        "eventsExternalized": True,
    }
    data["bootstrapMode"] = True
    return data, revision, updated_at


def compose_state(conn: sqlite3.Connection, *, include_sample_photos: bool = True, include_sample_logs: bool = True) -> tuple[dict, int, str]:
    row = conn.execute("SELECT data_json, revision, updated_at FROM app_state WHERE id = 1").fetchone()
    if row is None:
        return empty_data(), 1, now_iso()
    data = json_obj(row["data_json"], empty_data()) or empty_data()
    data["version"] = APP_VERSION
    data.pop("peoplePool", None)
    data.pop("locationPool", None)
    data["projects"] = load_project_library(conn)
    data["sampleLibrary"] = load_sample_library(conn, include_photos=include_sample_photos, include_logs=include_sample_logs)
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


def get_state(*, compact: bool = False) -> tuple[dict, int, str]:
    with DB_LOCK:
        with connect_db() as conn:
            return compose_state(conn, include_sample_photos=not compact, include_sample_logs=not compact)


def hydrate_externalized_sample_fields(new_data: dict, current_data: dict) -> None:
    """Preserve externally loaded sample photos/events when a compact client saves."""
    library = new_data.get("sampleLibrary") or {}
    current_library = current_data.get("sampleLibrary") or {}

    if library.get("photosExternalized"):
        current_samples = _sample_index_by_id(current_data)
        for _, sample in iter_samples(new_data):
            current_sample = current_samples.get(str(sample.get("id") or ""))
            if not current_sample:
                sample["photos"] = list(sample.get("photos") or [])
                sample["photoCount"] = len(sample["photos"])
                sample["photosLoaded"] = True
                continue
            if sample.get("photosLoaded") is True:
                sample["photoCount"] = len(sample.get("photos") or [])
                continue
            preserved = copy.deepcopy(current_sample.get("photos") or [])
            sample["photos"] = preserved
            sample["photoCount"] = len(preserved)
            sample["photosLoaded"] = True

    if library.get("eventsExternalized"):
        incoming_logs = [log for log in (library.get("logs") or []) if isinstance(log, dict)]
        merged_logs = []
        seen = set()
        for log in [*(current_library.get("logs") or []), *incoming_logs]:
            if not isinstance(log, dict):
                continue
            key = str(log.get("id") or "") or _content_hash(log)
            if key in seen:
                continue
            seen.add(key)
            merged_logs.append(copy.deepcopy(log))
        library["logs"] = merged_logs

    library.pop("photosExternalized", None)
    library.pop("eventsExternalized", None)


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
    curr_samples_by_board_sn = {}
    for s in curr_samples:
        sn = (s.get("sn") or "").strip()
        imei = (s.get("imei") or "").strip()
        board_sn = (s.get("boardSn") or "").strip()
        sno = (s.get("sampleNo") or "").strip()
        if sn:
            curr_samples_by_sn.setdefault(sn, []).append(s)
        if imei:
            curr_samples_by_imei.setdefault(imei, []).append(s)
        if board_sn:
            curr_samples_by_board_sn.setdefault(board_sn, []).append(s)
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
            field_diffs = _diff_fields(curr_p, proj, skip_keys={"stages", "tasks", "members", "locations"})
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

    def _blocking_sample_identity_match(index: dict, value: str, incoming_sample: dict, incoming_id: str) -> dict | None:
        if not value:
            return None
        for current_sample in index.get(value, []) or []:
            if current_sample.get("id") == incoming_id:
                continue
            if sample_is_reassembled(incoming_sample) or sample_is_reassembled(current_sample):
                continue
            return current_sample
        return None

    def _append_sample_identity_conflict(curr_s: dict, sample: dict, sid: str, match_by: str, label: str) -> None:
        mergeable = ["location", "owner", "status", "borrower", "sourceStageName", "sourceSkuName"]
        conflicts.append({
            "conflictId": _next_conflict_id(),
            "type": "sample_identity_conflict",
            "entity": "sample",
            "currentId": curr_s["id"], "incomingId": sid,
            "matchBy": match_by,
            "label": label,
            "current": {k: curr_s.get(k) for k in mergeable if curr_s.get(k) != sample.get(k)},
            "incoming": {k: sample.get(k) for k in mergeable if curr_s.get(k) != sample.get(k)},
            "allowedActions": ["merge_into_existing", "import_as_new_with_identity_edit", "skip"],
            "mergeableFields": mergeable,
            "autoMergeSubData": ["photos", "problemRecords"],
            "preferredMergeTarget": curr_s["id"],
        })

    # ── 样机匹配 ──
    for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []:
        cat_name = cat.get("name", "")
        for sample in cat.get("samples") or []:
            sid = sample.get("id", "")
            sn = (sample.get("sn") or "").strip()
            imei = (sample.get("imei") or "").strip()
            board_sn = (sample.get("boardSn") or "").strip()
            sno = (sample.get("sampleNo") or "").strip()

            # 1) ID 相同
            if sid and sid in curr_samples_by_id:
                curr_s = curr_samples_by_id[sid]
                field_diffs = _diff_fields(curr_s, sample, skip_keys={"photos", "logs", "problemRecords", "_categoryName"})
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

            identity_checks = [
                ("sn", sn, f"SN: {sn}", curr_samples_by_sn),
                ("imei", imei, f"IMEI: {imei}", curr_samples_by_imei),
                ("boardSn", board_sn, f"主板SN: {board_sn}", curr_samples_by_board_sn),
            ]
            identity_conflicted = False
            for match_by, value, label, index in identity_checks:
                curr_s = _blocking_sample_identity_match(index, value, sample, sid)
                if curr_s:
                    _append_sample_identity_conflict(curr_s, sample, sid, match_by, label)
                    identity_conflicted = True
                    break
            if identity_conflicted:
                continue

            # 2) 新增样机
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


IMPORT_DIFF_SYSTEM_SKIP_KEYS = {
    "categoryId",
    "photoCount",
    "photosLoaded",
    "eventsLoaded",
    "effectiveStatus",
    "logsLoaded",
}


def _diff_fields(current_item: dict, incoming_item: dict, skip_keys: set = set()) -> set:
    """返回两个字典中有差异的字段名集合（排除 skip_keys）"""
    diffs = set()
    ignored = set(skip_keys) | IMPORT_DIFF_SYSTEM_SKIP_KEYS
    all_keys = set(current_item.keys()) | set(incoming_item.keys())
    for k in all_keys:
        if k in ignored or k.startswith("_"):
            continue
        cv = current_item.get(k)
        iv = incoming_item.get(k)
        if stable_json(cv) != stable_json(iv):
            diffs.add(k)
    return diffs


def _sorted_nonempty_ids(values) -> list[str]:
    return sorted({str(value) for value in values if str(value or "").strip()})


def _build_import_mutation_summary(current_data: dict,
                                   project_id_map: dict,
                                   stage_id_map: dict,
                                   task_id_map: dict,
                                   sample_id_map: dict,
                                   touched_structure_project_ids: set[str]) -> dict:
    """Return the smallest frontend sync scope after a successful bundle import."""
    project_ids = {str(value) for value in project_id_map.values() if value}
    project_ids.update(str(value) for value in touched_structure_project_ids if value)
    stage_ids = {str(value) for value in stage_id_map.values() if value}
    task_ids = {str(value) for value in task_id_map.values() if value}
    sample_ids = {str(value) for value in sample_id_map.values() if value}
    sample_category_ids: set[str] = set()

    for project in current_data.get("projects") or []:
        if not isinstance(project, dict):
            continue
        pid = str(project.get("id") or "")
        project_touched = pid in project_ids
        for stage in project.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            sid = str(stage.get("id") or "")
            if project_touched and sid:
                stage_ids.add(sid)
            if sid in stage_ids and pid:
                project_ids.add(pid)
            for task in stage.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                tid = str(task.get("id") or "")
                if tid and tid in task_ids:
                    if sid:
                        stage_ids.add(sid)
                    if pid:
                        project_ids.add(pid)

    for category in (current_data.get("sampleLibrary") or {}).get("categories") or []:
        if not isinstance(category, dict):
            continue
        cid = str(category.get("id") or "")
        for sample in category.get("samples") or []:
            if not isinstance(sample, dict):
                continue
            sid = str(sample.get("id") or "")
            if sid and sid in sample_ids and cid:
                sample_category_ids.add(cid)

    return {
        "summaryVersion": 1,
        "projectIds": _sorted_nonempty_ids(project_ids),
        "stageIds": _sorted_nonempty_ids(stage_ids),
        "taskIds": _sorted_nonempty_ids(task_ids),
        "sampleCategoryIds": _sorted_nonempty_ids(sample_category_ids),
        "sampleIds": _sorted_nonempty_ids(sample_ids),
        "requiresFullState": False,
    }


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
            new_board_sn = (d.get("newBoardSn") or "").strip()
            new_sample_no = (d.get("newSampleNo") or "").strip()
            if not new_sn and not new_imei and not new_board_sn and not new_sample_no:
                return {"ok": False, "error": f"冲突 {cid} 选择编辑标识导入但未提供新 SN/IMEI/主板SN/编号", "status": 400}
        elif action == "apply_field_choices":
            if not isinstance(d.get("fieldChoices") or {}, dict):
                return {"ok": False, "error": f"冲突 {cid} 的字段选择格式不正确", "status": 400}

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
             "photosAdded": 0, "sampleEventsAdded": 0, "skipped": 0}

    # ── ID 映射表（incoming → target），所有写入必须经此重映射 ──
    project_id_map: dict[str, str] = {}  # incomingPID → targetPID
    stage_id_map: dict[str, str] = {}    # incomingSID → targetSID
    task_id_map: dict[str, str] = {}     # incomingTID → targetTID
    sample_id_map: dict[str, str] = {}   # incomingSampleID → targetSampleID
    skipped_sample_ids: set[str] = set()
    fully_imported_project_ids: set[str] = set()
    fully_imported_stage_ids: set[str] = set()
    touched_structure_project_ids: set[str] = set()

    for auto in result.get("autoApply") or []:
        atype = auto["type"]
        if atype == "new_project":
            pid = auto["id"]
            if pid not in curr_projects and pid in incoming_projects_by_id:
                project = _normalize_project(incoming_projects_by_id[pid])
                curr_projects[pid] = project
                stats["projectsAdded"] += 1
                project_id_map[pid] = pid
                stage_count, task_count, stage_ids = _register_imported_project_tree(project, stage_id_map, task_id_map)
                stats["stagesAdded"] += stage_count
                stats["tasksAdded"] += task_count
                fully_imported_project_ids.add(pid)
                fully_imported_stage_ids.update(stage_ids)
                touched_structure_project_ids.add(pid)
        elif atype == "new_stage":
            proj_id = auto.get("projectId", "")
            sid = auto["id"]
            target_project_id = project_id_map.get(proj_id, proj_id)
            if proj_id in fully_imported_project_ids or sid in fully_imported_stage_ids:
                continue
            if target_project_id in curr_projects and proj_id in incoming_projects_by_id:
                inc_proj = incoming_projects_by_id[proj_id]
                for inc_stage in inc_proj.get("stages") or []:
                    if inc_stage.get("id") == sid:
                        stage = copy.deepcopy(inc_stage)
                        curr_projects[target_project_id].setdefault("stages", []).append(stage)
                        stats["stagesAdded"] += 1
                        _, task_count, stage_id = _register_imported_stage_tree(stage, stage_id_map, task_id_map)
                        stats["tasksAdded"] += task_count
                        if stage_id:
                            fully_imported_stage_ids.add(stage_id)
                        touched_structure_project_ids.add(target_project_id)
                        break
        elif atype == "new_task":
            proj_id = auto.get("projectId", "")
            stage_id = auto.get("stageId", "")
            tid = auto["id"]
            target_project_id = project_id_map.get(proj_id, proj_id)
            target_stage_id = stage_id_map.get(stage_id, stage_id)
            if proj_id in fully_imported_project_ids or stage_id in fully_imported_stage_ids:
                continue
            if target_project_id in curr_projects and proj_id in incoming_projects_by_id:
                inc_proj = incoming_projects_by_id[proj_id]
                for inc_stage in inc_proj.get("stages") or []:
                    if inc_stage.get("id") == stage_id:
                        for inc_task in inc_stage.get("tasks") or []:
                            if inc_task.get("id") == tid:
                                curr_stages = curr_projects[target_project_id].setdefault("stages", [])
                                for cs in curr_stages:
                                    if cs.get("id") == target_stage_id:
                                        cs.setdefault("tasks", []).append(copy.deepcopy(inc_task))
                                        stats["tasksAdded"] += 1
                                        task_id_map[tid] = tid
                                        touched_structure_project_ids.add(target_project_id)
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
                        touched_structure_project_ids.add(target_id)
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
                                if inc_id:
                                    stage_id_map[inc_id] = target_id
                                touched_structure_project_ids.add(proj_id)
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
                                    if inc_id:
                                        task_id_map[inc_id] = target_id
                                    touched_structure_project_ids.add(proj_id)
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
                                sample_id_map[inc_id] = target_id
                                stats["samplesMerged"] += 1
                                break
            elif action == "skip":
                if etype == "sample" and c.get("incomingId"):
                    skipped_sample_ids.add(str(c.get("incomingId")))
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
                    touched_structure_project_ids.add(target_id)
            elif action == "rename_import":
                new_name = d.get("newName", "").strip()
                if new_name and ipid in incoming_projects_by_id:
                    inc_proj = incoming_projects_by_id[ipid]
                    inc_proj["name"] = new_name
                    project = _normalize_project(inc_proj)
                    curr_projects[ipid] = project
                    stats["projectsAdded"] += 1
                    project_id_map[ipid] = ipid
                    stage_count, task_count, stage_ids = _register_imported_project_tree(project, stage_id_map, task_id_map)
                    stats["stagesAdded"] += stage_count
                    stats["tasksAdded"] += task_count
                    fully_imported_stage_ids.update(stage_ids)
                    touched_structure_project_ids.add(ipid)
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
                                touched_structure_project_ids.add(proj_id)
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
                                stage = copy.deepcopy(inc_stage)
                                curr_projects[target_pid].setdefault("stages", []).append(stage)
                                stats["stagesAdded"] += 1
                                _, task_count, stage_id = _register_imported_stage_tree(stage, stage_id_map, task_id_map)
                                stats["tasksAdded"] += task_count
                                if stage_id:
                                    fully_imported_stage_ids.add(stage_id)
                                touched_structure_project_ids.add(target_pid)
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
                                    touched_structure_project_ids.add(proj_id)
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
                                                touched_structure_project_ids.add(target_pid)
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
                                stats["samplesMerged"] += 1
                                sample_id_map[inc_id] = target_id
                                break
            elif action == "import_as_new_with_identity_edit":
                inc_id = c.get("incomingId")
                new_sn = d.get("newSN", "").strip()
                new_imei = d.get("newIMEI", "").strip()
                new_board_sn = d.get("newBoardSn", "").strip()
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
                    if new_board_sn:
                        inc_sample["boardSn"] = new_board_sn
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
                if c.get("incomingId"):
                    skipped_sample_ids.add(str(c.get("incomingId")))
                stats["skipped"] += 1

    incoming_sample_ids = {
        str(sample.get("id"))
        for cat in (incoming.get("sampleLibrary") or {}).get("categories") or []
        for sample in (cat.get("samples") or [])
        if sample.get("id")
    }
    current_sample_ids = {
        str(sample.get("id"))
        for cat in curr_categories.values()
        for sample in (cat.get("samples") or [])
        if sample.get("id")
    }
    for sid in incoming_sample_ids:
        if sid in current_sample_ids and sid not in skipped_sample_ids:
            sample_id_map.setdefault(sid, sid)

    current_data["sampleLibrary"]["categories"] = list(curr_categories.values())
    current_data["projects"] = list(curr_projects.values())

    merged_photos, _ = _merge_import_sample_subrecords(current_data, incoming, sample_id_map)
    stats["photosAdded"] += merged_photos
    incoming_samples_by_id = _sample_index_by_id(incoming)
    incoming_photo_ids_by_target: dict[str, set[str]] = {}
    for inc_sid, target_sid in sample_id_map.items():
        inc_sample = incoming_samples_by_id.get(inc_sid)
        if not inc_sample:
            continue
        photo_ids = {
            str(photo.get("id"))
            for photo in (inc_sample.get("photos") or [])
            if photo.get("id")
        }
        if photo_ids:
            incoming_photo_ids_by_target.setdefault(target_sid, set()).update(photo_ids)

    # ── 复制照片资产文件（经 sample_id_map 定位源文件）──
    # 反向映射：target sample ID → incoming sample ID
    target_to_incoming_sample: dict[str, str] = {v: k for k, v in sample_id_map.items()}
    for cat in curr_categories.values():
        for sample in cat.get("samples") or []:
            target_sid = sample.get("id", "")
            incoming_photo_ids = incoming_photo_ids_by_target.get(target_sid, set())
            # 查找照片在导入包中对应的 incoming 样机 ID
            inc_sid = target_to_incoming_sample.get(target_sid, target_sid)
            for photo in sample.get("photos") or []:
                photo_id = photo.get("id", "")
                if photo_id not in incoming_photo_ids:
                    continue
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
    stats["sampleEventsAdded"] = _merge_import_sample_events(
        current_data, incoming, project_id_map, stage_id_map, task_id_map, sample_id_map
    )
    validation_errors = _validate_import_commit_state(current_data, touched_structure_project_ids)
    if validation_errors:
        _cleanup_preview_temp(preview_id)
        del _IMPORT_PREVIEWS[preview_id]
        return {
            "ok": False,
            "error": "导入后数据一致性校验失败：" + "；".join(validation_errors[:3]),
            "error_code": "IMPORT_STATE_VALIDATION_FAILED",
            "validationErrors": validation_errors,
            "status": 400,
        }

    import_remark = f"导入数据包 (deployment={source_manifest.get('sourceDeploymentId','?')})"
    ok, resp = save_state(current_data, preview_revision, "import-bundle", remark=import_remark, user="数据导入")

    if not ok:
        _cleanup_preview_temp(preview_id)
        del _IMPORT_PREVIEWS[preview_id]
        return {"ok": False, "error": resp.get("error", "写入失败"), "status": resp.get("status", 500)}

    _cleanup_preview_temp(preview_id)
    del _IMPORT_PREVIEWS[preview_id]

    revision = resp.get("revision", 0)
    mutation_summary = _build_import_mutation_summary(
        current_data,
        project_id_map,
        stage_id_map,
        task_id_map,
        sample_id_map,
        touched_structure_project_ids,
    )
    return {
        "ok": True,
        "stats": stats,
        "revision": revision,
        "newRevision": revision,
        "updated_at": resp.get("updated_at", ""),
        "mutationSummary": mutation_summary,
    }


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


def _register_imported_stage_tree(stage: dict, stage_id_map: dict[str, str],
                                  task_id_map: dict[str, str]) -> tuple[int, int, str | None]:
    """Register IDs for an imported full stage subtree."""
    sid = str(stage.get("id") or "")
    if sid:
        stage_id_map[sid] = sid
    task_count = 0
    for task in stage.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        task_count += 1
        tid = str(task.get("id") or "")
        if tid:
            task_id_map[tid] = tid
    return 1, task_count, sid or None


def _register_imported_project_tree(project: dict, stage_id_map: dict[str, str],
                                    task_id_map: dict[str, str]) -> tuple[int, int, set[str]]:
    """Register IDs for an imported full project subtree."""
    stage_count = 0
    task_count = 0
    stage_ids: set[str] = set()
    for stage in project.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        added_stage_count, added_task_count, sid = _register_imported_stage_tree(stage, stage_id_map, task_id_map)
        stage_count += added_stage_count
        task_count += added_task_count
        if sid:
            stage_ids.add(sid)
    return stage_count, task_count, stage_ids


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


def _validate_import_commit_state(data: dict, project_ids: set[str]) -> list[str]:
    """Validate imported project subtrees before writing them to storage."""
    if not project_ids:
        return []
    target_project_ids = {str(pid) for pid in project_ids if pid}
    sample_ids = {
        str(sample.get("id"))
        for cat in (data.get("sampleLibrary") or {}).get("categories") or []
        for sample in (cat.get("samples") or [])
        if isinstance(sample, dict) and sample.get("id")
    }
    errors: list[str] = []

    for project in data.get("projects") or []:
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("id") or "")
        if project_id not in target_project_ids:
            continue
        seen_stage_ids: set[str] = set()
        for stage in project.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            stage_id = str(stage.get("id") or "")
            if stage_id:
                if stage_id in seen_stage_ids:
                    errors.append(f"项目 {project_id} 内阶段 ID 重复: {stage_id}")
                seen_stage_ids.add(stage_id)
            seen_task_ids: set[str] = set()
            for task in stage.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                task_id = str(task.get("id") or "")
                if task_id:
                    if task_id in seen_task_ids:
                        errors.append(f"阶段 {stage_id or '(无ID)'} 内任务 ID 重复: {task_id}")
                    seen_task_ids.add(task_id)
                for sample_id in task.get("sampleIds") or []:
                    sid = str(sample_id or "")
                    if sid and sid not in sample_ids:
                        errors.append(f"任务 {task_id or '(无ID)'} 引用不存在的样机: {sid}")
                if len(errors) >= 20:
                    return errors
    return errors


def _remap_log_ids(log: dict, project_id_map: dict, stage_id_map: dict,
                   task_id_map: dict, sample_id_map: dict) -> None:
    """重映射单条日志中的 ID 引用"""
    for field, id_map in [("sampleId", sample_id_map), ("projectId", project_id_map),
                           ("stageId", stage_id_map), ("taskId", task_id_map)]:
        old_val = log.get(field)
        if old_val and old_val in id_map:
            log[field] = id_map[old_val]


def _sample_index_by_id(data: dict) -> dict[str, dict]:
    samples: dict[str, dict] = {}
    for cat in (data.get("sampleLibrary") or {}).get("categories") or []:
        for sample in cat.get("samples") or []:
            if isinstance(sample, dict) and sample.get("id"):
                samples[str(sample.get("id"))] = sample
    return samples


def _merge_import_sample_subrecords(current_data: dict, incoming: dict,
                                    sample_id_map: dict[str, str]) -> tuple[int, int]:
    """Merge photo metadata and problem records for imported or mapped samples."""
    current_samples = _sample_index_by_id(current_data)
    incoming_samples = _sample_index_by_id(incoming)
    photos_added = 0
    problems_added = 0

    for inc_sid, target_sid in sample_id_map.items():
        inc_sample = incoming_samples.get(inc_sid)
        target_sample = current_samples.get(target_sid)
        if not inc_sample or not target_sample:
            continue

        existing_photo_ids = {
            str(photo.get("id"))
            for photo in (target_sample.get("photos") or [])
            if isinstance(photo, dict) and photo.get("id")
        }
        existing_photo_hashes = {
            _content_hash(photo)
            for photo in (target_sample.get("photos") or [])
            if isinstance(photo, dict)
        }
        for photo in inc_sample.get("photos") or []:
            if not isinstance(photo, dict):
                continue
            photo_id = str(photo.get("id") or "")
            photo_hash = _content_hash(photo)
            if (photo_id and photo_id in existing_photo_ids) or photo_hash in existing_photo_hashes:
                continue
            target_sample.setdefault("photos", []).append(copy.deepcopy(photo))
            if photo_id:
                existing_photo_ids.add(photo_id)
            existing_photo_hashes.add(photo_hash)
            photos_added += 1

        existing_problem_hashes = {
            _content_hash(record)
            for record in (target_sample.get("problemRecords") or [])
            if isinstance(record, dict)
        }
        for record in inc_sample.get("problemRecords") or []:
            if not isinstance(record, dict):
                continue
            record_hash = _content_hash(record)
            if record_hash in existing_problem_hashes:
                continue
            target_sample.setdefault("problemRecords", []).append(copy.deepcopy(record))
            existing_problem_hashes.add(record_hash)
            problems_added += 1

    return photos_added, problems_added


def _merge_import_sample_events(current_data: dict, incoming: dict,
                                project_id_map: dict[str, str], stage_id_map: dict[str, str],
                                task_id_map: dict[str, str], sample_id_map: dict[str, str]) -> int:
    """Merge library-level sample events after import ID maps are known."""
    library = current_data.setdefault("sampleLibrary", {})
    logs = library.get("logs")
    if not isinstance(logs, list):
        logs = []
        library["logs"] = logs

    target_sample_ids = set(_sample_index_by_id(current_data).keys())
    existing_hashes = {
        _content_hash(log)
        for log in logs
        if isinstance(log, dict)
    }
    added = 0

    for raw in (incoming.get("sampleLibrary") or {}).get("logs") or []:
        if not isinstance(raw, dict):
            continue
        inc_sid = str(raw.get("sampleId") or "")
        if inc_sid and inc_sid not in sample_id_map:
            continue

        log = copy.deepcopy(raw)
        _remap_log_ids(log, project_id_map, stage_id_map, task_id_map, sample_id_map)
        target_sid = str(log.get("sampleId") or "")
        if target_sid and target_sid not in target_sample_ids:
            continue

        event_hash = _content_hash(log)
        if event_hash in existing_hashes:
            continue
        logs.append(log)
        existing_hashes.add(event_hash)
        added += 1

    return added


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
            hydrate_externalized_sample_fields(new_data, current_data)

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


def commit_sample_asset_mutation(
    conn: sqlite3.Connection,
    sample_id: str,
    action: str,
    remark: str,
    client_ip: str,
    *,
    user: str = "",
) -> dict:
    state_row = conn.execute("SELECT data_json, revision FROM app_state WHERE id = 1").fetchone()
    current_revision = int(state_row["revision"]) if state_row else 1
    new_revision = current_revision + 1
    updated_at = now_iso()

    sample_row = conn.execute(
        "SELECT data_json FROM sample_records WHERE id = ? AND deleted_at IS NULL",
        (sample_id,),
    ).fetchone()
    if not sample_row:
        raise KeyError("样机不存在")
    sample_json = json_obj(sample_row["data_json"], {}) or {}
    sample_json["updatedAt"] = updated_at
    conn.execute(
        "UPDATE sample_records SET data_json = ?, updated_at = ? WHERE id = ?",
        (json_dumps(sample_json), updated_at, sample_id),
    )

    stored = json_obj(state_row["data_json"] if state_row else None, {}) or split_state_for_storage(empty_data())
    stored["version"] = APP_VERSION
    if state_row:
        conn.execute(
            "UPDATE app_state SET data_json = ?, revision = ?, updated_at = ? WHERE id = 1",
            (json_dumps(stored), new_revision, updated_at),
        )
    else:
        conn.execute(
            "INSERT INTO app_state (id, data_json, revision, updated_at) VALUES (1, ?, ?, ?)",
            (json_dumps(stored), new_revision, updated_at),
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
    return {"revision": new_revision, "updated_at": updated_at, "photos": load_sample_photos(conn, sample_id)}


def write_task_logs(conn: sqlite3.Connection, task: dict, project_id: str, stage_id: str) -> None:
    task_id = str(task.get("id") or "")
    conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
    seen_log_ids: set[str] = set()
    for log in task.get("logs", []) or []:
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


def upsert_task_record(conn: sqlite3.Connection, task: dict, project_id: str, stage_id: str, *, create_if_missing: bool = False) -> None:
    task_id = str(task.get("id") or "")
    existing = conn.execute(
        "SELECT id FROM project_tasks WHERE id = ? AND deleted_at IS NULL",
        (task_id,),
    ).fetchone()
    if not existing and not create_if_missing:
        raise KeyError("任务不存在")
    sample_ids = [str(x) for x in (task.get("sampleIds") or [])]
    task_json = copy.deepcopy(task)
    task_json.pop("logs", None)
    if existing:
        conn.execute(
            """
            UPDATE project_tasks
            SET project_id = ?, stage_id = ?, progress_id = ?, category = ?, test_item = ?,
                sku_index = ?, status = ?, flow_status = ?, owner = ?, sample_ids_json = ?, data_json = ?,
                updated_at = ?, completed_at = ?
            WHERE id = ? AND deleted_at IS NULL
            """,
            (
                project_id,
                stage_id,
                str(task.get("progressId") or ""),
                str(task.get("category") or ""),
                str(task.get("testItem") or ""),
                to_int(task.get("skuIndex")),
                str(task.get("status") or ""),
                task_flow_status(task),
                str(task.get("owner") or ""),
                json_dumps(sample_ids),
                json_dumps(task_json),
                str(task.get("updatedAt") or now_iso()),
                str(task.get("completedAt") or task.get("endDate") or ""),
                task_id,
            ),
        )
    else:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO project_tasks
            (id, project_id, stage_id, progress_id, category, test_item, sku_index, status, flow_status, owner,
             sample_ids_json, data_json, created_at, updated_at, completed_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
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
                task_flow_status(task),
                str(task.get("owner") or ""),
                json_dumps(sample_ids),
                json_dumps(task_json),
                str(task.get("createdAt") or ts),
                str(task.get("updatedAt") or ts),
                str(task.get("completedAt") or task.get("endDate") or ""),
            ),
        )
    write_task_logs(conn, task, project_id, stage_id)
    replace_task_sample_links(conn, task_id, project_id, stage_id, task, sample_ids)


def delete_task_record(conn: sqlite3.Connection, task_id: str) -> None:
    conn.execute("DELETE FROM task_logs WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM project_task_samples WHERE task_id = ?", (task_id,))
    conn.execute("DELETE FROM project_tasks WHERE id = ?", (task_id,))


def update_project_record(conn: sqlite3.Connection, project: dict, *, create_if_missing: bool = False, sort_order: int | None = None) -> None:
    if not isinstance(project, dict) or not project:
        return
    project_id = str(project.get("id") or "")
    if not project_id:
        return
    existing = conn.execute(
        "SELECT id, sort_order FROM project_records WHERE id = ? AND deleted_at IS NULL",
        (project_id,),
    ).fetchone()
    if not existing and not create_if_missing:
        raise KeyError(f"项目不存在: {project_id}")
    if sort_order is None:
        if existing:
            sort_order = int(existing["sort_order"] or 0)
        else:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM project_records").fetchone()
            sort_order = int(row["next_order"] or 0)
    project_json = copy.deepcopy(project)
    project_json["id"] = project_id
    project_json.pop("stages", None)
    if existing:
        conn.execute(
            """
            UPDATE project_records
            SET name = ?, code = ?, owner = ?, sort_order = ?, data_json = ?, updated_at = ?, deleted_at = NULL
            WHERE id = ?
            """,
            (
                str(project.get("name") or "Untitled Project"),
                str(project.get("code") or ""),
                str(project.get("owner") or project.get("leader") or project.get("manager") or ""),
                sort_order,
                json_dumps(project_json),
                str(project.get("updatedAt") or now_iso()),
                project_id,
            ),
        )
    else:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO project_records
            (id, name, code, owner, sort_order, data_json, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                project_id,
                str(project.get("name") or "Untitled Project"),
                str(project.get("code") or ""),
                str(project.get("owner") or project.get("leader") or project.get("manager") or ""),
                sort_order,
                json_dumps(project_json),
                str(project.get("createdAt") or ts),
                str(project.get("updatedAt") or ts),
            ),
        )


def delete_project_record(conn: sqlite3.Connection, project_id: str) -> None:
    row = conn.execute(
        "SELECT id FROM project_records WHERE id = ? AND deleted_at IS NULL",
        (project_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"项目不存在: {project_id}")
    task_rows = conn.execute("SELECT id FROM project_tasks WHERE project_id = ?", (project_id,)).fetchall()
    task_ids = [str(row["id"] or "") for row in task_rows if row["id"]]
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        conn.execute(f"DELETE FROM task_logs WHERE task_id IN ({placeholders})", task_ids)
        conn.execute(f"DELETE FROM project_task_samples WHERE task_id IN ({placeholders})", task_ids)
    conn.execute("DELETE FROM project_tasks WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM project_stages WHERE project_id = ?", (project_id,))
    conn.execute("DELETE FROM project_records WHERE id = ?", (project_id,))


def update_stage_record(conn: sqlite3.Connection, stage: dict, project_id: str, stage_id: str, *, create_if_missing: bool = False, sort_order: int | None = None) -> None:
    if not isinstance(stage, dict) or not stage:
        return
    existing = conn.execute(
        "SELECT id, sort_order FROM project_stages WHERE id = ? AND deleted_at IS NULL",
        (stage_id,),
    ).fetchone()
    if not existing and not create_if_missing:
        raise KeyError(f"阶段不存在: {stage_id}")
    if sort_order is None:
        if existing:
            sort_order = int(existing["sort_order"] or 0)
        else:
            row = conn.execute(
                "SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM project_stages WHERE project_id = ?",
                (project_id,),
            ).fetchone()
            sort_order = int(row["next_order"] or 0)
    stage_json = copy.deepcopy(stage)
    stage_json["id"] = stage_id
    stage_json["projectId"] = project_id
    stage_json.pop("tasks", None)
    if existing:
        conn.execute(
            """
            UPDATE project_stages
            SET project_id = ?, name = ?, sort_order = ?, data_json = ?, updated_at = ?, deleted_at = NULL
            WHERE id = ?
            """,
            (
                project_id,
                str(stage.get("name") or "Untitled Stage"),
                sort_order,
                json_dumps(stage_json),
                str(stage.get("updatedAt") or now_iso()),
                stage_id,
            ),
        )
    else:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO project_stages
            (id, project_id, name, sort_order, data_json, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                stage_id,
                project_id,
                str(stage.get("name") or "Untitled Stage"),
                sort_order,
                json_dumps(stage_json),
                str(stage.get("createdAt") or ts),
                str(stage.get("updatedAt") or ts),
            ),
        )


def delete_stage_record(conn: sqlite3.Connection, stage_id: str) -> None:
    row = conn.execute(
        "SELECT id FROM project_stages WHERE id = ? AND deleted_at IS NULL",
        (stage_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"阶段不存在: {stage_id}")
    task_rows = conn.execute("SELECT id FROM project_tasks WHERE stage_id = ?", (stage_id,)).fetchall()
    task_ids = [str(row["id"] or "") for row in task_rows if row["id"]]
    if task_ids:
        placeholders = ",".join("?" for _ in task_ids)
        conn.execute(f"DELETE FROM task_logs WHERE task_id IN ({placeholders})", task_ids)
        conn.execute(f"DELETE FROM project_task_samples WHERE task_id IN ({placeholders})", task_ids)
    conn.execute("DELETE FROM project_tasks WHERE stage_id = ?", (stage_id,))
    conn.execute("DELETE FROM project_stages WHERE id = ?", (stage_id,))


def update_sample_category_record(conn: sqlite3.Connection, category: dict, *, create_if_missing: bool = False, sort_order: int | None = None) -> None:
    if not isinstance(category, dict) or not category:
        return
    category_id = str(category.get("id") or "")
    if not category_id:
        return
    existing = conn.execute(
        "SELECT id, sort_order FROM sample_categories WHERE id = ? AND deleted_at IS NULL",
        (category_id,),
    ).fetchone()
    if not existing and not create_if_missing:
        raise KeyError(f"样机池不存在: {category_id}")
    if sort_order is None:
        if existing:
            sort_order = int(existing["sort_order"] or 0)
        else:
            row = conn.execute("SELECT COALESCE(MAX(sort_order), -1) + 1 AS next_order FROM sample_categories").fetchone()
            sort_order = int(row["next_order"] or 0)
    category_json = copy.deepcopy(category)
    category_json["id"] = category_id
    category_json.pop("samples", None)
    if existing:
        conn.execute(
            """
            UPDATE sample_categories
            SET name = ?, description = ?, sort_order = ?, data_json = ?, updated_at = ?, deleted_at = NULL
            WHERE id = ?
            """,
            (
                str(category.get("name") or "未命名样机池"),
                str(category.get("description") or ""),
                sort_order,
                json_dumps(category_json),
                str(category.get("updatedAt") or now_iso()),
                category_id,
            ),
        )
    else:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO sample_categories
            (id, name, description, sort_order, data_json, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                category_id,
                str(category.get("name") or "未命名样机池"),
                str(category.get("description") or ""),
                sort_order,
                json_dumps(category_json),
                str(category.get("createdAt") or ts),
                str(category.get("updatedAt") or ts),
            ),
        )


def update_sample_record(conn: sqlite3.Connection, sample: dict, *, create_if_missing: bool = False) -> None:
    sample_id = str(sample.get("id") or "")
    if not sample_id:
        return
    row = conn.execute(
        "SELECT category_id FROM sample_records WHERE id = ? AND deleted_at IS NULL",
        (sample_id,),
    ).fetchone()
    if not row and not create_if_missing:
        raise KeyError(f"样机不存在: {sample_id}")
    category_id = str((row["category_id"] if row else None) or sample.get("categoryId") or "")
    if not category_id:
        raise KeyError(f"样机缺少 categoryId: {sample_id}")
    sample_json = copy.deepcopy(sample)
    sample_json["id"] = sample_id
    sample_json["categoryId"] = category_id
    sample_json.pop("photos", None)
    sample_json.pop("logs", None)
    for key in ("photosLoaded", "eventsLoaded", "photoCount", "effectiveStatus"):
        sample_json.pop(key, None)
    if row:
        conn.execute(
            """
            UPDATE sample_records
            SET category_id = ?, sample_no = ?, sn = ?, imei = ?, board_sn = ?, is_reassembled = ?, status = ?, has_problem = ?, effective_status = ?, location = ?,
                owner = ?, borrower = ?, data_json = ?, updated_at = ?, deleted_at = NULL
            WHERE id = ?
            """,
            (
                category_id,
                str(sample.get("sampleNo") or ""),
                str(sample.get("sn") or ""),
                str(sample.get("imei") or ""),
                str(sample.get("boardSn") or ""),
                1 if sample_is_reassembled(sample) else 0,
                str(sample.get("status") or ""),
                1 if sample_has_problem(sample) else 0,
                sample_effective_status(sample),
                str(sample.get("location") or ""),
                str(sample.get("owner") or ""),
                str(sample.get("borrower") or ""),
                json_dumps(sample_json),
                str(sample.get("updatedAt") or now_iso()),
                sample_id,
            ),
        )
    else:
        ts = now_iso()
        conn.execute(
            """
            INSERT INTO sample_records
            (id, category_id, sample_no, sn, imei, board_sn, is_reassembled, status, has_problem, effective_status, location, owner, borrower, data_json, created_at, updated_at, deleted_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL)
            """,
            (
                sample_id,
                category_id,
                str(sample.get("sampleNo") or ""),
                str(sample.get("sn") or ""),
                str(sample.get("imei") or ""),
                str(sample.get("boardSn") or ""),
                1 if sample_is_reassembled(sample) else 0,
                str(sample.get("status") or ""),
                1 if sample_has_problem(sample) else 0,
                sample_effective_status(sample),
                str(sample.get("location") or ""),
                str(sample.get("owner") or ""),
                str(sample.get("borrower") or ""),
                json_dumps(sample_json),
                str(sample.get("createdAt") or ts),
                str(sample.get("updatedAt") or ts),
            ),
        )


def upsert_sample_events(conn: sqlite3.Connection, sample_events: list[dict]) -> None:
    seen: set[str] = set()
    for log in sample_events or []:
        if not isinstance(log, dict):
            continue
        event_id = str(log.get("id") or f"event_{uuid.uuid4().hex}")
        if event_id in seen:
            continue
        seen.add(event_id)
        log["id"] = event_id
        conn.execute(
            """
            INSERT INTO sample_events
            (id, sample_id, time, event_type, project_id, stage_id, task_id, test_item, user, data_json)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(id) DO UPDATE SET
                sample_id = excluded.sample_id,
                time = excluded.time,
                event_type = excluded.event_type,
                project_id = excluded.project_id,
                stage_id = excluded.stage_id,
                task_id = excluded.task_id,
                test_item = excluded.test_item,
                user = excluded.user,
                data_json = excluded.data_json
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


def detect_task_mutation_occupancy_conflicts(
    conn: sqlite3.Connection,
    task_id: str,
    task: dict,
    project_id: str,
    stage_id: str,
) -> list[dict]:
    if task_flow_status(task) in ("正常完成", "异常终止"):
        return []
    target_sample_ids = {str(x) for x in (task.get("sampleIds") or []) if str(x)}
    if not target_sample_ids:
        return []
    placeholders = ",".join("?" for _ in target_sample_ids)
    rows = conn.execute(
        f"""
        SELECT sample_id, task_id, project_id, stage_id, test_item, status, flow_status
        FROM project_task_samples
        WHERE sample_id IN ({placeholders})
          AND task_id != ?
          AND flow_status NOT IN ('正常完成', '异常终止')
        """,
        (*target_sample_ids, task_id),
    ).fetchall()
    conflicts_by_sample: dict[str, list[dict]] = {}
    for row in rows:
        sid = str(row["sample_id"] or "")
        if not sid:
            continue
        conflicts_by_sample.setdefault(sid, []).append({
            "taskId": str(row["task_id"] or ""),
            "projectId": str(row["project_id"] or ""),
            "stageId": str(row["stage_id"] or ""),
            "testItem": str(row["test_item"] or ""),
            "status": str(row["status"] or ""),
        })
    conflicts = []
    for sid, tasks in conflicts_by_sample.items():
        conflicts.append({
            "sampleId": sid,
            "tasks": [
                {
                    "taskId": task_id,
                    "projectId": project_id,
                    "stageId": stage_id,
                    "testItem": str(task.get("testItem") or ""),
                    "status": str(task.get("status") or ""),
                },
                *tasks,
            ],
        })
    return conflicts


def task_sample_ids(task: dict) -> set[str]:
    return {str(x) for x in (task.get("sampleIds") or []) if str(x)}


def existing_task_sample_ids(conn: sqlite3.Connection, task_id: str) -> set[str]:
    row = conn.execute(
        "SELECT sample_ids_json FROM project_tasks WHERE id = ? AND deleted_at IS NULL",
        (task_id,),
    ).fetchone()
    if not row:
        return set()
    sample_ids = json_obj(row["sample_ids_json"], [])
    if not isinstance(sample_ids, list):
        return set()
    return {str(x) for x in sample_ids if str(x)}


def existing_finished_task(conn: sqlite3.Connection, task_id: str) -> dict | None:
    row = conn.execute(
        "SELECT id, status, data_json FROM project_tasks WHERE id = ? AND deleted_at IS NULL",
        (task_id,),
    ).fetchone()
    if not row:
        return None
    task = json_obj(row["data_json"], {}) or {}
    task["id"] = row["id"]
    task["status"] = row["status"] or task.get("status") or ""
    if task_flow_status(task) in ("正常完成", "异常终止"):
        return task
    return None


def sample_record_status(sample: dict) -> str:
    return str(sample.get("status") or "闲置").strip() or "闲置"


def detect_task_mutation_sample_status_blockers(
    conn: sqlite3.Connection,
    tasks: list[tuple[str, dict]],
) -> list[dict]:
    added_by_sample: dict[str, list[dict]] = {}
    for task_id, task in tasks:
        if task_flow_status(task) in ("正常完成", "异常终止"):
            continue
        added_ids = task_sample_ids(task) - existing_task_sample_ids(conn, task_id)
        for sample_id in added_ids:
            added_by_sample.setdefault(sample_id, []).append({
                "taskId": task_id,
                "testItem": str(task.get("testItem") or ""),
                "status": str(task.get("status") or ""),
            })
    if not added_by_sample:
        return []
    placeholders = ",".join("?" for _ in added_by_sample)
    rows = conn.execute(
        f"""
        SELECT id, sample_no, sn, imei, board_sn, is_reassembled, status, data_json
        FROM sample_records
        WHERE deleted_at IS NULL AND id IN ({placeholders})
        """,
        tuple(added_by_sample.keys()),
    ).fetchall()
    blockers = []
    for row in rows:
        sample = json_obj(row["data_json"], {}) or {}
        sample["id"] = row["id"]
        sample["sampleNo"] = row["sample_no"] or sample.get("sampleNo") or ""
        sample["sn"] = row["sn"] or sample.get("sn") or ""
        sample["imei"] = row["imei"] or sample.get("imei") or ""
        sample["boardSn"] = row["board_sn"] or sample.get("boardSn") or ""
        sample["isReassembled"] = bool(row["is_reassembled"]) if row["is_reassembled"] is not None else sample_is_reassembled(sample)
        sample["status"] = row["status"] or sample.get("status") or ""
        status = sample_record_status(sample)
        if status == "闲置":
            continue
        blockers.append({
            "sampleId": str(row["id"] or ""),
            "sampleNo": str(sample.get("sampleNo") or ""),
            "sn": str(sample.get("sn") or ""),
            "imei": str(sample.get("imei") or ""),
            "status": status,
            "tasks": added_by_sample.get(str(row["id"] or ""), []),
        })
    return blockers


def commit_task_mutation(payload: dict, client_ip: str) -> tuple[bool, dict]:
    task = payload.get("task")
    if not isinstance(task, dict):
        return False, {"status": 400, "error": "task 必须是 JSON 对象"}
    task_id = str(payload.get("taskId") or task.get("id") or "")
    project_id = str(payload.get("projectId") or task.get("projectId") or "")
    stage_id = str(payload.get("stageId") or task.get("stageId") or "")
    if not task_id or not project_id or not stage_id:
        return False, {"status": 400, "error": "缺少 projectId/stageId/taskId"}
    task["id"] = task_id
    task["projectId"] = project_id
    task["stageId"] = stage_id

    with DB_LOCK:
        with connect_db() as conn:
            row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            current_revision = int(row["revision"]) if row else 1
            is_delete = str(payload.get("deleteMode") or "") == "delete"
            action = str(payload.get("action") or "task_mutation")
            if action == "finish_task_result":
                finished = existing_finished_task(conn, task_id)
                if finished:
                    return False, {
                        "status": 409,
                        "error_code": "TASK_ALREADY_FINISHED",
                        "error": "任务已经结束，已拒绝重复结束请求。",
                        "taskId": task_id,
                        "taskStatus": str(finished.get("status") or ""),
                        "server_revision": current_revision,
                    }
            if not is_delete:
                status_blockers = detect_task_mutation_sample_status_blockers(conn, [(task_id, task)])
                if status_blockers:
                    return False, {
                        "status": 409,
                        "error_code": "SAMPLE_STATUS_NOT_SELECTABLE",
                        "error": "样机状态不可选：只有闲置样机可以加入测试任务，已拒绝保存。",
                        "samples": status_blockers,
                        "server_revision": current_revision,
                    }
                conflicts = detect_task_mutation_occupancy_conflicts(conn, task_id, task, project_id, stage_id)
                if conflicts:
                    return False, {
                        "status": 409,
                        "error_code": "SAMPLE_OCCUPANCY_CONFLICT",
                        "error": "样机占用冲突：同一样机被多个未完成任务占用，已拒绝保存。",
                        "conflicts": conflicts,
                        "server_revision": current_revision,
                    }

            update_stage_record(conn, payload.get("stage") or {}, project_id, stage_id)
            for sample in payload.get("samples") or []:
                if isinstance(sample, dict):
                    update_sample_record(conn, sample)
            upsert_sample_events(conn, payload.get("sampleEvents") or [])
            if is_delete:
                delete_task_record(conn, task_id)
            else:
                upsert_task_record(
                    conn,
                    task,
                    project_id,
                    stage_id,
                    create_if_missing=bool(payload.get("createIfMissing")),
                )

            new_revision = current_revision + 1
            updated_at = now_iso()
            remark = str(payload.get("remark") or "任务增量变更")
            user = str(payload.get("user") or "")
            conn.execute(
                "UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1",
                (new_revision, updated_at),
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

    if _should_backup(action, new_revision):
        try:
            with DB_LOCK:
                with connect_db() as conn:
                    data, _, _ = compose_state(conn, include_sample_photos=False, include_sample_logs=False)
            write_backup(data, new_revision)
        except Exception as e:
            print(f"[WARN] 写入任务增量备份失败：{e}")

    return True, {"revision": new_revision, "updated_at": updated_at}


def commit_task_batch_mutation(payload: dict, client_ip: str) -> tuple[bool, dict]:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False, {"status": 400, "error": "tasks 必须是非空数组"}
    project_id = str(payload.get("projectId") or "")
    stage_id = str(payload.get("stageId") or "")
    if not project_id or not stage_id:
        return False, {"status": 400, "error": "缺少 projectId/stageId"}

    normalized_tasks: list[dict] = []
    seen_task_ids: set[str] = set()
    for task in tasks:
        if not isinstance(task, dict):
            return False, {"status": 400, "error": "tasks 中每一项都必须是 JSON 对象"}
        task_id = str(task.get("id") or "")
        if not task_id:
            return False, {"status": 400, "error": "任务缺少 id"}
        if task_id in seen_task_ids:
            return False, {"status": 400, "error": f"任务 id 重复: {task_id}"}
        seen_task_ids.add(task_id)
        task["id"] = task_id
        task["projectId"] = project_id
        task["stageId"] = stage_id
        normalized_tasks.append(task)

    with DB_LOCK:
        with connect_db() as conn:
            row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            current_revision = int(row["revision"]) if row else 1
            stage_row = conn.execute(
                """
                SELECT id
                FROM project_stages
                WHERE id = ? AND project_id = ? AND deleted_at IS NULL
                """,
                (stage_id, project_id),
            ).fetchone()
            if not stage_row:
                return False, {"status": 404, "error": f"阶段不存在: {stage_id}"}

            status_blockers = detect_task_mutation_sample_status_blockers(
                conn,
                [(str(task.get("id") or ""), task) for task in normalized_tasks],
            )
            if status_blockers:
                return False, {
                    "status": 409,
                    "error_code": "SAMPLE_STATUS_NOT_SELECTABLE",
                    "error": "样机状态不可选：只有闲置样机可以加入测试任务，已拒绝保存。",
                    "samples": status_blockers,
                    "server_revision": current_revision,
                }

            update_stage_record(conn, payload.get("stage") or {}, project_id, stage_id)
            create_if_missing = bool(payload.get("createIfMissing"))
            for task in normalized_tasks:
                upsert_task_record(
                    conn,
                    task,
                    project_id,
                    stage_id,
                    create_if_missing=create_if_missing,
                )

            new_revision = current_revision + 1
            updated_at = now_iso()
            action = str(payload.get("action") or "task_batch_mutation")
            remark = str(payload.get("remark") or f"批量任务增量变更：{len(normalized_tasks)} 个")
            user = str(payload.get("user") or "")
            conn.execute(
                "UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1",
                (new_revision, updated_at),
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

    if _should_backup(action, new_revision):
        try:
            with DB_LOCK:
                with connect_db() as conn:
                    data, _, _ = compose_state(conn, include_sample_photos=False, include_sample_logs=False)
            write_backup(data, new_revision)
        except Exception as e:
            print(f"[WARN] 写入批量任务增量备份失败：{e}")

    return True, {"revision": new_revision, "updated_at": updated_at, "count": len(normalized_tasks)}


def commit_sample_mutation(payload: dict, client_ip: str) -> tuple[bool, dict]:
    sample_id = str(payload.get("sampleId") or (payload.get("sample") or {}).get("id") or "")
    if not sample_id:
        return False, {"status": 400, "error": "缺少 sampleId"}
    delete_sample = bool(payload.get("deleteSample"))

    with DB_LOCK:
        with connect_db() as conn:
            row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            current_revision = int(row["revision"]) if row else 1

            for item in payload.get("taskMutations") or []:
                if not isinstance(item, dict):
                    continue
                task = item.get("task")
                if not isinstance(task, dict):
                    continue
                project_id = str(item.get("projectId") or task.get("projectId") or "")
                stage_id = str(item.get("stageId") or task.get("stageId") or "")
                task_id = str(item.get("taskId") or task.get("id") or "")
                if not project_id or not stage_id or not task_id:
                    continue
                update_stage_record(conn, item.get("stage") or {}, project_id, stage_id)
                upsert_task_record(
                    conn,
                    task,
                    project_id,
                    stage_id,
                    create_if_missing=bool(item.get("createIfMissing")),
                )

            for sample in payload.get("samples") or []:
                if isinstance(sample, dict) and str(sample.get("id") or "") != sample_id:
                    update_sample_record(conn, sample)

            sample = payload.get("sample")
            if isinstance(sample, dict) and not delete_sample:
                update_sample_record(conn, sample)

            upsert_sample_events(conn, payload.get("sampleEvents") or [])

            if delete_sample:
                cleanup_sample_asset_files(conn, [sample_id])
                conn.execute("DELETE FROM sample_assets WHERE sample_id = ?", (sample_id,))
                conn.execute("DELETE FROM sample_events WHERE sample_id = ?", (sample_id,))
                conn.execute("DELETE FROM sample_records WHERE id = ?", (sample_id,))

            new_revision = current_revision + 1
            updated_at = now_iso()
            action = str(payload.get("action") or ("destroy_sample" if delete_sample else "sample_mutation"))
            remark = str(payload.get("remark") or ("样机档案销毁" if delete_sample else "样机增量变更"))
            user = str(payload.get("user") or "")
            conn.execute(
                "UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1",
                (new_revision, updated_at),
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

    return True, {"revision": new_revision, "updated_at": updated_at}


def commit_project_mutation(payload: dict, client_ip: str) -> tuple[bool, dict]:
    project = payload.get("project")
    project_id = str(payload.get("projectId") or (project or {}).get("id") or "")
    if not project_id:
        return False, {"status": 400, "error": "缺少 projectId"}
    delete_project = bool(payload.get("deleteProject"))

    with DB_LOCK:
        with connect_db() as conn:
            row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            current_revision = int(row["revision"]) if row else 1

            for sample in payload.get("samples") or []:
                if isinstance(sample, dict):
                    update_sample_record(conn, sample)
            upsert_sample_events(conn, payload.get("sampleEvents") or [])

            if delete_project:
                delete_project_record(conn, project_id)
            else:
                if not isinstance(project, dict):
                    return False, {"status": 400, "error": "project 必须是 JSON 对象"}
                project["id"] = project_id
                update_project_record(
                    conn,
                    project,
                    create_if_missing=bool(payload.get("createIfMissing")),
                    sort_order=to_int(payload.get("sortOrder")) if payload.get("sortOrder") is not None else None,
                )

            new_revision = current_revision + 1
            updated_at = now_iso()
            action = str(payload.get("action") or ("delete_project" if delete_project else "project_mutation"))
            remark = str(payload.get("remark") or ("删除项目" if delete_project else "项目增量变更"))
            user = str(payload.get("user") or "")
            conn.execute(
                "UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1",
                (new_revision, updated_at),
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

    return True, {"revision": new_revision, "updated_at": updated_at}


def commit_stage_mutation(payload: dict, client_ip: str) -> tuple[bool, dict]:
    stage = payload.get("stage")
    stage_id = str(payload.get("stageId") or (stage or {}).get("id") or "")
    project_id = str(payload.get("projectId") or (stage or {}).get("projectId") or "")
    if not stage_id or not project_id:
        return False, {"status": 400, "error": "缺少 projectId/stageId"}
    delete_stage = bool(payload.get("deleteStage"))

    with DB_LOCK:
        with connect_db() as conn:
            row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            current_revision = int(row["revision"]) if row else 1

            project = payload.get("project")
            if isinstance(project, dict):
                project["id"] = project_id
                update_project_record(conn, project)

            for sample in payload.get("samples") or []:
                if isinstance(sample, dict):
                    update_sample_record(conn, sample)
            upsert_sample_events(conn, payload.get("sampleEvents") or [])

            if delete_stage:
                delete_stage_record(conn, stage_id)
                for idx, sibling in enumerate(payload.get("stages") or []):
                    if isinstance(sibling, dict) and str(sibling.get("id") or "") != stage_id:
                        update_stage_record(conn, sibling, project_id, str(sibling.get("id") or ""), sort_order=idx)
            else:
                if not isinstance(stage, dict):
                    return False, {"status": 400, "error": "stage 必须是 JSON 对象"}
                stage["id"] = stage_id
                stage["projectId"] = project_id
                sibling_ids = [str(s.get("id") or "") for s in (payload.get("stages") or []) if isinstance(s, dict)]
                sort_order = sibling_ids.index(stage_id) if stage_id in sibling_ids else None
                update_stage_record(
                    conn,
                    stage,
                    project_id,
                    stage_id,
                    create_if_missing=bool(payload.get("createIfMissing")),
                    sort_order=sort_order,
                )
                for idx, sibling in enumerate(payload.get("stages") or []):
                    if isinstance(sibling, dict) and str(sibling.get("id") or "") != stage_id:
                        sid = str(sibling.get("id") or "")
                        if sid:
                            update_stage_record(conn, sibling, project_id, sid, sort_order=idx)

            new_revision = current_revision + 1
            updated_at = now_iso()
            action = str(payload.get("action") or ("delete_stage" if delete_stage else "stage_mutation"))
            remark = str(payload.get("remark") or ("删除阶段" if delete_stage else "阶段增量变更"))
            user = str(payload.get("user") or "")
            conn.execute(
                "UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1",
                (new_revision, updated_at),
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

    return True, {"revision": new_revision, "updated_at": updated_at}


def delete_sample_category_record(conn: sqlite3.Connection, category_id: str) -> None:
    row = conn.execute(
        "SELECT id FROM sample_categories WHERE id = ? AND deleted_at IS NULL",
        (category_id,),
    ).fetchone()
    if not row:
        raise KeyError(f"样机池不存在: {category_id}")
    sample_rows = conn.execute(
        "SELECT id FROM sample_records WHERE category_id = ? AND deleted_at IS NULL",
        (category_id,),
    ).fetchall()
    sample_ids = [str(row["id"] or "") for row in sample_rows if row["id"]]
    cleanup_sample_asset_files(conn, sample_ids)
    if sample_ids:
        placeholders = ",".join("?" for _ in sample_ids)
        conn.execute(f"DELETE FROM sample_assets WHERE sample_id IN ({placeholders})", sample_ids)
        conn.execute(f"DELETE FROM sample_events WHERE sample_id IN ({placeholders})", sample_ids)
        conn.execute(f"DELETE FROM sample_records WHERE id IN ({placeholders})", sample_ids)
    conn.execute("DELETE FROM sample_categories WHERE id = ?", (category_id,))


def commit_sample_category_mutation(payload: dict, client_ip: str) -> tuple[bool, dict]:
    category_id = str(payload.get("categoryId") or (payload.get("category") or {}).get("id") or "")
    if not category_id:
        return False, {"status": 400, "error": "缺少 categoryId"}
    delete_category = bool(payload.get("deleteCategory"))

    with DB_LOCK:
        with connect_db() as conn:
            row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
            current_revision = int(row["revision"]) if row else 1

            if not delete_category:
                category = payload.get("category")
                if not isinstance(category, dict):
                    return False, {"status": 400, "error": "category 必须是 JSON 对象"}
                category["id"] = category_id
                update_sample_category_record(
                    conn,
                    category,
                    create_if_missing=bool(payload.get("createIfMissing")),
                    sort_order=to_int(payload.get("sortOrder")) if payload.get("sortOrder") is not None else None,
                )

            for item in payload.get("taskMutations") or []:
                if not isinstance(item, dict):
                    continue
                task = item.get("task")
                if not isinstance(task, dict):
                    continue
                project_id = str(item.get("projectId") or task.get("projectId") or "")
                stage_id = str(item.get("stageId") or task.get("stageId") or "")
                task_id = str(item.get("taskId") or task.get("id") or "")
                if not project_id or not stage_id or not task_id:
                    continue
                update_stage_record(conn, item.get("stage") or {}, project_id, stage_id)
                upsert_task_record(
                    conn,
                    task,
                    project_id,
                    stage_id,
                    create_if_missing=bool(item.get("createIfMissing")),
                )

            for sample in payload.get("samples") or []:
                if isinstance(sample, dict):
                    update_sample_record(
                        conn,
                        sample,
                        create_if_missing=bool(payload.get("createSamples") or payload.get("createIfMissing")),
                    )
            upsert_sample_events(conn, payload.get("sampleEvents") or [])

            if delete_category:
                delete_sample_category_record(conn, category_id)

            new_revision = current_revision + 1
            updated_at = now_iso()
            action = str(payload.get("action") or ("destroy_sample_category" if delete_category else "sample_category_mutation"))
            remark = str(payload.get("remark") or ("样机池档案销毁" if delete_category else "样机池增量变更"))
            user = str(payload.get("user") or "")
            conn.execute(
                "UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1",
                (new_revision, updated_at),
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

    return True, {"revision": new_revision, "updated_at": updated_at}


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

    def _send_file(self, target: Path, content_type: str, *, cache: str = "public, max-age=86400, must-revalidate") -> None:
        stat = target.stat()
        etag = f'"{stat.st_mtime_ns:x}-{stat.st_size:x}"'
        if self.headers.get("If-None-Match") == etag:
            self.send_response(304)
            self.send_header("ETag", etag)
            self.send_header("Cache-Control", cache)
            self.end_headers()
            return
        data = target.read_bytes()
        self.send_response(200)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(len(data)))
        self.send_header("Cache-Control", cache)
        self.send_header("ETag", etag)
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

    def _sample_events_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "samples" and parts[3] == "events":
            return unquote(parts[2])
        return None

    def _sample_history_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "samples" and parts[3] == "history":
            return unquote(parts[2])
        return None

    def _stage_tasks_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "stages" and parts[3] == "tasks":
            return unquote(parts[2])
        return None

    def _stage_tasks_batch_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 5 and parts[0] == "api" and parts[1] == "stages" and parts[3] == "tasks" and parts[4] == "batch":
            return unquote(parts[2])
        return None

    def _project_detail_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "projects" and parts[2] != "summary":
            return unquote(parts[2])
        return None

    def _project_mutation_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "projects" and parts[3] == "mutation":
            return unquote(parts[2])
        return None

    def _stage_mutation_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "stages" and parts[3] == "mutation":
            return unquote(parts[2])
        return None

    def _sample_category_samples_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "sample-categories" and parts[3] == "samples":
            return unquote(parts[2])
        return None

    def _sample_category_detail_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 3 and parts[0] == "api" and parts[1] == "sample-categories":
            return unquote(parts[2])
        return None

    def _task_mutation_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "tasks" and parts[3] == "mutation":
            return unquote(parts[2])
        return None

    def _sample_mutation_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "samples" and parts[3] == "mutation":
            return unquote(parts[2])
        return None

    def _sample_category_mutation_route(self, path: str) -> str | None:
        parts = path.strip("/").split("/")
        if len(parts) == 4 and parts[0] == "api" and parts[1] == "sample-categories" and parts[3] == "mutation":
            return unquote(parts[2])
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
        query = parse_qs(parsed.query, keep_blank_values=True)

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
                data, revision, updated_at = get_state(compact=True)
                self._send_json({"ok": True, "revision": revision, "updated_at": updated_at, "data": data})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/bootstrap":
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        data, revision, updated_at = compose_bootstrap_state(conn)
                self._send_json({"ok": True, "revision": revision, "updated_at": updated_at, "data": data, "partial": True})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/projects/summary":
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        projects = list_project_summary(conn)
                self._send_json({"ok": True, "projects": projects, "count": len(projects)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        project_detail_id = self._project_detail_route(path)
        if project_detail_id:
            try:
                include_tasks = first_query_value(query, "includeTasks", "") in ("1", "true", "yes")
                with DB_LOCK:
                    with connect_db() as conn:
                        project = load_project_detail(conn, project_detail_id, include_tasks=include_tasks)
                if not project:
                    self._send_json({"ok": False, "error": "项目不存在"}, 404)
                    return
                self._send_json({"ok": True, "project": project, "includeTasks": include_tasks})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/sample-categories":
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        categories = list_sample_categories_summary(conn)
                self._send_json({"ok": True, "categories": categories, "count": len(categories)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path == "/api/task-sample-candidates":
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        result = list_task_sample_candidates_page(conn, query)
                self._send_json({"ok": True, **result})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        sample_category_detail_id = self._sample_category_detail_route(path)
        if sample_category_detail_id:
            try:
                include_photos = first_query_value(query, "includePhotos", "") in ("1", "true", "yes")
                with DB_LOCK:
                    with connect_db() as conn:
                        category = load_sample_category_detail(conn, sample_category_detail_id, include_photos=include_photos)
                if not category:
                    self._send_json({"ok": False, "error": "样机池不存在"}, 404)
                    return
                self._send_json({"ok": True, "category": category, "includePhotos": include_photos})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        stage_tasks_id = self._stage_tasks_route(path)
        if stage_tasks_id:
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        result = list_stage_tasks_page(conn, stage_tasks_id, query)
                self._send_json({"ok": True, **result})
            except KeyError as e:
                self._send_json({"ok": False, "error": str(e)}, 404)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        sample_category_id = self._sample_category_samples_route(path)
        if sample_category_id:
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        result = list_samples_page(conn, sample_category_id, query)
                self._send_json({"ok": True, **result})
            except KeyError as e:
                self._send_json({"ok": False, "error": str(e)}, 404)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        photo_route = self._sample_photo_route(path)
        if photo_route and photo_route[1] is None:
            sample_id, _ = photo_route
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        photos = load_sample_photos(conn, sample_id)
                self._send_json({"ok": True, "sampleId": sample_id, "photos": photos, "photoCount": len(photos)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

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

        event_sample_id = self._sample_events_route(path)
        if event_sample_id:
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        logs = load_sample_events(conn, event_sample_id)
                self._send_json({"ok": True, "sampleId": event_sample_id, "logs": logs, "count": len(logs)})
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        history_sample_id = self._sample_history_route(path)
        if history_sample_id:
            try:
                with DB_LOCK:
                    with connect_db() as conn:
                        result = list_sample_history_page(conn, history_sample_id, query)
                self._send_json({"ok": True, **result})
            except KeyError as e:
                self._send_json({"ok": False, "error": str(e)}, 404)
            except Exception as e:
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        if path in ("/", "/index.html"):
            if not INDEX_PATH.exists():
                self._send_json({"ok": False, "error": "index.html 不存在"}, 404)
                return
            self._send_file(INDEX_PATH, "text/html; charset=utf-8", cache="no-cache")
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
            self._send_file(target, content_type)
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

        if path == "/api/sample-identity-check":
            try:
                payload = json.loads(self._read_body(max_bytes=MAX_UPLOAD_BYTES).decode("utf-8") or "{}")
                with DB_LOCK:
                    with connect_db() as conn:
                        result = check_sample_identity_conflicts(conn, payload)
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
                    sample_row = conn.execute(
                        "SELECT id FROM sample_records WHERE id = ? AND deleted_at IS NULL",
                        (sample_id,),
                    ).fetchone()
                    if not sample_row:
                        self._send_json({"ok": False, "error": "样机不存在"}, 404)
                        return
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
                    result = commit_sample_asset_mutation(
                        conn,
                        sample_id,
                        "upload_sample_photos",
                        fields.get("remark", "上传样机外观照片"),
                        self.client_address[0],
                    )
                    self._send_json({"ok": True, **result, "uploaded": uploaded})
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
                    sample_row = conn.execute(
                        "SELECT id FROM sample_records WHERE id = ? AND deleted_at IS NULL",
                        (sample_id,),
                    ).fetchone()
                    if not sample_row:
                        self._send_json({"ok": False, "error": "样机不存在"}, 404)
                        return
                    asset_rows = conn.execute(
                        """
                        SELECT relative_path FROM sample_assets
                        WHERE sample_id = ? AND id IN (?, ?) AND kind IN ('photo', 'photo_thumb') AND deleted_at IS NULL
                        """,
                        (sample_id, photo_id, thumbnail_asset_id(photo_id)),
                    ).fetchall()
                    if not asset_rows:
                        self._send_json({"ok": False, "error": "照片不存在"}, 404)
                        return
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
                    result = commit_sample_asset_mutation(conn, sample_id, "delete_sample_photo", "删除样机外观照片", self.client_address[0])
                    self._send_json({"ok": True, **result})
        except Exception as e:
            self._send_json({"ok": False, "error": str(e)}, 500)

    def do_PATCH(self) -> None:
        parsed = urlparse(self.path)
        path = unquote(parsed.path)
        photo_route = self._sample_photo_route(path)
        if photo_route and photo_route[1]:
            sample_id, photo_id = photo_route
            try:
                payload = json.loads(self._read_body(max_bytes=MAX_UPLOAD_BYTES).decode("utf-8") or "{}")
                name = str(payload.get("name") or "").strip()
                if not name:
                    self._send_json({"ok": False, "error": "照片名称不能为空"}, 400)
                    return
                with DB_LOCK:
                    with connect_db() as conn:
                        row = conn.execute(
                            """
                            SELECT id
                            FROM sample_assets
                            WHERE sample_id = ? AND id = ? AND kind = 'photo' AND deleted_at IS NULL
                            """,
                            (sample_id, photo_id),
                        ).fetchone()
                        if not row:
                            self._send_json({"ok": False, "error": "照片不存在"}, 404)
                            return
                        ts = now_iso()
                        conn.execute(
                            "UPDATE sample_assets SET original_name = ? WHERE sample_id = ? AND id = ? AND kind = 'photo'",
                            (name, sample_id, photo_id),
                        )
                        sample_row = conn.execute("SELECT data_json FROM sample_records WHERE id = ?", (sample_id,)).fetchone()
                        if sample_row:
                            sample = json_obj(sample_row["data_json"], {}) or {}
                            sample["updatedAt"] = ts
                            conn.execute(
                                "UPDATE sample_records SET data_json = ?, updated_at = ? WHERE id = ?",
                                (json_dumps(sample), ts, sample_id),
                            )
                        state_row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
                        current_revision = int(state_row["revision"] or 1) if state_row else 1
                        new_revision = current_revision + 1
                        conn.execute("UPDATE app_state SET revision = ?, updated_at = ? WHERE id = 1", (new_revision, ts))
                        conn.execute(
                            """
                            INSERT INTO audit_log
                            (time, user, action, remark, revision_before, revision_after, client_ip)
                            VALUES (?, ?, ?, ?, ?, ?, ?)
                            """,
                            (ts, str(payload.get("user") or "管理员"), "rename_sample_photo", f"重命名样机照片：{name}", current_revision, new_revision, self.client_address[0]),
                        )
                        photos = load_sample_photos(conn, sample_id)
                        conn.commit()
                self._send_json({"ok": True, "revision": new_revision, "updated_at": ts, "sampleId": sample_id, "photos": photos})
            except json.JSONDecodeError:
                self._send_json({"ok": False, "error": "请求体不是有效 JSON"}, 400)
            except Exception as e:
                traceback.print_exc()
                self._send_json({"ok": False, "error": str(e)}, 500)
            return

        project_id = self._project_mutation_route(path)
        stage_mutation_id = self._stage_mutation_route(path)
        stage_tasks_batch_id = self._stage_tasks_batch_route(path)
        task_id = self._task_mutation_route(path)
        sample_id = self._sample_mutation_route(path)
        category_id = self._sample_category_mutation_route(path)
        if not project_id and not stage_mutation_id and not stage_tasks_batch_id and not task_id and not sample_id and not category_id:
            self._send_json({"ok": False, "error": "Not Found"}, 404)
            return

        try:
            payload = json.loads(self._read_body(max_bytes=MAX_UPLOAD_BYTES).decode("utf-8"))
            if project_id:
                payload["projectId"] = project_id
                ok, result = commit_project_mutation(payload, self.client_address[0])
            elif stage_mutation_id:
                payload["stageId"] = stage_mutation_id
                ok, result = commit_stage_mutation(payload, self.client_address[0])
            elif stage_tasks_batch_id:
                payload["stageId"] = stage_tasks_batch_id
                ok, result = commit_task_batch_mutation(payload, self.client_address[0])
            elif task_id:
                payload["taskId"] = task_id
                ok, result = commit_task_mutation(payload, self.client_address[0])
            elif sample_id:
                payload["sampleId"] = sample_id
                ok, result = commit_sample_mutation(payload, self.client_address[0])
            else:
                payload["categoryId"] = category_id
                ok, result = commit_sample_category_mutation(payload, self.client_address[0])
            if not ok:
                self._send_json({"ok": False, **result}, int(result.get("status", 400)))
                return
            self._send_json({"ok": True, **result})
        except json.JSONDecodeError:
            self._send_json({"ok": False, "error": "请求体不是有效 JSON"}, 400)
        except KeyError as e:
            self._send_json({"ok": False, "error": str(e)}, 404)
        except ValueError as e:
            self._send_json({"ok": False, "error": str(e)}, 400)
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
