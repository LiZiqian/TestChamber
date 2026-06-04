from __future__ import annotations

import copy
import json
import sqlite3

from server_modules import task_queries


def json_obj(text: str | None, fallback: object | None = None):
    try:
        return json.loads(text or "")
    except Exception:
        return copy.deepcopy(fallback)


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

    task_rows = conn.execute(
        """
        SELECT id, project_id, stage_id, progress_id, category, test_item, sku_index, status, owner,
               sample_ids_json, data_json, completed_at
        FROM project_tasks
        WHERE deleted_at IS NULL
        ORDER BY created_at, id
        """
    ).fetchall()
    logs_by_task = task_queries.load_task_logs_for(conn, [str(row["id"]) for row in task_rows])
    for row in task_rows:
        stage = stage_map.get(row["stage_id"])
        if not stage:
            continue
        task = task_queries.task_from_db_row(row)
        task["logs"] = logs_by_task.get(row["id"], [])
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
    logs_by_task = task_queries.load_task_logs_for(conn, [str(row["id"]) for row in task_rows])
    for row in task_rows:
        stage = stage_map.get(row["stage_id"])
        if not stage:
            continue
        task = task_queries.task_from_db_row(row)
        task["logs"] = logs_by_task.get(row["id"], [])
        stage.setdefault("tasks", []).append(task)
    return project


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
