from __future__ import annotations

from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[2]
VERSION_FILE = PROJECT_ROOT / "VERSION"


def load_app_version() -> str:
    version = VERSION_FILE.read_text(encoding="utf-8").strip()
    if not version:
        raise RuntimeError(f"版本文件为空：{VERSION_FILE}")
    return version


APP_VERSION = load_app_version()
SERVER_VERSION = f"TestChamberServer/{APP_VERSION}"
