from __future__ import annotations

import copy
import hashlib
import json


def stable_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def empty_data() -> dict:
    return {
        "projects": [],
        "sampleLibrary": {"categories": [], "logs": []},
        "view": {},
    }


def list_item_key(item: object, index: int) -> str:
    if isinstance(item, dict) and item.get("id"):
        return str(item.get("id"))
    digest = hashlib.sha1(stable_json(item).encode("utf-8")).hexdigest()
    return f"__hash_{digest}_{index}"


def normalize_json_list(value: object) -> list:
    return value if isinstance(value, list) else []


def to_int(value: object, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def merge_record(base: dict, new: dict, current: dict, child_specs: dict[str, dict] | None = None) -> dict:
    child_specs = child_specs or {}
    merged = copy.deepcopy(current if isinstance(current, dict) else {})
    base = base if isinstance(base, dict) else {}
    new = new if isinstance(new, dict) else {}

    for key in set(base.keys()) | set(new.keys()) | set(merged.keys()):
        if key in child_specs:
            continue
        base_val = base.get(key)
        new_has_key = key in new
        new_val = new.get(key)
        if new_has_key and stable_json(new_val) != stable_json(base_val):
            merged[key] = copy.deepcopy(new_val)

    for key, spec in child_specs.items():
        merged[key] = merge_list_by_id(
            normalize_json_list(base.get(key)),
            normalize_json_list(new.get(key)),
            normalize_json_list((current or {}).get(key) if isinstance(current, dict) else []),
            spec,
        )
    return merged


def merge_list_by_id(base_list: list, new_list: list, current_list: list, child_specs: dict[str, dict] | None = None) -> list:
    child_specs = child_specs or {}
    base_map = {list_item_key(item, idx): item for idx, item in enumerate(base_list)}
    new_map = {list_item_key(item, idx): item for idx, item in enumerate(new_list)}
    current_map = {list_item_key(item, idx): item for idx, item in enumerate(current_list)}
    merged_map: dict[str, object] = {key: copy.deepcopy(value) for key, value in current_map.items()}

    for idx, item in enumerate(new_list):
        key = list_item_key(item, idx)
        base_item = base_map.get(key)
        current_item = current_map.get(key)
        if base_item is None:
            if isinstance(item, dict) and isinstance(current_item, dict):
                merged_map[key] = merge_record({}, item, current_item, child_specs)
            elif key not in current_map:
                merged_map[key] = copy.deepcopy(item)
            continue
        if current_item is None:
            if stable_json(item) != stable_json(base_item):
                merged_map[key] = copy.deepcopy(item)
            continue
        if isinstance(item, dict) and isinstance(base_item, dict) and isinstance(current_item, dict):
            merged_map[key] = merge_record(base_item, item, current_item, child_specs)
        elif stable_json(item) != stable_json(base_item):
            merged_map[key] = copy.deepcopy(item)

    for idx, item in enumerate(base_list):
        key = list_item_key(item, idx)
        if key in new_map or key not in merged_map:
            continue
        current_item = current_map.get(key)
        if stable_json(current_item) == stable_json(item):
            merged_map.pop(key, None)

    ordered_keys: list[str] = []
    for idx, item in enumerate(new_list):
        key = list_item_key(item, idx)
        if key in merged_map and key not in ordered_keys:
            ordered_keys.append(key)
    for idx, item in enumerate(current_list):
        key = list_item_key(item, idx)
        if key in merged_map and key not in ordered_keys:
            ordered_keys.append(key)
    return [merged_map[key] for key in ordered_keys]


PROJECT_CHILDREN = {
    "stages": {
        "tasks": {
            "logs": {},
        },
    },
}


SAMPLE_CATEGORY_CHILDREN = {
    "samples": {
        "logs": {},
        "photos": {},
        "initialResults": {},
    },
}


def merge_sample_library(base_library: dict, new_library: dict, current_library: dict) -> dict:
    base_library = base_library if isinstance(base_library, dict) else {}
    new_library = new_library if isinstance(new_library, dict) else {}
    current_library = current_library if isinstance(current_library, dict) else {}
    merged = copy.deepcopy(current_library)
    merged["categories"] = merge_list_by_id(
        normalize_json_list(base_library.get("categories")),
        normalize_json_list(new_library.get("categories")),
        normalize_json_list(current_library.get("categories")),
        SAMPLE_CATEGORY_CHILDREN,
    )
    merged["logs"] = merge_list_by_id(
        normalize_json_list(base_library.get("logs")),
        normalize_json_list(new_library.get("logs")),
        normalize_json_list(current_library.get("logs")),
        {},
    )
    return merged


def merge_state(base_data: dict, new_data: dict, current_data: dict, *, app_version: str) -> dict:
    base_data = base_data if isinstance(base_data, dict) else empty_data()
    current_data = current_data if isinstance(current_data, dict) else empty_data()
    merged = copy.deepcopy(current_data)
    merged.pop("peoplePool", None)
    merged.pop("locationPool", None)
    for key in set(base_data.keys()) | set(new_data.keys()) | set(current_data.keys()):
        if key in ("projects", "sampleLibrary", "version", "peoplePool", "locationPool"):
            continue
        if stable_json(new_data.get(key)) != stable_json(base_data.get(key)):
            merged[key] = copy.deepcopy(new_data.get(key))

    merged["projects"] = merge_list_by_id(
        normalize_json_list(base_data.get("projects")),
        normalize_json_list(new_data.get("projects")),
        normalize_json_list(current_data.get("projects")),
        PROJECT_CHILDREN,
    )
    merged["sampleLibrary"] = merge_sample_library(
        base_data.get("sampleLibrary") or {},
        new_data.get("sampleLibrary") or {},
        current_data.get("sampleLibrary") or {},
    )
    merged["version"] = app_version
    return merged
