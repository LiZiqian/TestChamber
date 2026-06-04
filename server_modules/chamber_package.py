"""ChamberData import/export package protocol helpers.

The server still exposes the historical HTTP endpoints, but the on-disk bundle
format is versioned here instead of being tied to the browser app state shape.
"""

from __future__ import annotations

import copy
import hashlib
import json
from pathlib import Path
from typing import Callable


LEGACY_FORMAT_V1 = "testchamber-export-bundle-v1"
FORMAT_V2 = "chamberdata-package-v2"
PROTOCOL_NAME = "ChamberData"
SCHEMA_VERSION = 2

DOMAIN_PATHS = {
    "app": "domains/app.json",
    "projects": "domains/projects.json",
    "stages": "domains/stages.json",
    "tasks": "domains/tasks.json",
    "sampleCategories": "domains/sample-categories.json",
    "samples": "domains/samples.json",
    "sampleAssets": "domains/sample-assets.json",
    "sampleEvents": "domains/sample-events.json",
}
ASSET_INDEX_PATH = "assets/index.json"
CHECKSUMS_PATH = "checksums.json"
CHECKSUM_REQUIRED_PATHS = frozenset({"manifest.json", ASSET_INDEX_PATH, *DOMAIN_PATHS.values()})
LIST_DOMAIN_KEYS = tuple(key for key in DOMAIN_PATHS if key != "app")
DOMAIN_COUNT_KEYS = {
    "projects": "projects",
    "stages": "stages",
    "tasks": "tasks",
    "sampleCategories": "sampleCategories",
    "samples": "samples",
    "sampleAssets": "sampleAssets",
    "sampleEvents": "sampleEvents",
}


