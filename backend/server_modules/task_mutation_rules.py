from __future__ import annotations

import json
import sqlite3

from server_modules import sample_queries, status_normalization, task_queries


def json_obj(text: str | None, fallback: object | None = None):
    try:
        return json.loads(text or "")
    except Exception:
        return fallback


def detect_task_mutation_occupancy_conflicts(
    conn: sqlite3.Connection,
    task_id: str,
    task: dict,
    project_id: str,
    stage_id: str,
) -> list[dict]:
    if task_queries.task_flow_status(task) in ("正常完成", "异常终止"):
        return []
    target_sample_ids = {str(item) for item in (task.get("sampleIds") or []) if str(item)}
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
        sample_id = str(row["sample_id"] or "")
        if not sample_id:
            continue
        conflicts_by_sample.setdefault(sample_id, []).append({
            "taskId": str(row["task_id"] or ""),
            "projectId": str(row["project_id"] or ""),
            "stageId": str(row["stage_id"] or ""),
            "testItem": str(row["test_item"] or ""),
            "status": str(row["status"] or ""),
        })
    conflicts = []
    for sample_id, tasks in conflicts_by_sample.items():
        conflicts.append({
            "sampleId": sample_id,
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
    return {str(item) for item in (task.get("sampleIds") or []) if str(item)}


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
    return {str(item) for item in sample_ids if str(item)}


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
    if task_queries.task_flow_status(task) in ("正常完成", "异常终止"):
        return task
    return None


def sample_record_status(sample: dict) -> str:
    return status_normalization.normalize_sample_usage_status(sample.get("status") if isinstance(sample, dict) else "")


def detect_task_mutation_sample_status_blockers(
    conn: sqlite3.Connection,
    tasks: list[tuple[str, dict]],
) -> list[dict]:
    added_by_sample: dict[str, list[dict]] = {}
    for task_id, task in tasks:
        if task_queries.task_flow_status(task) in ("正常完成", "异常终止"):
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
        sample["isReassembled"] = bool(row["is_reassembled"]) if row["is_reassembled"] is not None else sample_queries.sample_is_reassembled(sample)
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
