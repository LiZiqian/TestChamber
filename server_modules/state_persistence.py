from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Callable


@dataclass(frozen=True)
class StatePersistenceContext:
    app_version: str
    write_db_connection: Callable
    now_iso: Callable[[], str]
    json_dumps: Callable
    json_obj: Callable
    empty_data: Callable[[], dict]
    compose_state: Callable
    merge_state: Callable
    detect_sample_occupancy_conflicts: Callable
    hydrate_externalized_sample_fields: Callable
    sync_project_library: Callable
    sync_sample_library: Callable
    split_state_for_storage: Callable
    should_backup: Callable
    write_backup: Callable[[dict, int], None]
    load_sample_photos: Callable[[sqlite3.Connection, str], list[dict]]


IMPORTANT_ACTIONS = {
    "upload_sample_photos",
    "delete_sample_photo",
}


def save_state(
    ctx: StatePersistenceContext,
    new_data: dict,
    expected_revision: int | None,
    client_ip: str,
    remark: str = "",
    user: str = "",
    base_data: dict | None = None,
) -> tuple[bool, dict]:
    if not isinstance(new_data, dict):
        return False, {"status": 400, "error": "data 必须是 JSON 对象"}

    with ctx.write_db_connection() as conn:
        current_data, current_revision, _ = ctx.compose_state(
            conn,
            include_sample_photos=False,
            include_sample_logs=True,
        )
        action = "save_state"

        if expected_revision is not None and int(expected_revision) != current_revision and isinstance(base_data, dict):
            new_data = ctx.merge_state(base_data, new_data, current_data)
            action = "save_state_merge"

        if expected_revision is not None and int(expected_revision) != current_revision and not isinstance(base_data, dict):
            return False, {
                "status": 409,
                "error": "revision 冲突，服务器数据已被其他客户端更新",
                "server_revision": current_revision,
            }

        conflict = ctx.detect_sample_occupancy_conflicts(new_data)
        if conflict:
            return False, {
                "status": 409,
                "error_code": "SAMPLE_OCCUPANCY_CONFLICT",
                "error": "样机占用冲突：同一样机被多个未完成任务占用，已拒绝保存。",
                "conflicts": conflict,
                "server_revision": current_revision,
            }

        new_revision = current_revision + 1
        updated_at = ctx.now_iso()
        new_data["version"] = ctx.app_version
        ctx.hydrate_externalized_sample_fields(new_data, current_data)

        ctx.sync_project_library(conn, new_data, allow_empty=True)
        ctx.sync_sample_library(conn, new_data, allow_empty=True)
        stored_data = ctx.split_state_for_storage(new_data)

        conn.execute(
            "UPDATE app_state SET data_json = ?, revision = ?, updated_at = ? WHERE id = 1",
            (ctx.json_dumps(stored_data), new_revision, updated_at),
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

    if ctx.should_backup(action, new_revision):
        try:
            ctx.write_backup(new_data, new_revision)
        except Exception as e:
            print(f"[WARN] 写入备份失败：{e}")

    return True, {"revision": new_revision, "updated_at": updated_at}


def commit_data_mutation(ctx: StatePersistenceContext, conn: sqlite3.Connection, data: dict, action: str, remark: str, client_ip: str) -> dict:
    row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
    current_revision = int(row["revision"]) if row else 1
    new_revision = current_revision + 1
    updated_at = ctx.now_iso()
    data["version"] = ctx.app_version
    ctx.sync_project_library(conn, data, allow_empty=True)
    ctx.sync_sample_library(conn, data, allow_empty=True)
    conn.execute(
        "UPDATE app_state SET data_json = ?, revision = ?, updated_at = ? WHERE id = 1",
        (ctx.json_dumps(ctx.split_state_for_storage(data)), new_revision, updated_at),
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

    is_important = action in IMPORTANT_ACTIONS
    if ctx.should_backup(action, new_revision, is_important=is_important):
        try:
            ctx.write_backup(data, new_revision)
        except Exception as e:
            print(f"[WARN] 写入备份失败：{e}")
    return {"revision": new_revision, "updated_at": updated_at}


def commit_sample_asset_mutation(
    ctx: StatePersistenceContext,
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
    updated_at = ctx.now_iso()

    sample_row = conn.execute(
        "SELECT data_json FROM sample_records WHERE id = ? AND deleted_at IS NULL",
        (sample_id,),
    ).fetchone()
    if not sample_row:
        raise KeyError("样机不存在")
    sample_json = ctx.json_obj(sample_row["data_json"], {}) or {}
    sample_json["updatedAt"] = updated_at
    conn.execute(
        "UPDATE sample_records SET data_json = ?, updated_at = ? WHERE id = ?",
        (ctx.json_dumps(sample_json), updated_at, sample_id),
    )

    stored = ctx.json_obj(state_row["data_json"] if state_row else None, {}) or ctx.split_state_for_storage(ctx.empty_data())
    stored["version"] = ctx.app_version
    if state_row:
        conn.execute(
            "UPDATE app_state SET data_json = ?, revision = ?, updated_at = ? WHERE id = 1",
            (ctx.json_dumps(stored), new_revision, updated_at),
        )
    else:
        conn.execute(
            "INSERT INTO app_state (id, data_json, revision, updated_at) VALUES (1, ?, ?, ?)",
            (ctx.json_dumps(stored), new_revision, updated_at),
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
    return {"revision": new_revision, "updated_at": updated_at, "photos": ctx.load_sample_photos(conn, sample_id)}