def json_dumps(obj: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def sha256_bytes(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def sha256_file(path: Path) -> str:
    digest = hashlib.sha256()
    with Path(path).open("rb") as fh:
        while True:
            chunk = fh.read(1024 * 1024)
            if not chunk:
                break
            digest.update(chunk)
    return digest.hexdigest()


def _safe_data_path(data_dir: Path, relative_path: str) -> Path | None:
    if not relative_path:
        return None
    target = (data_dir / relative_path).resolve()
    root = data_dir.resolve()
    if target != root and root not in target.parents:
        return None
    return target


def _asset_entry(data_dir: Path, sample_id: str, photo_id: str, role: str, relative_path: str) -> dict:
    filename = Path(relative_path or "").name
    zip_path = f"assets/samples/{sample_id}/photos/{filename}" if filename else ""
    source_path = _safe_data_path(data_dir, relative_path)
    exists = bool(source_path and source_path.is_file())
    entry = {
        "assetId": f"{photo_id}::{role}",
        "entity": "sample",
        "entityId": sample_id,
        "kind": "sample_photo",
        "role": role,
        "metadataId": photo_id,
        "sourceRelativePath": relative_path or "",
        "zipPath": zip_path,
        "fileName": filename,
        "exists": exists,
        "bytes": 0,
        "sha256": "",
    }
    if exists and source_path:
        raw = source_path.read_bytes()
        entry["bytes"] = len(raw)
        entry["sha256"] = sha256_bytes(raw)
    return entry


def build_domain_documents(state: dict, data_dir: Path) -> tuple[dict[str, object], dict]:
    """Flatten current app state into stable ChamberData domain documents."""
    projects: list[dict] = []
    stages: list[dict] = []
    tasks: list[dict] = []
    sample_categories: list[dict] = []
    samples: list[dict] = []
    sample_assets: list[dict] = []
    asset_entries: list[dict] = []

    for project in state.get("projects") or []:
        if not isinstance(project, dict):
            continue
        project_id = str(project.get("id") or "")
        project_doc = copy.deepcopy(project)
        project_doc.pop("stages", None)
        projects.append(project_doc)
        for stage in project.get("stages") or []:
            if not isinstance(stage, dict):
                continue
            stage_id = str(stage.get("id") or "")
            stage_doc = copy.deepcopy(stage)
            stage_doc["projectId"] = project_id
            stage_doc.pop("tasks", None)
            stages.append(stage_doc)
            for task in stage.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                task_doc = copy.deepcopy(task)
                task_doc["projectId"] = project_id
                task_doc["stageId"] = stage_id
                tasks.append(task_doc)

    for category in (state.get("sampleLibrary") or {}).get("categories") or []:
        if not isinstance(category, dict):
            continue
        category_id = str(category.get("id") or "")
        category_doc = copy.deepcopy(category)
        category_doc.pop("samples", None)
        sample_categories.append(category_doc)
        for sample in category.get("samples") or []:
            if not isinstance(sample, dict):
                continue
            sample_id = str(sample.get("id") or "")
            sample_doc = copy.deepcopy(sample)
            sample_doc["categoryId"] = category_id
            photos = sample_doc.pop("photos", [])
            sample_doc.pop("logs", None)
            samples.append(sample_doc)
            for photo in photos or []:
                if not isinstance(photo, dict):
                    continue
                photo_doc = copy.deepcopy(photo)
                photo_doc["sampleId"] = sample_id
                sample_assets.append(photo_doc)
                photo_id = str(photo.get("id") or "")
                rel = str(photo.get("relativePath") or "")
                if rel:
                    asset_entries.append(_asset_entry(data_dir, sample_id, photo_id, "original", rel))
                thumb_rel = str(photo.get("thumbRelativePath") or "")
                if thumb_rel:
                    asset_entries.append(_asset_entry(data_dir, sample_id, photo_id, "thumbnail", thumb_rel))

    app_doc = copy.deepcopy(state)
    app_doc["projects"] = []
    library_doc = copy.deepcopy((state.get("sampleLibrary") or {}) if isinstance(state.get("sampleLibrary"), dict) else {})
    library_doc["categories"] = []
    library_doc["logs"] = []
    app_doc["sampleLibrary"] = library_doc
    sample_events = [
        copy.deepcopy(log)
        for log in (state.get("sampleLibrary") or {}).get("logs") or []
        if isinstance(log, dict)
    ]

    return {
        "app": app_doc,
        "projects": projects,
        "stages": stages,
        "tasks": tasks,
        "sampleCategories": sample_categories,
        "samples": samples,
        "sampleAssets": sample_assets,
        "sampleEvents": sample_events,
    }, {
        "schemaVersion": 1,
        "assets": asset_entries,
    }


def build_export_package(
    state: dict,
    *,
    data_dir: Path,
    app_version: str,
    server_version: str,
    exported_at: str,
    export_id: str,
    deployment_id: str,
    revision: int,
) -> dict:
    domains, asset_index = build_domain_documents(state, data_dir)
    manifest = {
        "format": FORMAT_V2,
        "protocol": PROTOCOL_NAME,
        "schemaVersion": SCHEMA_VERSION,
        "appVersion": app_version,
        "serverVersion": server_version,
        "exportedAt": exported_at,
        "exportId": export_id,
        "sourceDeploymentId": deployment_id,
        "sourceName": "",
        "revision": revision,
        "domainPaths": DOMAIN_PATHS,
        "assetIndexPath": ASSET_INDEX_PATH,
        "legacyCompatible": False,
        "counts": {
            "projects": len(domains["projects"]),
            "stages": len(domains["stages"]),
            "tasks": len(domains["tasks"]),
            "sampleCategories": len(domains["sampleCategories"]),
            "samples": len(domains["samples"]),
            "sampleAssets": len(domains["sampleAssets"]),
            "sampleEvents": len(domains["sampleEvents"]),
            "assetFiles": len(asset_index["assets"]),
        },
    }
    return {"manifest": manifest, "domains": domains, "assetIndex": asset_index}


def package_payloads(package: dict, *, pretty: bool = True) -> dict[str, str]:
    payloads = {"manifest.json": json_dumps(package["manifest"], pretty=pretty)}
    domains = package.get("domains") or {}
    for key, path in DOMAIN_PATHS.items():
        payloads[path] = json_dumps(domains.get(key, [] if key != "app" else {}), pretty=pretty)
    payloads[ASSET_INDEX_PATH] = json_dumps(package.get("assetIndex") or {"assets": []}, pretty=pretty)
    return payloads


def is_chamberdata_manifest(manifest: dict) -> bool:
    return str(manifest.get("format") or "") == FORMAT_V2 or str(manifest.get("protocol") or "") == PROTOCOL_NAME


def state_from_domain_documents(manifest: dict, domains: dict[str, object]) -> dict:
    """Rehydrate ChamberData domain docs into the current canonical state shape."""
    app_doc = copy.deepcopy(domains.get("app") or {})
    state = app_doc if isinstance(app_doc, dict) else {}
    state["version"] = state.get("version") or manifest.get("appVersion") or ""
    state["currentProjectId"] = state.get("currentProjectId")
    state["currentStageId"] = state.get("currentStageId")
    state["users"] = state.get("users") if isinstance(state.get("users"), list) else []
    state["projects"] = []
    library_doc = state.get("sampleLibrary") if isinstance(state.get("sampleLibrary"), dict) else {}
    sample_library = copy.deepcopy(library_doc)
    sample_library["categories"] = []
    sample_library["logs"] = []
    state["sampleLibrary"] = sample_library
    state["testCaseMaster"] = state.get("testCaseMaster") if isinstance(state.get("testCaseMaster"), list) else []

    projects_by_id: dict[str, dict] = {}
    for project in domains.get("projects") or []:
        if not isinstance(project, dict):
            continue
        item = copy.deepcopy(project)
        item.setdefault("stages", [])
        pid = str(item.get("id") or "")
        state["projects"].append(item)
        if pid:
            projects_by_id[pid] = item

    stages_by_id: dict[str, dict] = {}
    for stage in domains.get("stages") or []:
        if not isinstance(stage, dict):
            continue
        item = copy.deepcopy(stage)
        project_id = str(item.get("projectId") or "")
        item.setdefault("tasks", [])
        sid = str(item.get("id") or "")
        if project_id in projects_by_id:
            projects_by_id[project_id].setdefault("stages", []).append(item)
        if sid:
            stages_by_id[sid] = item

    for task in domains.get("tasks") or []:
        if not isinstance(task, dict):
            continue
        item = copy.deepcopy(task)
        stage_id = str(item.get("stageId") or "")
        if stage_id in stages_by_id:
            stages_by_id[stage_id].setdefault("tasks", []).append(item)

    categories_by_id: dict[str, dict] = {}
    for category in domains.get("sampleCategories") or []:
        if not isinstance(category, dict):
            continue
        item = copy.deepcopy(category)
        item.setdefault("samples", [])
        cid = str(item.get("id") or "")
        state["sampleLibrary"]["categories"].append(item)
        if cid:
            categories_by_id[cid] = item

    samples_by_id: dict[str, dict] = {}
    for sample in domains.get("samples") or []:
        if not isinstance(sample, dict):
            continue
        item = copy.deepcopy(sample)
        item.setdefault("photos", [])
        cid = str(item.get("categoryId") or "")
        sid = str(item.get("id") or "")
        if cid in categories_by_id:
            categories_by_id[cid].setdefault("samples", []).append(item)
        if sid:
            samples_by_id[sid] = item

    for asset in domains.get("sampleAssets") or []:
        if not isinstance(asset, dict):
            continue
        sample_id = str(asset.get("sampleId") or "")
        if sample_id in samples_by_id:
            photo = copy.deepcopy(asset)
            photo.pop("sampleId", None)
            samples_by_id[sample_id].setdefault("photos", []).append(photo)

    events = domains.get("sampleEvents")
    state["sampleLibrary"]["logs"] = copy.deepcopy(events) if isinstance(events, list) else []
    return state


def read_domain_documents(read_json: Callable[[str], object]) -> dict[str, object]:
    domains: dict[str, object] = {}
    for key, path in DOMAIN_PATHS.items():
        domains[key] = read_json(path)
    return domains


def read_asset_index(read_json: Callable[[str], object]) -> dict:
    value = read_json(ASSET_INDEX_PATH)
    if not isinstance(value, dict) or not isinstance(value.get("assets"), list):
        raise ValueError(f"导入包 {ASSET_INDEX_PATH} 格式不正确")
    return value


def _manifest_count_value(counts: dict, key: str) -> int | None:
    if key not in counts:
        return None
    value = counts.get(key)
    if isinstance(value, bool):
        raise ValueError(f"导入包 manifest counts 格式不正确: {key}")
    try:
        return int(value)
    except (TypeError, ValueError):
        raise ValueError(f"导入包 manifest counts 格式不正确: {key}")


def validate_domain_documents(manifest: dict, domains: dict[str, object], asset_index: dict | None) -> None:
    if not isinstance(domains.get("app"), dict):
        raise ValueError(f"导入包 {DOMAIN_PATHS['app']} 格式不正确")
    for key in LIST_DOMAIN_KEYS:
        if not isinstance(domains.get(key), list):
            raise ValueError(f"导入包 {DOMAIN_PATHS[key]} 格式不正确")
        for idx, item in enumerate(domains.get(key) or [], start=1):
            if not isinstance(item, dict):
                raise ValueError(f"导入包 {DOMAIN_PATHS[key]} 第 {idx} 项格式不正确")
    if asset_index is not None:
        for idx, item in enumerate(asset_index.get("assets") or [], start=1):
            if not isinstance(item, dict):
                raise ValueError(f"导入包 {ASSET_INDEX_PATH} 第 {idx} 项格式不正确")

    counts = manifest.get("counts") if isinstance(manifest, dict) else None
    if not isinstance(counts, dict):
        return

    actual_counts = {count_key: len(domains[domain_key]) for count_key, domain_key in DOMAIN_COUNT_KEYS.items()}
    actual_counts["assetFiles"] = len(asset_entries(asset_index))
    for key, actual in actual_counts.items():
        expected = _manifest_count_value(counts, key)
        if expected is not None and expected != actual:
            raise ValueError(f"导入包 manifest counts 不匹配: {key}")


def asset_entries(asset_index: dict | None) -> list[dict]:
    if not isinstance(asset_index, dict):
        return []
    return [item for item in (asset_index.get("assets") or []) if isinstance(item, dict)]


def sample_photo_asset_lookup(asset_index: dict | None) -> dict[tuple[str, str, str], dict]:
    lookup: dict[tuple[str, str, str], dict] = {}
    for asset in asset_entries(asset_index):
        if str(asset.get("entity") or "") != "sample":
            continue
        if str(asset.get("kind") or "") != "sample_photo":
            continue
        entity_id = str(asset.get("entityId") or "")
        metadata_id = str(asset.get("metadataId") or "")
        role = str(asset.get("role") or "original")
        if entity_id and metadata_id:
            lookup[(entity_id, metadata_id, role)] = asset
    return lookup


def safe_package_member_path(root_dir: Path, member_path: str) -> Path | None:
    if not member_path:
        return None
    root = Path(root_dir).resolve()
    target = (root / member_path.replace("\\", "/")).resolve()
    if target == root or root in target.parents:
        return target
    return None


def verify_checksums(root_dir: Path, checksums: dict | None) -> None:
    """Validate ChamberData package payload checksums when checksums.json exists."""
    if checksums is None:
        return
    if not isinstance(checksums, dict):
        raise ValueError("导入包 checksums.json 格式不正确")

    missing_required = sorted(path for path in CHECKSUM_REQUIRED_PATHS if path not in checksums)
    if missing_required:
        raise ValueError(f"导入包 checksums.json 缺少: {missing_required[0]}")

    for rel_path, expected in checksums.items():
        rel_path = str(rel_path or "")
        if rel_path == CHECKSUMS_PATH:
            continue
        expected_hash = str(expected or "").strip().lower()
        if len(expected_hash) != 64 or any(ch not in "0123456789abcdef" for ch in expected_hash):
            raise ValueError(f"导入包 checksum 格式不正确: {rel_path}")
        target = safe_package_member_path(root_dir, rel_path)
        if target is None:
            raise ValueError(f"导入包 checksum 包含不安全路径: {rel_path}")
        if not target.is_file():
            raise ValueError(f"导入包 checksum 引用缺失文件: {rel_path}")
        actual_hash = sha256_file(target)
        if actual_hash != expected_hash:
            raise ValueError(f"导入包 checksum 不匹配: {rel_path}")
