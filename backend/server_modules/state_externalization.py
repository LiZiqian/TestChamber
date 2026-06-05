from __future__ import annotations

import copy
from typing import Callable


def iter_samples(data: dict):
    for category in data.get("sampleLibrary", {}).get("categories", []) or []:
        for sample in category.get("samples", []) or []:
            yield category, sample


def find_sample(data: dict, sample_id: str) -> tuple[dict | None, dict | None]:
    for category, sample in iter_samples(data):
        if str(sample.get("id")) == str(sample_id):
            return category, sample
    return None, None


def sample_index_by_id(data: dict) -> dict[str, dict]:
    return {
        str(sample.get("id")): sample
        for _, sample in iter_samples(data)
        if sample.get("id")
    }


def split_state_for_storage(data: dict, app_version: str) -> dict:
    stored = copy.deepcopy(data)
    stored["version"] = app_version
    stored.pop("peoplePool", None)
    stored.pop("locationPool", None)
    stored["projects"] = []
    stored["projectsExternalized"] = {
        "schema": "project_tables_v1",
        "note": "Projects, stages, tasks and task logs are stored in normalized SQLite tables.",
    }
    stored["sampleLibrary"] = {
        "externalized": True,
        "schema": "sample_tables_v1",
        "note": "样机库数据已外置到 sample_categories / sample_records / sample_assets 表。",
    }
    return stored


def hydrate_externalized_sample_fields(
    new_data: dict,
    current_data: dict,
    *,
    content_hash: Callable[[object], str],
) -> None:
    """Preserve externally loaded sample photos/events when a compact client saves."""
    library = new_data.get("sampleLibrary") or {}
    current_library = current_data.get("sampleLibrary") or {}

    if library.get("photosExternalized"):
        current_samples = sample_index_by_id(current_data)
        for _, sample in iter_samples(new_data):
            current_sample = current_samples.get(str(sample.get("id") or ""))
            if not current_sample:
                sample["photos"] = list(sample.get("photos") or [])
                sample["photoCount"] = len(sample["photos"])
                sample["photosLoaded"] = True
                continue
            if sample.get("photosLoaded") is True:
                sample["photoCount"] = len(sample.get("photos") or [])
                continue
            if current_sample.get("photosLoaded") is True:
                preserved = copy.deepcopy(current_sample.get("photos") or [])
                sample["photos"] = preserved
                sample["photoCount"] = len(preserved)
                sample["photosLoaded"] = True
            else:
                sample["photos"] = list(sample.get("photos") or [])
                sample["photoCount"] = int(sample.get("photoCount") or current_sample.get("photoCount") or 0)
                sample["photosLoaded"] = False

    if library.get("eventsExternalized"):
        incoming_logs = [log for log in (library.get("logs") or []) if isinstance(log, dict)]
        merged_logs = []
        seen = set()
        for log in [*(current_library.get("logs") or []), *incoming_logs]:
            if not isinstance(log, dict):
                continue
            key = str(log.get("id") or "") or content_hash(log)
            if key in seen:
                continue
            seen.add(key)
            merged_logs.append(copy.deepcopy(log))
        library["logs"] = merged_logs

    library.pop("photosExternalized", None)
    library.pop("eventsExternalized", None)
