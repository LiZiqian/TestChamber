from __future__ import annotations

import copy
import json
import uuid
from datetime import datetime, timezone
from pathlib import Path


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def empty_data(app_version: str) -> dict:
    return {
        "version": app_version,
        "currentProjectId": None,
        "currentStageId": None,
        "users": [],
        "projects": [],
        "sampleLibrary": {"categories": [], "logs": []},
        "testCaseMaster": [],
    }


def json_dumps(obj: object, *, pretty: bool = False) -> str:
    if pretty:
        return json.dumps(obj, ensure_ascii=False, indent=2)
    return json.dumps(obj, ensure_ascii=False, separators=(",", ":"))


def stable_json(obj: object) -> str:
    return json.dumps(obj, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


def json_obj(text: str | None, fallback: object | None = None):
    try:
        return json.loads(text or "")
    except Exception:
        return copy.deepcopy(fallback)


def load_deployment_id(deployment_file: Path) -> str:
    """读取部署身份文件，返回 deploymentId 或空字符串"""
    try:
        if deployment_file.is_file():
            meta = json.loads(deployment_file.read_text(encoding="utf-8"))
            return str(meta.get("deploymentId") or "")
    except Exception:
        pass
    return ""


def ensure_deployment_id(deployment_file: Path) -> str:
    """确保部署身份文件存在，不存在则创建并返回新 ID"""
    existing = load_deployment_id(deployment_file)
    if existing:
        return existing
    created_at = now_iso()
    did = f"deploy_{created_at.replace('-','').replace(':','').replace('T','_')[:15]}_{uuid.uuid4().hex[:8]}"
    meta = {"deploymentId": did, "createdAt": created_at, "name": "未命名部署"}
    deployment_file.write_text(json_dumps(meta, pretty=True), encoding="utf-8")
    return did
