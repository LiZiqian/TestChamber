from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class DatabaseBackfillContext:
    json_obj: Callable
    task_flow_status: Callable[[dict], str]
    sample_has_problem: Callable[[dict], bool]
    sample_effective_status: Callable[[dict], str]
    sample_is_reassembled: Callable[[dict], bool]
    replace_task_sample_links: Callable[..., None]


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
