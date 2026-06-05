from __future__ import annotations

import json
import sqlite3
from dataclasses import dataclass
from typing import Callable

from server_modules import status_normalization


@dataclass(frozen=True)
class DatabaseBackfillContext:
    json_obj: Callable
    task_flow_status: Callable[[dict], str]
    sample_has_problem: Callable[[dict], bool]
    sample_effective_status: Callable[[dict], str]
    sample_is_reassembled: Callable[[dict], bool]
    replace_task_sample_links: Callable[..., None]


def json_dumps(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def backfill_status_normalization(ctx: DatabaseBackfillContext, conn: sqlite3.Connection) -> None:
    """Canonicalize persisted status values and business status text."""
    state_rows = conn.execute("SELECT id, data_json FROM app_state").fetchall()
    for row in state_rows:
        data = ctx.json_obj(row["data_json"], {}) or {}
        normalized = status_normalization.normalize_state_payload(data)
        if normalized != data:
            conn.execute(
                "UPDATE app_state SET data_json = ? WHERE id = ?",
                (json_dumps(normalized), row["id"]),
            )

    project_rows = conn.execute("SELECT id, data_json FROM project_records").fetchall()
    for row in project_rows:
        project = ctx.json_obj(row["data_json"], {}) or {}
        normalized = status_normalization.normalize_project_payload(project)
        if normalized != project:
            conn.execute(
                "UPDATE project_records SET data_json = ? WHERE id = ?",
                (json_dumps(normalized), row["id"]),
            )

    stage_rows = conn.execute("SELECT id, data_json FROM project_stages").fetchall()
    for row in stage_rows:
        stage = ctx.json_obj(row["data_json"], {}) or {}
        normalized = status_normalization.normalize_stage_payload(stage)
        if normalized != stage:
            conn.execute(
                "UPDATE project_stages SET data_json = ? WHERE id = ?",
                (json_dumps(normalized), row["id"]),
            )

    task_rows = conn.execute(
        """
        SELECT id, status, flow_status, data_json
        FROM project_tasks
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    for row in task_rows:
        task = ctx.json_obj(row["data_json"], {}) or {}
        task["id"] = row["id"]
        task["status"] = row["status"] or task.get("status") or ""
        normalized = status_normalization.normalize_task_payload(task)
        status = status_normalization.normalize_task_stored_status(normalized)
        flow_status = ctx.task_flow_status(normalized)
        if normalized != task or str(row["status"] or "") != status or str(row["flow_status"] or "") != flow_status:
            conn.execute(
                """
                UPDATE project_tasks
                SET status = ?, flow_status = ?, data_json = ?, completed_at = COALESCE(NULLIF(completed_at, ''), ?)
                WHERE id = ?
                """,
                (
                    status,
                    flow_status,
                    json_dumps(normalized),
                    str(normalized.get("completedAt") or normalized.get("endDate") or ""),
                    row["id"],
                ),
            )

    link_rows = conn.execute(
        """
        SELECT pts.task_id, pts.sample_id, pts.status, pts.flow_status, pt.status AS task_status, pt.flow_status AS task_flow_status
        FROM project_task_samples pts
        LEFT JOIN project_tasks pt ON pt.id = pts.task_id
        """
    ).fetchall()
    for row in link_rows:
        status = status_normalization.normalize_task_stored_status(row["task_status"] or row["status"] or "")
        flow_status = status_normalization.normalize_task_flow_status(row["task_flow_status"] or status)
        if str(row["status"] or "") != status or str(row["flow_status"] or "") != flow_status:
            conn.execute(
                """
                UPDATE project_task_samples
                SET status = ?, flow_status = ?
                WHERE task_id = ? AND sample_id = ?
                """,
                (status, flow_status, row["task_id"], row["sample_id"]),
            )

    category_rows = conn.execute("SELECT id, data_json FROM sample_categories").fetchall()
    for row in category_rows:
        category = ctx.json_obj(row["data_json"], {}) or {}
        normalized = status_normalization.normalize_sample_category_payload(category)
        if normalized != category:
            conn.execute(
                "UPDATE sample_categories SET data_json = ? WHERE id = ?",
                (json_dumps(normalized), row["id"]),
            )

    sample_rows = conn.execute(
        """
        SELECT id, status, has_problem, effective_status, board_sn, is_reassembled, data_json
        FROM sample_records
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    for row in sample_rows:
        sample = ctx.json_obj(row["data_json"], {}) or {}
        sample["id"] = row["id"]
        sample["status"] = row["status"] or sample.get("status") or ""
        normalized = status_normalization.normalize_sample_payload(sample)
        if int(row["has_problem"] or 0) or status_normalization.normalize_sample_quality_value(row["effective_status"]) == "有故障":
            normalized["hasProblem"] = True
            normalized["problemState"] = "有故障"
        status = ctx.sample_effective_status(normalized)
        has_problem = 1 if ctx.sample_has_problem(normalized) else 0
        effective_status = ctx.sample_effective_status(normalized)
        board_sn = str(normalized.get("boardSn") or "").strip()
        is_reassembled = 1 if ctx.sample_is_reassembled(normalized) else 0
        if (
            normalized != sample
            or str(row["status"] or "") != status
            or int(row["has_problem"] or 0) != has_problem
            or str(row["effective_status"] or "") != effective_status
            or str(row["board_sn"] or "") != board_sn
            or int(row["is_reassembled"] or 0) != is_reassembled
        ):
            conn.execute(
                """
                UPDATE sample_records
                SET status = ?, has_problem = ?, effective_status = ?, board_sn = ?, is_reassembled = ?, data_json = ?
                WHERE id = ?
                """,
                (status, has_problem, effective_status, board_sn, is_reassembled, json_dumps(normalized), row["id"]),
            )

    task_log_rows = conn.execute("SELECT id, action, data_json FROM task_logs").fetchall()
    for row in task_log_rows:
        log = ctx.json_obj(row["data_json"], {}) or {}
        normalized = status_normalization.normalize_business_value(log)
        action = status_normalization.normalize_status_text(str(row["action"] or ""))
        if normalized != log or action != str(row["action"] or ""):
            conn.execute(
                "UPDATE task_logs SET action = ?, data_json = ? WHERE id = ?",
                (action, json_dumps(normalized), row["id"]),
            )

    sample_event_rows = conn.execute("SELECT id, data_json FROM sample_events").fetchall()
    for row in sample_event_rows:
        log = ctx.json_obj(row["data_json"], {}) or {}
        normalized = status_normalization.normalize_business_value(log)
        if normalized != log:
            conn.execute(
                "UPDATE sample_events SET data_json = ? WHERE id = ?",
                (json_dumps(normalized), row["id"]),
            )

    audit_rows = conn.execute("SELECT id, action, remark FROM audit_log").fetchall()
    for row in audit_rows:
        action = status_normalization.normalize_status_text(str(row["action"] or ""))
        remark = status_normalization.normalize_status_text(str(row["remark"] or ""))
        if action != str(row["action"] or "") or remark != str(row["remark"] or ""):
            conn.execute(
                "UPDATE audit_log SET action = ?, remark = ? WHERE id = ?",
                (action, remark, row["id"]),
            )


def backfill_query_state_columns(ctx: DatabaseBackfillContext, conn: sqlite3.Connection) -> None:
    task_rows = conn.execute(
        """
        SELECT id, status, data_json
        FROM project_tasks
        WHERE COALESCE(flow_status, '') = ''
        """
    ).fetchall()
    for row in task_rows:
        task = ctx.json_obj(row["data_json"], {}) or {}
        task["status"] = row["status"] or task.get("status") or ""
        conn.execute(
            "UPDATE project_tasks SET flow_status = ? WHERE id = ?",
            (ctx.task_flow_status(task), row["id"]),
        )

    sample_rows = conn.execute(
        """
        SELECT id, status, has_problem, effective_status, data_json
        FROM sample_records
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    for row in sample_rows:
        sample = ctx.json_obj(row["data_json"], {}) or {}
        sample["status"] = row["status"] or sample.get("status") or ""
        has_problem = 1 if ctx.sample_has_problem(sample) else 0
        effective_status = ctx.sample_effective_status(sample)
        if int(row["has_problem"] or 0) != has_problem or str(row["effective_status"] or "") != effective_status:
            conn.execute(
                "UPDATE sample_records SET has_problem = ?, effective_status = ? WHERE id = ?",
                (has_problem, effective_status, row["id"]),
            )


def backfill_sample_identity_columns(ctx: DatabaseBackfillContext, conn: sqlite3.Connection) -> None:
    rows = conn.execute(
        """
        SELECT id, data_json, board_sn, is_reassembled
        FROM sample_records
        WHERE deleted_at IS NULL
        """
    ).fetchall()
    for row in rows:
        sample = ctx.json_obj(row["data_json"], {}) or {}
        board_sn = str(sample.get("boardSn") or "").strip()
        is_reassembled = 1 if ctx.sample_is_reassembled(sample) else 0
        if str(row["board_sn"] or "") != board_sn or int(row["is_reassembled"] or 0) != is_reassembled:
            conn.execute(
                "UPDATE sample_records SET board_sn = ?, is_reassembled = ? WHERE id = ?",
                (board_sn, is_reassembled, row["id"]),
            )


def backfill_project_task_samples(ctx: DatabaseBackfillContext, conn: sqlite3.Connection) -> None:
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
        task = ctx.json_obj(row["data_json"], {}) or {}
        task["id"] = row["id"]
        task["projectId"] = row["project_id"]
        task["stageId"] = row["stage_id"]
        task["testItem"] = row["test_item"] or task.get("testItem") or ""
        task["status"] = row["status"] or task.get("status") or ""
        sample_ids = ctx.json_obj(row["sample_ids_json"], [])
        if not isinstance(sample_ids, list):
            sample_ids = []
        ctx.replace_task_sample_links(
            conn,
            str(row["id"] or ""),
            str(row["project_id"] or ""),
            str(row["stage_id"] or ""),
            task,
            [str(x) for x in sample_ids],
        )
