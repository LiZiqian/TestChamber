"""Import migration and defaulting for legacy and ChamberData bundles."""

from __future__ import annotations

import copy


def _ensure_list(obj: dict, key: str) -> list:
    if not isinstance(obj.get(key), list):
        obj[key] = []
    return obj[key]


def _ensure_dict_list(obj: dict, key: str) -> list:
    values = obj.get(key)
    if not isinstance(values, list):
        obj[key] = []
        return obj[key]
    obj[key] = [item for item in values if isinstance(item, dict)]
    return obj[key]


def _text(value: object, default: str = "") -> str:
    if value is None:
        return default
    if isinstance(value, bool):
        return default
    if isinstance(value, (dict, list, tuple, set)):
        return default
    return str(value)


def _ensure_text(obj: dict, key: str, default: str = "") -> str:
    obj[key] = _text(obj.get(key), default)
    return obj[key]


def _ensure_int(obj: dict, key: str, default: int = 0) -> int:
    try:
        if isinstance(obj.get(key), bool):
            raise ValueError
        obj[key] = int(obj.get(key))
    except (TypeError, ValueError):
        obj[key] = default
    return obj[key]


def _ensure_id_list(obj: dict, key: str) -> list:
    values = obj.get(key)
    if not isinstance(values, list):
        obj[key] = []
        return obj[key]
    result = []
    for item in values:
        value = _text(item, "")
        if value:
            result.append(value)
    obj[key] = result
    return obj[key]


def _ensure_text_list(obj: dict, key: str) -> list:
    values = obj.get(key)
    if not isinstance(values, list):
        obj[key] = []
        return obj[key]
    obj[key] = [_text(item) for item in values if _text(item)]
    return obj[key]


def _ensure_dict(obj: dict, key: str) -> dict:
    if not isinstance(obj.get(key), dict):
        obj[key] = {}
    return obj[key]


def normalize_import_state(state: dict, *, source_format: str = "") -> dict:
    """Return a canonical import state while preserving unknown harmless fields."""
    data = copy.deepcopy(state) if isinstance(state, dict) else {}
    data.setdefault("version", "")
    data.setdefault("currentProjectId", None)
    data.setdefault("currentStageId", None)
    _ensure_list(data, "users")
    _ensure_dict_list(data, "projects")
    _ensure_list(data, "testCaseMaster")
    library = _ensure_dict(data, "sampleLibrary")
    _ensure_dict_list(library, "categories")
    _ensure_dict_list(library, "logs")

    for project in data["projects"]:
        _ensure_text(project, "id")
        _ensure_text(project, "name")
        _ensure_text(project, "code")
        project["owner"] = _text(project.get("owner")) or _text(project.get("leader")) or _text(project.get("manager"))
        _ensure_dict_list(project, "members")
        _ensure_text_list(project, "locations")
        _ensure_list(project, "testCaseMaster")
        _ensure_dict_list(project, "stages")
        for stage in project["stages"]:
            _ensure_text(stage, "id")
            stage["projectId"] = _text(stage.get("projectId")) or project.get("id") or ""
            _ensure_text(stage, "name")
            _ensure_text_list(stage, "skuNames")
            _ensure_list(stage, "bom")
            _ensure_list(stage, "strategy")
            _ensure_list(stage, "progress")
            _ensure_dict_list(stage, "tasks")
            for task in stage["tasks"]:
                _ensure_text(task, "id")
                task["projectId"] = _text(task.get("projectId")) or project.get("id") or ""
                task["stageId"] = _text(task.get("stageId")) or stage.get("id") or ""
                _ensure_text(task, "category")
                _ensure_text(task, "testItem")
                task.setdefault("skuIndex", 0)
                _ensure_text(task, "status")
                _ensure_text(task, "owner")
                _ensure_text(task, "remark")
                task.setdefault("archived", False)
                _ensure_id_list(task, "sampleIds")
                _ensure_dict_list(task, "logs")
                _ensure_dict_list(task, "removedSampleRecords")
                _ensure_dict_list(task, "sampleFaultRecords")
                _ensure_dict_list(task, "resultUploads")
                issue_record = _ensure_dict(task, "issueRecord")
                _ensure_text(issue_record, "dtsNo")
                _ensure_text(issue_record, "isIssue")
                _ensure_text(issue_record, "issueNote")

    for category in library["categories"]:
        _ensure_text(category, "id")
        _ensure_text(category, "name")
        _ensure_text(category, "description")
        _ensure_dict_list(category, "samples")
        for sample in category["samples"]:
            _ensure_text(sample, "id")
            sample["categoryId"] = _text(sample.get("categoryId")) or category.get("id") or ""
            _ensure_text(sample, "sampleNo")
            _ensure_text(sample, "sn")
            _ensure_text(sample, "imei")
            _ensure_text(sample, "boardSn")
            sample.setdefault("isReassembled", False)
            _ensure_text(sample, "schemeNo")
            sample["status"] = _text(sample.get("status"), "闲置") or "闲置"
            _ensure_text(sample, "location")
            _ensure_text(sample, "owner")
            _ensure_text(sample, "borrower")
            _ensure_text(sample, "borrowDate")
            _ensure_text(sample, "importDate")
            _ensure_text(sample, "sourceStageName")
            _ensure_text(sample, "sourceSkuName")
            _ensure_text(sample, "initialResult")
            _ensure_list(sample, "initialResults")
            _ensure_list(sample, "problemRecords")
            _ensure_dict_list(sample, "photos")
            _ensure_dict_list(sample, "logs")
            for photo in sample["photos"]:
                _ensure_text(photo, "id")
                _ensure_text(photo, "name")
                _ensure_text(photo, "type")
                _ensure_int(photo, "size", 0)
                if "thumbSize" in photo:
                    _ensure_int(photo, "thumbSize", 0)
                if "thumbnailSize" in photo:
                    _ensure_int(photo, "thumbnailSize", 0)
                _ensure_text(photo, "uploadedAt")
                _ensure_text(photo, "relativePath")
                _ensure_text(photo, "url")
                _ensure_text(photo, "thumbRelativePath")
                _ensure_text(photo, "thumbUrl")

    data["_importNormalizedFrom"] = source_format or "unknown"
    return data
