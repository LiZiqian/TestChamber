from __future__ import annotations

import copy
import re
from typing import Any


TASK_FLOW_STATUSES = ("待下发", "进行中", "阻塞中", "正常完成", "异常终止")
TASK_RESULT_STATUSES = ("通过", "不通过")
PROGRESS_PLAN_KEYS = ("id", "strategyId", "category", "testItem", "skuIndex", "sampleSize")
SAMPLE_USAGE_STATUSES = ("闲置", "在位等待", "测试中", "已退库", "取走分析")
SAMPLE_QUALITY_STATUSES = ("无故障", "有故障")
REASSEMBLY_LABELS = ("非重组", "重组")

DISPLAY_FALLBACK_ALIASES = {
    "变更退出": "退出测试",
    "未设置": "待确认",
}

TASK_FLOW_ALIASES = {
    "": "待下发",
    "待下发": "待下发",
    "待执行": "待下发",
    "待启动": "待下发",
    "进行中": "进行中",
    "Testing": "进行中",
    "testing": "进行中",
    "阻塞": "阻塞中",
    "阻塞中": "阻塞中",
    "正常完成": "正常完成",
    "已完成": "正常完成",
    "完成": "正常完成",
    "通过": "正常完成",
    "Pass": "正常完成",
    "PASS": "正常完成",
    "pass": "正常完成",
    "异常完成": "异常终止",
    "异常终止": "异常终止",
    "失败": "异常终止",
    "Fail": "异常终止",
    "FAIL": "异常终止",
    "fail": "异常终止",
}

TASK_RESULT_ALIASES = {
    "通过": "通过",
    "Pass": "通过",
    "PASS": "通过",
    "pass": "通过",
    "OK": "通过",
    "ok": "通过",
    "正常": "通过",
    "不通过": "不通过",
    "失败": "不通过",
    "Fail": "不通过",
    "FAIL": "不通过",
    "fail": "不通过",
    "NG": "不通过",
    "ng": "不通过",
    "异常": "不通过",
}

SAMPLE_USAGE_ALIASES = {
    "": "闲置",
    "闲置": "闲置",
    "已分配": "在位等待",
    "在位等待": "在位等待",
    "进入测试任务": "测试中",
    "测试中": "测试中",
    "已退库": "已退库",
    "借出": "取走分析",
    "已借出": "取走分析",
    "取走分析": "取走分析",
    "已归还": "闲置",
    "待维修": "闲置",
    "报废": "闲置",
    "故障": "闲置",
}

SAMPLE_QUALITY_ALIASES = {
    "无故障": "无故障",
    "OK": "无故障",
    "ok": "无故障",
    "通过": "无故障",
    "正常": "无故障",
    "有故障": "有故障",
    "故障": "有故障",
    "Fail": "有故障",
    "FAIL": "有故障",
    "fail": "有故障",
    "失败": "有故障",
    "不通过": "有故障",
}

TEXT_REPLACEMENTS = (
    ("进入测试任务", "测试中"),
    ("异常完成", "异常终止"),
    ("待执行", "待下发"),
    ("待启动", "待下发"),
    ("已分配", "在位等待"),
    ("已借出", "取走分析"),
    ("借出", "取走分析"),
    ("已归还", "闲置"),
    ("待维修", "闲置"),
    ("报废", "闲置"),
    ("变更退出", "退出测试"),
    ("未设置", "待确认"),
    ("失败", "不通过"),
    ("OK", "无故障"),
)

TEXT_TOKEN_REPLACEMENTS = {
    "Pass": "通过",
    "PASS": "通过",
    "pass": "通过",
    "Fail": "不通过",
    "FAIL": "不通过",
    "fail": "不通过",
    "Testing": "进行中",
    "testing": "进行中",
}

TEXT_NORMALIZATION_SKIP_KEYS = {
    "id",
    "ids",
    "_id",
    "uuid",
    "key",
    "code",
    "name",
    "filename",
    "file_name",
    "originalname",
    "original_name",
    "relativepath",
    "relative_path",
    "path",
    "url",
    "sampleid",
    "sampleids",
    "sample_id",
    "sample_ids",
    "taskid",
    "taskids",
    "task_id",
    "task_ids",
    "projectid",
    "projectids",
    "project_id",
    "project_ids",
    "stageid",
    "stageids",
    "stage_id",
    "stage_ids",
    "categoryid",
    "categoryids",
    "category_id",
    "category_ids",
    "progressid",
    "progressids",
    "progress_id",
    "progress_ids",
    "assetid",
    "assetids",
    "asset_id",
    "asset_ids",
    "photoid",
    "photoids",
    "photo_id",
    "photo_ids",
    "eventid",
    "eventids",
    "event_id",
    "event_ids",
    "sn",
    "imei",
    "boardsn",
    "board_sn",
    "sampleno",
    "sample_no",
    "serial",
    "serialno",
    "serial_no",
}


