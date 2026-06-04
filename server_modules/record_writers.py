from __future__ import annotations

import copy
import json
import sqlite3
import uuid
from datetime import datetime, timezone

from server_modules import sample_assets, sample_queries, task_queries


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def json_dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


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
    ids = sample_ids if sample_ids is not None else [str(item) for item in (task.get("sampleIds") or [])]
    seen: set[str] = set()
    ts = str(task.get("updatedAt") or now_iso())
    flow_status = task_queries.task_flow_status(task)
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
    sample_ids = [str(item) for item in (task.get("sampleIds") or [])]
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
                task_queries.to_int(task.get("skuIndex")),
                str(task.get("status") or ""),
                task_queries.task_flow_status(task),
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
                task_queries.to_int(task.get("skuIndex")),
                str(task.get("status") or ""),
                task_queries.task_flow_status(task),
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
                1 if sample_queries.sample_is_reassembled(sample) else 0,
                str(sample.get("status") or ""),
                1 if sample_queries.sample_has_problem(sample) else 0,
                sample_queries.sample_effective_status(sample),
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
                1 if sample_queries.sample_is_reassembled(sample) else 0,
                str(sample.get("status") or ""),
                1 if sample_queries.sample_has_problem(sample) else 0,
                sample_queries.sample_effective_status(sample),
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


def delete_sample_category_record(conn: sqlite3.Connection, category_id: str) -> list[str]:
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
    asset_paths_to_delete = sample_assets.sample_asset_relative_paths(conn, sample_ids)
    if sample_ids:
        placeholders = ",".join("?" for _ in sample_ids)
        conn.execute(f"DELETE FROM sample_assets WHERE sample_id IN ({placeholders})", sample_ids)
        conn.execute(f"DELETE FROM sample_events WHERE sample_id IN ({placeholders})", sample_ids)
        conn.execute(f"DELETE FROM sample_records WHERE id IN ({placeholders})", sample_ids)
    conn.execute("DELETE FROM sample_categories WHERE id = ?", (category_id,))
    return asset_paths_to_delete
