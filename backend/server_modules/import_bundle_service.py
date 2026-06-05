from __future__ import annotations

import copy
import json
import shutil
import uuid
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

from server_modules import chamber_package, import_commit, import_diff, migration_scope, mutation_summary as mutation_summary_module, record_writers


@dataclass(frozen=True)
class ImportBundleCommitContext:
    app_version: str
    sample_data_dir: Path
    import_previews: dict
    cleanup_expired_previews: Callable[[], None]
    cleanup_preview_temp: Callable[[str], None]
    load_import_preview_payload: Callable[[dict], tuple[dict, dict]]
    get_state_metadata: Callable[[], tuple[int, str]]
    get_state: Callable[..., tuple[dict, int, str]]
    detect_sample_occupancy_conflicts: Callable[[dict], list[dict]]
    write_db_connection: Callable
    now_iso: Callable[[], str]
    sync_project_library: Callable
    sync_sample_library: Callable
    split_state_for_storage: Callable[[dict], dict]
    json_dumps: Callable[[object], str]
    connect_db: Callable
    begin_read_snapshot: Callable
    load_sample_photos: Callable
    url_for_asset: Callable[[str, str], str]
    thumbnail_asset_id: Callable[[str], str]

def commit_merged_import_state(
    ctx: ImportBundleCommitContext,
    merged_data: dict,
    expected_revision: int | None,
    client_ip: str,
    remark: str,
    user: str,
) -> tuple[bool, dict]:
    """Persist an already-merged import state without composing full current state again."""
    detect_sample_occupancy_conflicts = ctx.detect_sample_occupancy_conflicts
    write_db_connection = ctx.write_db_connection
    now_iso = ctx.now_iso
    sync_project_library = ctx.sync_project_library
    sync_sample_library = ctx.sync_sample_library
    split_state_for_storage = ctx.split_state_for_storage
    json_dumps = ctx.json_dumps
    APP_VERSION = ctx.app_version
    conflict = detect_sample_occupancy_conflicts(merged_data)
    if conflict:
        return False, {
            "status": 409,
            "error_code": "SAMPLE_OCCUPANCY_CONFLICT",
            "error": "样机占用冲突：同一样机被多个未完成任务占用，已拒绝保存。",
            "conflicts": conflict,
        }

    with write_db_connection() as conn:
        row = conn.execute("SELECT revision FROM app_state WHERE id = 1").fetchone()
        current_revision = int(row["revision"]) if row else 1
        if expected_revision is not None and int(expected_revision) != current_revision:
            return False, {
                "status": 409,
                "error": "revision 冲突，服务器数据已被其他客户端更新",
                "error_code": "IMPORT_REVISION_CONFLICT",
                "server_revision": current_revision,
            }

        new_revision = current_revision + 1
        updated_at = now_iso()
        merged_data["version"] = APP_VERSION
        sync_project_library(conn, merged_data, allow_empty=True)
        sync_sample_library(conn, merged_data, allow_empty=True)
        record_writers.prune_orphan_operational_logs(conn)
        stored_data = split_state_for_storage(merged_data)
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
            (updated_at, user, "import_bundle_commit", remark, current_revision, new_revision, client_ip),
        )
        record_writers.clear_audit_log_when_platform_empty(conn)
        conn.commit()

    return True, {"revision": new_revision, "updated_at": updated_at}


