from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable

from server_modules import mutation_summary, record_writers, sample_assets, status_normalization, task_mutation_rules


@dataclass(frozen=True)
class MutationServiceContext:
    write_db_connection: Callable
    now_iso: Callable[[], str]
    unlink_asset_relative_paths: Callable


def to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except Exception:
        return default


def _current_revision(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
    return int(row["revision"]) if row else 1


def _task_scope_failure(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    project_id: str,
    stage_id: str,
) -> dict | None:
    task_row = conn.execute(
        """
        SELECT project_id, stage_id
        FROM project_tasks
        WHERE id = ? AND deleted_at IS NULL
        """,
        (task_id,),
    ).fetchone()
    if task_row and (
        str(task_row["project_id"] or "") != project_id
        or str(task_row["stage_id"] or "") != stage_id
    ):
        return {
            "status": 409,
            "error_code": "TASK_SCOPE_CONFLICT",
            "error": "任务归属与请求中的项目或阶段不一致，已拒绝跨范围写入。",
            "taskId": task_id,
            "actualProjectId": str(task_row["project_id"] or ""),
            "actualStageId": str(task_row["stage_id"] or ""),
        }

    stage_row = conn.execute(
        """
        SELECT project_id
        FROM project_stages
        WHERE id = ? AND deleted_at IS NULL
        """,
        (stage_id,),
    ).fetchone()
    if not stage_row:
        return {
            "status": 404,
            "error_code": "STAGE_NOT_FOUND",
            "error": f"阶段不存在: {stage_id}",
            "stageId": stage_id,
        }
    if str(stage_row["project_id"] or "") != project_id:
        return {
            "status": 409,
            "error_code": "TASK_SCOPE_CONFLICT",
            "error": "阶段不属于请求中的项目，已拒绝跨项目写入任务。",
            "taskId": task_id,
            "stageId": stage_id,
            "actualProjectId": str(stage_row["project_id"] or ""),
        }
    return None


def _task_related_sample_ids(task: dict) -> set[str]:
    ids = set(task_mutation_rules.task_sample_ids(task))

    def add_items(items: object) -> None:
        if not isinstance(items, list):
            return
        for item in items:
            if not isinstance(item, dict):
                continue
            sample_id = str(item.get("sampleId") or item.get("sid") or item.get("id") or "")
            if sample_id:
                ids.add(sample_id)

    add_items(task.get("removedSampleRecords"))
    add_items(task.get("sampleFaultRecords"))
    result_draft = task.get("resultDraft")
    if isinstance(result_draft, dict):
        add_items(result_draft.get("samples"))
    result_uploads = task.get("resultUploads")
    if isinstance(result_uploads, list):
        for upload in result_uploads:
            if isinstance(upload, dict):
                add_items(upload.get("samples"))
    return ids


def _task_sample_payload_failure(
    conn: sqlite3.Connection,
    *,
    task_id: str,
    action: str,
    task: dict,
    sample_payloads: list[dict],
    sample_events: list[dict],
    is_delete: bool,
) -> dict | None:
    payload_ids: list[str] = []
    for sample in sample_payloads:
        sample_id = str(sample.get("id") or "")
        if not sample_id:
            return {"status": 400, "error": "samples 中每台样机都必须包含 id"}
        payload_ids.append(sample_id)
    if len(payload_ids) != len(set(payload_ids)):
        return {"status": 400, "error": "samples 中存在重复样机 id"}

    old_ids = task_mutation_rules.existing_task_sample_ids(conn, task_id)
    new_ids = task_mutation_rules.task_sample_ids(task)
    assignment_actions = {
        "assign_task_samples",
        "reassign_task_samples",
        "create_task_config",
        "save_task_config",
        "temp_change_task",
    }
    fixed_assignment_actions = {
        "set_task_plan",
        "save_task_result_draft",
        "update_issue_record",
        "start_task",
        "restart_task",
        "block_task",
        "task_start",
        "finish_task_result",
        "upload_task_result",
        "archive_task_delete",
        "delete_task",
    }
    if action in fixed_assignment_actions and old_ids != new_ids:
        return {
            "status": 409,
            "error_code": "TASK_SAMPLE_ASSIGNMENT_CONFLICT",
            "error": "该任务操作不允许同时改变样机分配，已拒绝保存。",
            "missingSampleIds": sorted(old_ids - new_ids),
            "unexpectedSampleIds": sorted(new_ids - old_ids),
        }

    payload_id_set = set(payload_ids)
    if action in {"set_task_plan", "save_task_result_draft", "update_issue_record"}:
        required_ids = set()
        allowed_ids = set()
    elif action in assignment_actions:
        required_ids = old_ids | new_ids if old_ids != new_ids else set()
        allowed_ids = set(required_ids)
    elif action in {"start_task", "restart_task", "block_task", "task_start", "delete_task"} or is_delete:
        required_ids = set(old_ids)
        allowed_ids = set(old_ids)
    elif action == "archive_task_delete":
        current = task_mutation_rules.existing_task(conn, task_id) or {}
        current_flow = status_normalization.normalize_task_flow_status(current)
        required_ids = set() if current_flow in ("正常完成", "异常终止") else set(old_ids)
        allowed_ids = set(required_ids)
    elif action in {"finish_task_result", "upload_task_result"}:
        allowed_ids = _task_related_sample_ids(task) | old_ids
        required_ids = set()
        if action == "finish_task_result" and old_ids:
            placeholders = ",".join("?" for _ in old_ids)
            locked_rows = conn.execute(
                f"""
                SELECT DISTINCT sample_id
                FROM project_task_samples
                WHERE sample_id IN ({placeholders})
                  AND task_id != ?
                  AND flow_status NOT IN ('正常完成', '异常终止')
                """,
                (*old_ids, task_id),
            ).fetchall()
            locked_ids = {str(row["sample_id"] or "") for row in locked_rows}
            required_ids = old_ids - locked_ids
    else:
        required_ids = old_ids | new_ids if old_ids != new_ids else set()
        allowed_ids = old_ids | new_ids

    missing_ids = required_ids - payload_id_set
    unexpected_ids = payload_id_set - allowed_ids
    if missing_ids or unexpected_ids:
        return {
            "status": 409,
            "error_code": "TASK_SAMPLE_PAYLOAD_MISMATCH",
            "error": "任务与样机载荷不完整或包含无关样机，已拒绝部分写入。",
            "missingSampleIds": sorted(missing_ids),
            "unexpectedSampleIds": sorted(unexpected_ids),
        }

    if payload_id_set:
        placeholders = ",".join("?" for _ in payload_id_set)
        existing_rows = conn.execute(
            f"SELECT id FROM sample_records WHERE deleted_at IS NULL AND id IN ({placeholders})",
            tuple(payload_id_set),
        ).fetchall()
        existing_ids = {str(row["id"] or "") for row in existing_rows}
        missing_records = payload_id_set - existing_ids
        if missing_records:
            return {
                "status": 409,
                "error_code": "SAMPLE_NOT_FOUND",
                "error": "任务引用的样机档案不存在，已拒绝保存。",
                "sampleIds": sorted(missing_records),
            }

    event_sample_ids = {
        str(event.get("sampleId") or "")
        for event in sample_events
        if isinstance(event, dict)
    }
    if "" in event_sample_ids or not event_sample_ids.issubset(payload_id_set):
        return {
            "status": 409,
            "error_code": "TASK_SAMPLE_EVENT_SCOPE_CONFLICT",
            "error": "样机事件超出本次任务允许写入的样机范围，已拒绝保存。",
            "unexpectedSampleIds": sorted(event_sample_ids - payload_id_set),
        }
    return None


def _bump_revision_and_audit(
    ctx: MutationServiceContext,
    conn: sqlite3.Connection,
    *,
    current_revision: int,
    action: str,
    remark: str,
    user: str,
    client_ip: str,
) -> tuple[int, str]:
    new_revision = current_revision + 1
    updated_at = ctx.now_iso()
    record_writers.prune_orphan_operational_logs(conn)
    action = status_normalization.normalize_status_text(action)
    remark = status_normalization.normalize_status_text(remark)
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
    record_writers.clear_audit_log_when_platform_empty(conn)
    return new_revision, updated_at


def commit_task_mutation(ctx: MutationServiceContext, payload: dict, client_ip: str) -> tuple[bool, dict]:
    task = payload.get("task")
    if not isinstance(task, dict):
        return False, {"status": 400, "error": "task 必须是 JSON 对象"}
    task_id = str(payload.get("taskId") or task.get("id") or "")
    project_id = str(payload.get("projectId") or task.get("projectId") or "")
    stage_id = str(payload.get("stageId") or task.get("stageId") or "")
    if not task_id or not project_id or not stage_id:
        return False, {"status": 400, "error": "缺少 projectId/stageId/taskId"}
    samples_value = payload.get("samples")
    sample_events_value = payload.get("sampleEvents")
    if samples_value is not None and not isinstance(samples_value, list):
        return False, {"status": 400, "error": "samples 必须是数组"}
    if sample_events_value is not None and not isinstance(sample_events_value, list):
        return False, {"status": 400, "error": "sampleEvents 必须是数组"}
    sample_payloads = [sample for sample in (samples_value or []) if isinstance(sample, dict)]
    if len(sample_payloads) != len(samples_value or []):
        return False, {"status": 400, "error": "samples 中每一项都必须是 JSON 对象"}
    sample_events = [event for event in (sample_events_value or []) if isinstance(event, dict)]
    if len(sample_events) != len(sample_events_value or []):
        return False, {"status": 400, "error": "sampleEvents 中每一项都必须是 JSON 对象"}
    action_aliases = {"task_start": "start_task"}
    raw_action = str(payload.get("action") or "")
    action = action_aliases.get(raw_action, raw_action)
    allowed_actions = {
        "create_task_config",
        "save_task_config",
        "assign_task_samples",
        "reassign_task_samples",
        "set_task_plan",
        "temp_change_task",
        "save_task_result_draft",
        "update_issue_record",
        "upload_task_result",
        "start_task",
        "restart_task",
        "block_task",
        "finish_task_result",
        "archive_task_delete",
        "delete_task",
    }
    if action not in allowed_actions:
        return False, {
            "status": 400,
            "error_code": "TASK_ACTION_NOT_ALLOWED",
            "error": f"不支持的任务操作: {raw_action or '(空)'}",
        }
    is_delete = str(payload.get("deleteMode") or "") == "delete"
    if (action == "delete_task") != is_delete:
        return False, {
            "status": 400,
            "error_code": "TASK_ACTION_NOT_ALLOWED",
            "error": "delete_task 操作与物理删除模式不一致。",
        }
    task["id"] = task_id
    task["projectId"] = project_id
    task["stageId"] = stage_id
    task = status_normalization.normalize_task_payload(task)
    affected = {}

    with ctx.write_db_connection() as conn:
        current_revision = _current_revision(conn)
        scope_failure = _task_scope_failure(
            conn,
            task_id=task_id,
            project_id=project_id,
            stage_id=stage_id,
        )
        if scope_failure:
            return False, {**scope_failure, "server_revision": current_revision}
        if action == "archive_task_delete" and status_normalization.normalize_task_flow_status(task) not in ("正常完成", "异常终止"):
            archived_at = ctx.now_iso()
            task.update({
                "status": "异常终止",
                "completed": True,
                "completionType": "异常终止",
                "completedAt": str(task.get("completedAt") or archived_at),
                "endDate": str(task.get("endDate") or archived_at[:10]),
            })
            task = status_normalization.normalize_task_payload(task)
        if action == "finish_task_result":
            finished = task_mutation_rules.existing_finished_task(conn, task_id)
            if finished:
                return False, {
                    "status": 409,
                    "error_code": "TASK_ALREADY_FINISHED",
                    "error": "任务已经结束，已拒绝重复结束请求。",
                    "taskId": task_id,
                    "taskStatus": str(finished.get("status") or ""),
                    "server_revision": current_revision,
                }
        state_conflict = task_mutation_rules.task_action_state_conflict(
            conn,
            task_id,
            action,
            task,
            is_delete=is_delete,
        )
        if state_conflict:
            return False, {
                "status": 409,
                "error_code": "TASK_STATE_CONFLICT",
                "error": state_conflict["reason"],
                **state_conflict,
                "server_revision": current_revision,
            }
        if not is_delete:
            status_blockers = task_mutation_rules.detect_task_mutation_sample_status_blockers(conn, [(task_id, task)])
            if status_blockers:
                return False, {
                    "status": 409,
                    "error_code": "SAMPLE_STATUS_NOT_SELECTABLE",
                    "error": "样机状态不可选：只有闲置样机可以加入测试任务，已拒绝保存。",
                    "samples": status_blockers,
                    "server_revision": current_revision,
                }
            if action == "upload_task_result" and task_mutation_rules.existing_finished_task(conn, task_id) and sample_payloads:
                locked = task_mutation_rules.detect_completed_task_sample_current_state_locks(
                    conn,
                    task_id,
                    {str(sample.get("id") or "") for sample in sample_payloads},
                )
                if locked:
                    return False, {
                        "status": 409,
                        "error_code": "SAMPLE_CURRENT_STATE_LOCKED",
                        "error": "样机正在其他未完成任务中，已拒绝通过已完成任务覆盖当前样机信息。",
                        "conflicts": locked,
                        "server_revision": current_revision,
                    }
            conflicts = task_mutation_rules.detect_task_mutation_occupancy_conflicts(conn, task_id, task, project_id, stage_id)
            if conflicts:
                return False, {
                    "status": 409,
                    "error_code": "SAMPLE_OCCUPANCY_CONFLICT",
                    "error": "样机占用冲突：同一样机被多个未完成任务占用，已拒绝保存。",
                    "conflicts": conflicts,
                    "server_revision": current_revision,
                }

        sample_failure = _task_sample_payload_failure(
            conn,
            task_id=task_id,
            action=action,
            task=task,
            sample_payloads=sample_payloads,
            sample_events=sample_events,
            is_delete=is_delete,
        )
        if sample_failure:
            return False, {**sample_failure, "server_revision": current_revision}

        for sample in sample_payloads:
            record_writers.update_sample_record(conn, sample)
        record_writers.upsert_sample_events(conn, sample_events)
        if is_delete:
            record_writers.delete_task_record(conn, task_id)
        else:
            record_writers.upsert_task_record(
                conn,
                task,
                project_id,
                stage_id,
                create_if_missing=bool(payload.get("createIfMissing")),
            )

        new_revision, updated_at = _bump_revision_and_audit(
            ctx,
            conn,
            current_revision=current_revision,
            action=action,
            remark=str(payload.get("remark") or "任务增量变更"),
            user=str(payload.get("user") or ""),
            client_ip=client_ip,
        )
        affected_sample_ids = set(task_mutation_rules.task_sample_ids(task))
        for sample in payload.get("samples") or []:
            if isinstance(sample, dict) and sample.get("id"):
                affected_sample_ids.add(str(sample.get("id") or ""))
        for event in payload.get("sampleEvents") or []:
            if isinstance(event, dict) and event.get("sampleId"):
                affected_sample_ids.add(str(event.get("sampleId") or ""))
        affected = mutation_summary.build_mutation_affected_summary(
            conn,
            project_ids=[project_id],
            stage_ids=[stage_id],
            task_ids=[task_id],
            sample_ids=affected_sample_ids,
        )
        conn.commit()

    return True, {"revision": new_revision, "updated_at": updated_at, "affected": affected}


def commit_task_batch_mutation(ctx: MutationServiceContext, payload: dict, client_ip: str) -> tuple[bool, dict]:
    tasks = payload.get("tasks")
    if not isinstance(tasks, list) or not tasks:
        return False, {"status": 400, "error": "tasks 必须是非空数组"}
    project_id = str(payload.get("projectId") or "")
    stage_id = str(payload.get("stageId") or "")
    if not project_id or not stage_id:
        return False, {"status": 400, "error": "缺少 projectId/stageId"}
    affected = {}

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
        normalized_tasks.append(status_normalization.normalize_task_payload(task))

    with ctx.write_db_connection() as conn:
        current_revision = _current_revision(conn)
        action = str(payload.get("action") or "task_batch_mutation")
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

        placeholders = ",".join("?" for _ in normalized_tasks)
        existing_rows = conn.execute(
            f"""
            SELECT id, project_id, stage_id
            FROM project_tasks
            WHERE deleted_at IS NULL AND id IN ({placeholders})
            """,
            tuple(str(task.get("id") or "") for task in normalized_tasks),
        ).fetchall()
        scope_conflicts = [
            {
                "taskId": str(row["id"] or ""),
                "actualProjectId": str(row["project_id"] or ""),
                "actualStageId": str(row["stage_id"] or ""),
            }
            for row in existing_rows
            if str(row["project_id"] or "") != project_id or str(row["stage_id"] or "") != stage_id
        ]
        if scope_conflicts:
            return False, {
                "status": 409,
                "error_code": "TASK_SCOPE_CONFLICT",
                "error": "批量任务中包含属于其他项目或阶段的任务，已拒绝跨范围写入。",
                "tasks": scope_conflicts,
                "server_revision": current_revision,
            }

        if action != "create_tasks_batch" or not bool(payload.get("createIfMissing")):
            return False, {
                "status": 409,
                "error_code": "TASK_BATCH_CREATE_ONLY",
                "error": "批量任务接口仅允许一次性创建新的待下发空任务。",
                "server_revision": current_revision,
            }
        if existing_rows:
            return False, {
                "status": 409,
                "error_code": "TASK_ALREADY_EXISTS",
                "error": "批量创建中包含已经存在的任务，已拒绝覆盖。",
                "taskIds": sorted(str(row["id"] or "") for row in existing_rows),
                "server_revision": current_revision,
            }

        invalid_tasks = []
        for task in normalized_tasks:
            sample_ids = task.get("sampleIds")
            flow_status = status_normalization.normalize_task_flow_status(task)
            if not isinstance(sample_ids, list) or sample_ids or flow_status != "待下发":
                invalid_tasks.append({
                    "taskId": str(task.get("id") or ""),
                    "status": flow_status,
                    "sampleIds": sample_ids if isinstance(sample_ids, list) else [],
                })
        if invalid_tasks:
            return False, {
                "status": 409,
                "error_code": "TASK_BATCH_CREATE_ONLY",
                "error": "批量创建只接受未分配样机的待下发任务。",
                "tasks": invalid_tasks,
                "server_revision": current_revision,
            }

        status_blockers = task_mutation_rules.detect_task_mutation_sample_status_blockers(
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

        for task in normalized_tasks:
            record_writers.upsert_task_record(
                conn,
                task,
                project_id,
                stage_id,
                create_if_missing=True,
            )

        new_revision, updated_at = _bump_revision_and_audit(
            ctx,
            conn,
            current_revision=current_revision,
            action=action,
            remark=str(payload.get("remark") or f"批量任务增量变更：{len(normalized_tasks)} 个"),
            user=str(payload.get("user") or ""),
            client_ip=client_ip,
        )
        affected = mutation_summary.build_mutation_affected_summary(
            conn,
            project_ids=[project_id],
            stage_ids=[stage_id],
            task_ids=[task.get("id") for task in normalized_tasks],
            sample_ids=[
                sample_id
                for task in normalized_tasks
                for sample_id in (task.get("sampleIds") or [])
            ],
        )
        conn.commit()

    return True, {"revision": new_revision, "updated_at": updated_at, "count": len(normalized_tasks), "affected": affected}


def commit_sample_mutation(ctx: MutationServiceContext, payload: dict, client_ip: str) -> tuple[bool, dict]:
    sample_id = str(payload.get("sampleId") or (payload.get("sample") or {}).get("id") or "")
    if not sample_id:
        return False, {"status": 400, "error": "缺少 sampleId"}
    sample = payload.get("sample")
    if sample is not None and not isinstance(sample, dict):
        return False, {"status": 400, "error": "sample 必须是 JSON 对象"}
    body_sample_id = str((sample or {}).get("id") or "")
    if body_sample_id and body_sample_id != sample_id:
        return False, {
            "status": 409,
            "error_code": "SAMPLE_ID_MISMATCH",
            "error": "请求路径中的样机与请求体样机不一致，已拒绝写入。",
            "sampleId": sample_id,
            "bodySampleId": body_sample_id,
        }
    if isinstance(sample, dict):
        sample = {**sample, "id": sample_id}
    delete_sample = bool(payload.get("deleteSample"))
    affected = {}
    asset_paths_to_delete: list[str] = []

    with ctx.write_db_connection() as conn:
        current_revision = _current_revision(conn)

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
            record_writers.update_stage_record(conn, item.get("stage") or {}, project_id, stage_id)
            record_writers.upsert_task_record(
                conn,
                task,
                project_id,
                stage_id,
                create_if_missing=bool(item.get("createIfMissing")),
            )

        for sample in payload.get("samples") or []:
            if isinstance(sample, dict) and str(sample.get("id") or "") != sample_id:
                record_writers.update_sample_record(conn, sample)

        if isinstance(sample, dict) and not delete_sample:
            record_writers.update_sample_record(conn, sample)

        record_writers.upsert_sample_events(conn, payload.get("sampleEvents") or [])

        if delete_sample:
            asset_paths_to_delete = sample_assets.sample_asset_relative_paths(conn, [sample_id])
            conn.execute("DELETE FROM sample_assets WHERE sample_id = ?", (sample_id,))
            conn.execute("DELETE FROM sample_events WHERE sample_id = ?", (sample_id,))
            conn.execute("DELETE FROM sample_records WHERE id = ?", (sample_id,))

        action = str(payload.get("action") or ("destroy_sample" if delete_sample else "sample_mutation"))
        new_revision, updated_at = _bump_revision_and_audit(
            ctx,
            conn,
            current_revision=current_revision,
            action=action,
            remark=str(payload.get("remark") or ("样机档案销毁" if delete_sample else "样机增量变更")),
            user=str(payload.get("user") or ""),
            client_ip=client_ip,
        )
        affected_task_ids = []
        affected_project_ids = []
        affected_stage_ids = []
        for item in payload.get("taskMutations") or []:
            if not isinstance(item, dict):
                continue
            affected_task_ids.append(item.get("taskId") or (item.get("task") or {}).get("id"))
            affected_project_ids.append(item.get("projectId") or (item.get("task") or {}).get("projectId"))
            affected_stage_ids.append(item.get("stageId") or (item.get("task") or {}).get("stageId"))
        affected_sample_ids = [sample_id, *[
            sample.get("id")
            for sample in payload.get("samples") or []
            if isinstance(sample, dict)
        ], *[
            event.get("sampleId")
            for event in payload.get("sampleEvents") or []
            if isinstance(event, dict)
        ]]
        affected = mutation_summary.build_mutation_affected_summary(
            conn,
            project_ids=affected_project_ids,
            stage_ids=affected_stage_ids,
            task_ids=affected_task_ids,
            sample_ids=affected_sample_ids,
        )
        conn.commit()

    if asset_paths_to_delete:
        ctx.unlink_asset_relative_paths(asset_paths_to_delete, warn_label="删除样机资产文件")

    return True, {"revision": new_revision, "updated_at": updated_at, "affected": affected}


def commit_project_mutation(ctx: MutationServiceContext, payload: dict, client_ip: str) -> tuple[bool, dict]:
    project = payload.get("project")
    project_id = str(payload.get("projectId") or (project or {}).get("id") or "")
    if not project_id:
        return False, {"status": 400, "error": "缺少 projectId"}
    delete_project = bool(payload.get("deleteProject"))
    affected = {}

    with ctx.write_db_connection() as conn:
        current_revision = _current_revision(conn)

        for sample in payload.get("samples") or []:
            if isinstance(sample, dict):
                record_writers.update_sample_record(conn, sample)
        record_writers.upsert_sample_events(conn, payload.get("sampleEvents") or [])

        if delete_project:
            record_writers.delete_project_record(conn, project_id)
        else:
            if not isinstance(project, dict):
                return False, {"status": 400, "error": "project 必须是 JSON 对象"}
            project["id"] = project_id
            record_writers.update_project_record(
                conn,
                project,
                create_if_missing=bool(payload.get("createIfMissing")),
                sort_order=to_int(payload.get("sortOrder")) if payload.get("sortOrder") is not None else None,
            )

        new_revision, updated_at = _bump_revision_and_audit(
            ctx,
            conn,
            current_revision=current_revision,
            action=str(payload.get("action") or ("delete_project" if delete_project else "project_mutation")),
            remark=str(payload.get("remark") or ("删除项目" if delete_project else "项目增量变更")),
            user=str(payload.get("user") or ""),
            client_ip=client_ip,
        )
        affected = mutation_summary.build_mutation_affected_summary(
            conn,
            project_ids=[project_id],
            sample_ids=[
                sample.get("id")
                for sample in payload.get("samples") or []
                if isinstance(sample, dict)
            ],
        )
        conn.commit()

    return True, {"revision": new_revision, "updated_at": updated_at, "affected": affected}


def commit_stage_mutation(ctx: MutationServiceContext, payload: dict, client_ip: str) -> tuple[bool, dict]:
    stage = payload.get("stage")
    stage_id = str(payload.get("stageId") or (stage or {}).get("id") or "")
    project_id = str(payload.get("projectId") or (stage or {}).get("projectId") or "")
    if not stage_id or not project_id:
        return False, {"status": 400, "error": "缺少 projectId/stageId"}
    delete_stage = bool(payload.get("deleteStage"))
    affected = {}

    with ctx.write_db_connection() as conn:
        current_revision = _current_revision(conn)

        project = payload.get("project")
        if isinstance(project, dict):
            project["id"] = project_id
            record_writers.update_project_record(conn, project)

        for sample in payload.get("samples") or []:
            if isinstance(sample, dict):
                record_writers.update_sample_record(conn, sample)
        record_writers.upsert_sample_events(conn, payload.get("sampleEvents") or [])

        if delete_stage:
            record_writers.delete_stage_record(conn, stage_id)
            for idx, sibling in enumerate(payload.get("stages") or []):
                if isinstance(sibling, dict) and str(sibling.get("id") or "") != stage_id:
                    record_writers.update_stage_record(conn, sibling, project_id, str(sibling.get("id") or ""), sort_order=idx)
        else:
            if not isinstance(stage, dict):
                return False, {"status": 400, "error": "stage 必须是 JSON 对象"}
            stage["id"] = stage_id
            stage["projectId"] = project_id
            sibling_ids = [str(s.get("id") or "") for s in (payload.get("stages") or []) if isinstance(s, dict)]
            sort_order = sibling_ids.index(stage_id) if stage_id in sibling_ids else None
            record_writers.update_stage_record(
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
                        record_writers.update_stage_record(conn, sibling, project_id, sid, sort_order=idx)

        new_revision, updated_at = _bump_revision_and_audit(
            ctx,
            conn,
            current_revision=current_revision,
            action=str(payload.get("action") or ("delete_stage" if delete_stage else "stage_mutation")),
            remark=str(payload.get("remark") or ("删除阶段" if delete_stage else "阶段增量变更")),
            user=str(payload.get("user") or ""),
            client_ip=client_ip,
        )
        affected = mutation_summary.build_mutation_affected_summary(
            conn,
            project_ids=[project_id],
            stage_ids=[stage_id, *[
                sibling.get("id")
                for sibling in payload.get("stages") or []
                if isinstance(sibling, dict)
            ]],
            sample_ids=[
                sample.get("id")
                for sample in payload.get("samples") or []
                if isinstance(sample, dict)
            ],
        )
        conn.commit()

    return True, {"revision": new_revision, "updated_at": updated_at, "affected": affected}


def delete_sample_category_record(conn: sqlite3.Connection, category_id: str) -> list[str]:
    return record_writers.delete_sample_category_record(conn, category_id)


def commit_sample_category_mutation(ctx: MutationServiceContext, payload: dict, client_ip: str) -> tuple[bool, dict]:
    category_id = str(payload.get("categoryId") or (payload.get("category") or {}).get("id") or "")
    if not category_id:
        return False, {"status": 400, "error": "缺少 categoryId"}
    delete_category = bool(payload.get("deleteCategory"))
    affected = {}
    asset_paths_to_delete: list[str] = []
    default_project_ids: list[str] = []

    with ctx.write_db_connection() as conn:
        current_revision = _current_revision(conn)

        if not delete_category:
            category = payload.get("category")
            if not isinstance(category, dict):
                return False, {"status": 400, "error": "category 必须是 JSON 对象"}
            category["id"] = category_id
            record_writers.update_sample_category_record(
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
            record_writers.update_stage_record(conn, item.get("stage") or {}, project_id, stage_id)
            record_writers.upsert_task_record(
                conn,
                task,
                project_id,
                stage_id,
                create_if_missing=bool(item.get("createIfMissing")),
            )

        for sample in payload.get("samples") or []:
            if isinstance(sample, dict):
                record_writers.update_sample_record(
                    conn,
                    sample,
                    create_if_missing=bool(payload.get("createSamples") or payload.get("createIfMissing")),
                )
        record_writers.upsert_sample_events(conn, payload.get("sampleEvents") or [])

        if delete_category:
            default_project_ids = record_writers.clear_project_default_sample_category(conn, category_id)
            asset_paths_to_delete = delete_sample_category_record(conn, category_id)

        new_revision, updated_at = _bump_revision_and_audit(
            ctx,
            conn,
            current_revision=current_revision,
            action=str(payload.get("action") or ("destroy_sample_category" if delete_category else "sample_category_mutation")),
            remark=str(payload.get("remark") or ("样机池档案销毁" if delete_category else "样机池增量变更")),
            user=str(payload.get("user") or ""),
            client_ip=client_ip,
        )
        affected_task_ids = []
        affected_project_ids = []
        affected_stage_ids = []
        for item in payload.get("taskMutations") or []:
            if not isinstance(item, dict):
                continue
            affected_task_ids.append(item.get("taskId") or (item.get("task") or {}).get("id"))
            affected_project_ids.append(item.get("projectId") or (item.get("task") or {}).get("projectId"))
            affected_stage_ids.append(item.get("stageId") or (item.get("task") or {}).get("stageId"))
        affected_project_ids.extend(default_project_ids)
        affected = mutation_summary.build_mutation_affected_summary(
            conn,
            project_ids=affected_project_ids,
            stage_ids=affected_stage_ids,
            task_ids=affected_task_ids,
            sample_category_ids=[category_id],
            sample_ids=[
                sample.get("id")
                for sample in payload.get("samples") or []
                if isinstance(sample, dict)
            ],
        )
        conn.commit()

    if asset_paths_to_delete:
        ctx.unlink_asset_relative_paths(asset_paths_to_delete, warn_label="删除样机池资产文件")

    return True, {"revision": new_revision, "updated_at": updated_at, "affected": affected}