def should_skip_status_text_normalization(key: Any, skip_keys: set[str] | None = None) -> bool:
    key_text = str(key or "")
    lowered = key_text.replace("-", "_").lower()
    compact = lowered.replace("_", "")
    if key_text in (skip_keys or set()) or lowered in (skip_keys or set()) or compact in TEXT_NORMALIZATION_SKIP_KEYS:
        return True
    return compact.endswith("id") or compact.endswith("ids")


def _text(value: Any) -> str:
    return str(value or "").strip()


def normalize_task_flow_status(task_or_status: Any, *, completed: bool | None = None) -> str:
    if isinstance(task_or_status, dict):
        status = _text(task_or_status.get("status"))
        is_completed = bool(task_or_status.get("completed")) if completed is None else completed
        if status in {"异常完成", "异常终止", "失败", "Fail", "FAIL", "fail"}:
            return "异常终止"
        if is_completed and status not in {"异常终止", "异常完成", "失败", "Fail", "FAIL", "fail"}:
            return "正常完成"
        return TASK_FLOW_ALIASES.get(status, "待下发")
    status = _text(task_or_status)
    return TASK_FLOW_ALIASES.get(status, "待下发")


def normalize_task_stored_status(status: Any, *, completed: bool | None = None) -> str:
    return normalize_task_flow_status(status, completed=completed)


def normalize_task_result_value(value: Any) -> str:
    raw = _text(value)
    return TASK_RESULT_ALIASES.get(raw, raw if raw in TASK_RESULT_STATUSES else "")


def normalize_sample_usage_status(value: Any) -> str:
    raw = _text(value)
    return SAMPLE_USAGE_ALIASES.get(raw, raw if raw in SAMPLE_USAGE_STATUSES else "闲置")


def normalize_sample_quality_value(value: Any, *, has_problem: bool | None = None) -> str:
    if has_problem is not None:
        return "有故障" if has_problem else "无故障"
    raw = _text(value)
    return SAMPLE_QUALITY_ALIASES.get(raw, raw if raw in SAMPLE_QUALITY_STATUSES else "无故障")


def normalize_reassembly_label(value: Any) -> str:
    if isinstance(value, bool):
        return "重组" if value else "非重组"
    if isinstance(value, (int, float)):
        return "重组" if int(value) == 1 else "非重组"
    raw = _text(value).lower()
    if raw in {"是", "yes", "y", "true", "1", "重组", "reassembled"}:
        return "重组"
    return "非重组"


def normalize_display_fallback(value: Any) -> str:
    raw = _text(value)
    return DISPLAY_FALLBACK_ALIASES.get(raw, raw)


def normalize_status_text(text: Any) -> Any:
    if not isinstance(text, str):
        return text
    if not text:
        return text
    result = text
    for old, new in TEXT_REPLACEMENTS:
        result = result.replace(old, new)
    result = re.sub(r"(?<![无有])故障", "有故障", result)
    def replace_token(match: re.Match[str]) -> str:
        return TEXT_TOKEN_REPLACEMENTS.get(match.group(0), match.group(0))
    return re.sub(r"\b(Pass|PASS|pass|Fail|FAIL|fail|Testing|testing)\b", replace_token, result)


def normalize_business_value(value: Any, *, skip_keys: set[str] | None = None) -> Any:
    skip = skip_keys or set()
    if isinstance(value, dict):
        changed = False
        result = {}
        for key, item in value.items():
            if should_skip_status_text_normalization(key, skip):
                result[key] = item
                continue
            normalized = normalize_business_value(item, skip_keys=skip)
            result[key] = normalized
            changed = changed or normalized != item
        return result if changed else value
    if isinstance(value, list):
        result = [normalize_business_value(item, skip_keys=skip) for item in value]
        return result if result != value else value
    if isinstance(value, str):
        return normalize_status_text(value)
    return value


def normalize_problem_records(records: Any) -> list:
    if not isinstance(records, list):
        return []
    normalized = []
    for record in records:
        if isinstance(record, dict):
            item = copy.deepcopy(record)
            for key in ("description", "problem", "source", "taskLabel", "task"):
                if key in item:
                    item[key] = normalize_status_text(item.get(key) or "")
            normalized.append(item)
        elif isinstance(record, str):
            text = normalize_status_text(record).strip()
            if text:
                normalized.append(text)
    return normalized