def commit_import_bundle(ctx: ImportBundleCommitContext, payload: dict) -> dict:
    """执行导入写入"""
    _cleanup_expired_previews = ctx.cleanup_expired_previews
    _IMPORT_PREVIEWS = ctx.import_previews
    _load_import_preview_payload = ctx.load_import_preview_payload
    _cleanup_preview_temp = ctx.cleanup_preview_temp
    get_state_metadata = ctx.get_state_metadata
    get_state = ctx.get_state
    SAMPLE_DATA_DIR = ctx.sample_data_dir
    url_for_asset = ctx.url_for_asset
    thumbnail_asset_id = ctx.thumbnail_asset_id
    _normalize_project = import_diff.normalize_project
    _register_imported_project_tree = import_commit.register_imported_project_tree
    _register_imported_stage_tree = import_commit.register_imported_stage_tree
    _find_incoming_stage = import_commit.find_incoming_stage
    _find_incoming_task = import_commit.find_incoming_task
    _merge_project_sub_data = import_commit.merge_project_sub_data
    _content_hash = import_commit.content_hash
    _sample_index_by_id = import_commit.sample_index_by_id
    _merge_import_sample_subrecords = import_commit.merge_import_sample_subrecords
    _apply_id_maps = import_commit.apply_id_maps
    _merge_import_sample_events = import_commit.merge_import_sample_events
    _validate_import_commit_state = import_commit.validate_import_commit_state
    _build_import_mutation_summary = mutation_summary_module.build_import_mutation_summary

    def hydrate_import_target_photos(current_data: dict, incoming: dict, sample_id_map: dict[str, str], existing_sample_ids: set[str]) -> None:
        import_commit.hydrate_import_target_photos(
            current_data,
            incoming,
            sample_id_map,
            existing_sample_ids,
            connect_db=ctx.connect_db,
            begin_read_snapshot=ctx.begin_read_snapshot,
            load_sample_photos=ctx.load_sample_photos,
        )
    preview_id = payload.get("previewId", "")
    decisions = payload.get("decisions") or {}

    _cleanup_expired_previews()
    entry = _IMPORT_PREVIEWS.get(preview_id)
    if not entry:
        return {"ok": False, "error": "previewId 无效或已过期", "status": 400}

    incoming_payload, result = _load_import_preview_payload(entry)
    if not result:
        _cleanup_preview_temp(preview_id)
        del _IMPORT_PREVIEWS[preview_id]
        return {"ok": False, "error": "导入预览缓存损坏，请重新选择文件导入", "status": 400}

    # ── Revision 校验：commit 时主库 revision 必须与 preview 时一致 ──
    preview_revision = entry.get("_revision")
    if preview_revision is not None:
        current_revision_check, _ = get_state_metadata()
        if current_revision_check != preview_revision:
            return {"ok": False,
                    "error": "服务器数据在预览后被其他用户修改，请重新选择文件导入。",
                    "error_code": "IMPORT_REVISION_CONFLICT",
                    "server_revision": current_revision_check,
                    "status": 409}

    tmp_dir = Path(entry["_tmp_dir"])
    asset_index = {"assets": []}
    asset_index_path = tmp_dir / chamber_package.ASSET_INDEX_PATH
    if asset_index_path.is_file():
        try:
            loaded_asset_index = json.loads(asset_index_path.read_text(encoding="utf-8"))
            if isinstance(loaded_asset_index, dict):
                asset_index = loaded_asset_index
        except (OSError, json.JSONDecodeError):
            asset_index = {"assets": []}

    current_data = None
    selection = payload.get("selection")
    if not migration_scope.selection_is_empty(selection):
        current_data, _, _ = get_state(compact=True)
        incoming_payload = migration_scope.filter_state_by_selection(incoming_payload, selection)
        manifest = {}
        manifest_path = tmp_dir / "manifest.json"
        if manifest_path.is_file():
            try:
                loaded_manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
                if isinstance(loaded_manifest, dict):
                    manifest = loaded_manifest
            except (OSError, json.JSONDecodeError):
                manifest = {}
        result = import_diff.diff_import_bundle(current_data, incoming_payload, manifest, tmp_dir, asset_index=asset_index)

    blockers = result.get("blockers") or []
    if blockers:
        return {"ok": False, "error": "存在阻断项（如缺失照片），无法提交导入", "blockers": blockers, "status": 400}

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

    # Commit merge does not need full photo/event arrays for the whole library.
    # Existing photos for touched samples are loaded selectively before photo merge.
    if current_data is None:
        current_data, _, _ = get_state(compact=True)
    existing_sample_ids_before_import = set(_sample_index_by_id(current_data).keys())

    incoming = copy.deepcopy(incoming_payload)
    source_manifest = (result.get("source") or {})
    asset_lookup = chamber_package.sample_photo_asset_lookup(asset_index)

    def import_asset_source(incoming_sample_id: str, photo: dict, role: str, fallback_relative_path: str) -> tuple[Path | None, str]:
        photo_id = str(photo.get("id") or "")
        asset = asset_lookup.get((str(incoming_sample_id), photo_id, role))
        if asset:
            zip_path = str(asset.get("zipPath") or "")
            source_path = chamber_package.safe_package_member_path(tmp_dir, zip_path)
            filename = Path(str(asset.get("fileName") or Path(zip_path).name or Path(fallback_relative_path).name)).name
            return source_path, filename
        filename = Path(fallback_relative_path or "").name
        if not filename:
            return None, ""
        return tmp_dir / "assets" / "samples" / str(incoming_sample_id) / "photos" / filename, filename

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
                                        # Central photo merge below loads only the touched
                                        # target sample photos before appending incoming photos.
                                        continue
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

    hydrate_import_target_photos(current_data, incoming, sample_id_map, existing_sample_ids_before_import)
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
                manifest_original_key = (str(inc_sid), str(photo_id), "original")
                manifest_thumb_key = (str(inc_sid), str(photo_id), "thumbnail")
                # 原图：用 relativePath 获取真实文件名（含扩展名）
                rel = photo.get("relativePath", "")
                if rel or manifest_original_key in asset_lookup:
                    asset_src, fn = import_asset_source(inc_sid, photo, "original", rel)
                    if asset_src and fn and asset_src.is_file():
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
                if thumb_rel or manifest_thumb_key in asset_lookup:
                    thumb_src, thumb_fn = import_asset_source(inc_sid, photo, "thumbnail", thumb_rel)
                    if thumb_src and thumb_fn and thumb_src.is_file():
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
    ok, resp = commit_merged_import_state(
        ctx,
        current_data,
        preview_revision,
        "import-bundle",
        import_remark,
        "数据导入",
    )

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


def sample_archive_default_decisions(result: dict) -> dict:
    decisions: dict[str, dict] = {}
    for conflict in result.get("conflicts") or []:
        cid = conflict.get("conflictId")
        if not cid:
            continue
        if conflict.get("type") == "sample_identity_conflict":
            decisions[cid] = {
                "action": "merge_into_existing",
                "targetId": conflict.get("preferredMergeTarget") or conflict.get("currentId"),
                "fieldChoices": {},
            }
        elif conflict.get("type") == "field_conflict" and conflict.get("entity") == "sample":
            decisions[cid] = {
                "action": "apply_field_choices",
                "fieldChoices": {field: "current" for field in conflict.get("diffFields") or []},
            }
        else:
            decisions[cid] = {"action": "skip"}
    return decisions


def commit_sample_archive(ctx: ImportBundleCommitContext, payload: dict) -> dict:
    preview_id = payload.get("previewId", "")
    ctx.cleanup_expired_previews()
    entry = ctx.import_previews.get(preview_id)
    if not entry:
        return {"ok": False, "error": "previewId 无效或已过期", "status": 400}
    _incoming, result = ctx.load_import_preview_payload(entry)
    decisions = payload.get("decisions")
    if not isinstance(decisions, dict) or not decisions:
        decisions = sample_archive_default_decisions(result or {})
    next_payload = {
        "previewId": preview_id,
        "decisions": decisions,
    }
    return commit_import_bundle(ctx, next_payload)