def normalize_task_payload(task: Any) -> Any:
    if not isinstance(task, dict):
        return task
    original_status = task.get("status")
    original_completed = task.get("completed")
    item = normalize_business_value(copy.deepcopy(task), skip_keys={"photos", "name", "fileName", "file_name", "originalName", "original_name", "relativePath", "path", "url"})
    item["status"] = normalize_task_stored_status({"status": original_status, "completed": original_completed})
    flow = normalize_task_flow_status(item)
    item["completed"] = flow in {"正常完成", "异常终止"}
    if item["completed"]:
        item["completionType"] = flow
    for key in ("latestResult", "result"):
        if key in item:
            normalized = normalize_task_result_value(item.get(key))
            if normalized:
                item[key] = normalized
    if isinstance(item.get("resultDraft"), dict):
        draft = item["resultDraft"]
        normalized = normalize_task_result_value(draft.get("result"))
        if normalized:
            draft["result"] = normalized
        for sample in draft.get("samples") or []:
            if isinstance(sample, dict):
                sample["fault"] = normalize_sample_quality_value(sample.get("fault"), has_problem=None)
    for upload in item.get("resultUploads") or []:
        if not isinstance(upload, dict):
            continue
        normalized = normalize_task_result_value(upload.get("result"))
        if normalized:
            upload["result"] = normalized
        for sample in upload.get("samples") or []:
            if isinstance(sample, dict):
                sample["fault"] = normalize_sample_quality_value(sample.get("fault"), has_problem=None)
                if "destination" in sample:
                    sample["destination"] = normalize_sample_usage_status(sample.get("destination"))
    for fault in item.get("sampleFaultRecords") or []:
        if isinstance(fault, dict):
            if "result" in fault:
                normalized = normalize_task_result_value(fault.get("result"))
                if normalized:
                    fault["result"] = normalized
            if "fault" in fault and not isinstance(fault.get("fault"), bool):
                fault["fault"] = normalize_sample_quality_value(fault.get("fault")) == "有故障"
    return item


def normalize_progress_plan_payload(progress: Any) -> Any:
    if not isinstance(progress, dict):
        return progress
    return {key: copy.deepcopy(progress[key]) for key in PROGRESS_PLAN_KEYS if key in progress}


def normalize_stage_payload(stage: Any) -> Any:
    if not isinstance(stage, dict):
        return stage
    item = normalize_business_value(copy.deepcopy(stage), skip_keys={"photos", "name", "fileName", "file_name", "originalName", "original_name", "relativePath", "path", "url"})
    if isinstance(item.get("progress"), list):
        item["progress"] = [
            normalize_progress_plan_payload(progress)
            for progress in item["progress"]
            if isinstance(progress, dict)
        ]
    if isinstance(item.get("tasks"), list):
        item["tasks"] = [normalize_task_payload(task) for task in item["tasks"]]
    return item


def normalize_project_payload(project: Any) -> Any:
    if not isinstance(project, dict):
        return project
    item = normalize_business_value(copy.deepcopy(project), skip_keys={"photos", "name", "fileName", "file_name", "originalName", "original_name", "relativePath", "path", "url"})
    if isinstance(item.get("stages"), list):
        item["stages"] = [normalize_stage_payload(stage) for stage in item["stages"]]
    return item


def normalize_sample_payload(sample: Any) -> Any:
    if not isinstance(sample, dict):
        return sample
    original_status = sample.get("status")
    original_effective_status = sample.get("effectiveStatus", sample.get("effective_status"))
    original_problem_state = sample.get("problemState", sample.get("fault"))
    item = normalize_business_value(copy.deepcopy(sample), skip_keys={"photos", "name", "fileName", "file_name", "originalName", "original_name", "relativePath", "path", "url"})
    if any(
        normalize_sample_quality_value(value) == "有故障"
        for value in (original_status, original_effective_status, original_problem_state)
        if _text(value)
    ):
        item["hasProblem"] = True
        item["problemState"] = "有故障"
    item["status"] = normalize_sample_usage_status(item.get("status"))
    item["problemRecords"] = normalize_problem_records(item.get("problemRecords"))
    if isinstance(item.get("initialResults"), list):
        item["initialResults"] = [normalize_status_text(text) for text in item["initialResults"] if str(text or "").strip()]
    if isinstance(item.get("initialResult"), str):
        item["initialResult"] = normalize_status_text(item["initialResult"])
    return item


def normalize_sample_category_payload(category: Any) -> Any:
    if not isinstance(category, dict):
        return category
    item = normalize_business_value(copy.deepcopy(category), skip_keys={"photos", "name", "fileName", "file_name", "originalName", "original_name", "relativePath", "path", "url"})
    if isinstance(item.get("samples"), list):
        item["samples"] = [normalize_sample_payload(sample) for sample in item["samples"]]
    return item


def normalize_state_payload(data: Any) -> Any:
    if not isinstance(data, dict):
        return data
    item = normalize_business_value(copy.deepcopy(data), skip_keys={"photos", "name", "fileName", "file_name", "originalName", "original_name", "relativePath", "path", "url"})
    if isinstance(item.get("projects"), list):
        item["projects"] = [normalize_project_payload(project) for project in item["projects"]]
    library = item.get("sampleLibrary")
    if isinstance(library, dict):
        if isinstance(library.get("categories"), list):
            library["categories"] = [normalize_sample_category_payload(category) for category in library["categories"]]
        if isinstance(library.get("logs"), list):
            library["logs"] = normalize_business_value(library["logs"], skip_keys={"photos", "name", "fileName", "file_name", "originalName", "original_name", "relativePath", "path", "url"})
    return item
