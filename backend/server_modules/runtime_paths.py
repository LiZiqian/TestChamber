"""Runtime data-root path management for TestChamber V7.

This module intentionally contains no business logic. It owns the physical
boundary between frontend, backend, and runtime data so backend/server.py can stay
focused on HTTP/API orchestration while data-root rules remain testable.
"""

from __future__ import annotations

import filecmp
import json
import os
import shutil
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path


DATA_ROOT_ENV_VAR = "TESTCHAMBER_DATA_DIR"
DATA_ROOT_MARKER_FILE = "platform-data.json"
DATA_ROOT_SCHEMA = "testchamber-data-root-v1"


@dataclass(frozen=True)
class RuntimePaths:
    data_dir: Path
    sample_data_dir: Path
    import_preview_dir: Path
    export_dir: Path
    db_path: Path
    deployment_file: Path


@dataclass(frozen=True)
class DataRootMigrationReport:
    data_dir: Path
    migrated: bool
    legacy_data_dir: Path
    copied_files: int
    copied_dirs: int
    skipped: str = ""
    copied_bytes: int = 0
    verified_files: int = 0


@dataclass(frozen=True)
class CopyTreeReport:
    copied_files: int = 0
    copied_dirs: int = 0
    copied_bytes: int = 0
    verified_files: int = 0


def now_iso() -> str:
    return datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds")


def default_data_dir(platform_root: Path) -> Path:
    platform_root = Path(platform_root).resolve()
    return platform_root / "data"


def previous_external_data_dir(platform_root: Path) -> Path:
    platform_root = Path(platform_root).resolve()
    return platform_root.with_name(f"{platform_root.name}_data")


def path_is_inside(child: Path, parent: Path) -> bool:
    child = Path(child).resolve()
    parent = Path(parent).resolve()
    return child == parent or parent in child.parents


def resolve_data_root(platform_root: Path, path_value: str | os.PathLike | None = None) -> Path:
    raw = path_value or os.environ.get(DATA_ROOT_ENV_VAR) or default_data_dir(platform_root)
    return Path(raw).expanduser().resolve()


def build_runtime_paths(data_root: Path) -> RuntimePaths:
    data_root = Path(data_root).expanduser().resolve()
    return RuntimePaths(
        data_dir=data_root,
        sample_data_dir=data_root / "samples",
        import_preview_dir=data_root / "import-previews",
        export_dir=data_root / "exports",
        db_path=data_root / "testchamber.sqlite",
        deployment_file=data_root / "deployment.json",
    )


def validate_project_data_root(data_root: Path, platform_root: Path) -> None:
    data_root = Path(data_root).resolve()
    platform_root = Path(platform_root).resolve()
    if not path_is_inside(data_root, platform_root):
        raise ValueError(
            f"数据目录必须位于项目目录内部: {data_root}。"
            f"请使用项目内路径，例如 {default_data_dir(platform_root)}。"
        )
    for reserved in ("frontend", "backend", ".git", ".claude"):
        reserved_path = platform_root / reserved
        if path_is_inside(data_root, reserved_path):
            raise ValueError(f"数据目录不能位于 {reserved}/ 内部: {data_root}。请使用 {default_data_dir(platform_root)}。")


def validate_external_data_root(data_root: Path, platform_root: Path) -> None:
    """Compatibility alias; data is now expected inside the project."""
    validate_project_data_root(data_root, platform_root)


def ensure_runtime_dirs(paths: RuntimePaths, *, platform_root: Path | None = None, migration: dict | None = None) -> None:
    paths.data_dir.mkdir(parents=True, exist_ok=True)
    paths.sample_data_dir.mkdir(parents=True, exist_ok=True)
    paths.import_preview_dir.mkdir(parents=True, exist_ok=True)
    paths.export_dir.mkdir(parents=True, exist_ok=True)
    marker_path = paths.data_dir / DATA_ROOT_MARKER_FILE
    if marker_path.is_file() and not migration:
        try:
            marker = json.loads(marker_path.read_text(encoding="utf-8"))
            platform_value = str(Path(platform_root).resolve()) if platform_root else ""
            if marker.get("schema") == DATA_ROOT_SCHEMA and marker.get("dataRoot") == str(paths.data_dir) and marker.get("platformRoot") == platform_value:
                return
        except Exception:
            pass
    marker = {
        "schema": DATA_ROOT_SCHEMA,
        "createdAt": now_iso(),
        "dataRoot": str(paths.data_dir),
        "platformRoot": str(Path(platform_root).resolve()) if platform_root else "",
    }
    if migration:
        marker["migration"] = migration
    marker_path.write_text(json.dumps(marker, ensure_ascii=False, indent=2), encoding="utf-8")


def has_legacy_data(platform_root: Path) -> bool:
    platform_root = Path(platform_root).resolve()
    return previous_external_data_dir(platform_root).exists()


def data_root_has_business_data(paths: RuntimePaths) -> bool:
    if paths.db_path.exists() or paths.deployment_file.exists():
        return True
    if paths.sample_data_dir.exists() and any(paths.sample_data_dir.iterdir()):
        return True
    return False


def directory_is_empty(path: Path) -> bool:
    return not path.exists() or not any(path.iterdir())


def directory_is_runtime_shell(path: Path) -> bool:
    if not path.exists():
        return True
    allowed_empty_dirs = {"samples", "import-previews", "exports"}
    for item in path.iterdir():
        if item.name == DATA_ROOT_MARKER_FILE and item.is_file():
            continue
        if item.name in allowed_empty_dirs and item.is_dir() and directory_is_empty(item):
            continue
        return False
    return True


def _copy_file_without_loss(src: Path, dst: Path) -> tuple[bool, Path]:
    if dst.exists():
        if dst.is_file() and filecmp.cmp(src, dst, shallow=False):
            return False, dst
        conflict = dst.with_name(f"{dst.stem}.legacy-conflict-{uuid.uuid4().hex[:8]}{dst.suffix}")
        shutil.copy2(src, conflict)
        return True, conflict
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(src, dst)
    return True, dst


def copy_tree_without_loss(src: Path, dst: Path) -> tuple[int, int]:
    report = copy_tree_without_loss_detailed(src, dst)
    return report.copied_files, report.copied_dirs


def copy_tree_without_loss_detailed(src: Path, dst: Path, *, ignored_dir_names: set[str] | None = None) -> CopyTreeReport:
    if not src.exists():
        return CopyTreeReport()
    ignored = ignored_dir_names or set()
    copied_files = 0
    copied_dirs = 0
    copied_bytes = 0
    verified_files = 0
    for item in src.rglob("*"):
        rel = item.relative_to(src)
        if any(part in ignored for part in rel.parts):
            continue
        target = dst / rel
        if item.is_dir():
            target.mkdir(parents=True, exist_ok=True)
            copied_dirs += 1
        elif item.is_file():
            copied, copied_to = _copy_file_without_loss(item, target)
            if not copied_to.is_file() or not filecmp.cmp(item, copied_to, shallow=False):
                raise RuntimeError(f"迁移复制校验失败: {item} -> {copied_to}")
            copied_bytes += item.stat().st_size
            verified_files += 1
            if copied:
                copied_files += 1
    return CopyTreeReport(copied_files, copied_dirs, copied_bytes, verified_files)


def prepare_runtime_paths(
    platform_root: Path,
    data_root: str | os.PathLike | None = None,
    *,
    migrate_legacy: bool = True,
) -> tuple[RuntimePaths, DataRootMigrationReport]:
    platform_root = Path(platform_root).resolve()
    target_root = resolve_data_root(platform_root, data_root)
    validate_project_data_root(target_root, platform_root)
    paths = build_runtime_paths(target_root)
    legacy_data_dir = previous_external_data_dir(platform_root)

    if not migrate_legacy or not has_legacy_data(platform_root):
        ensure_runtime_dirs(paths, platform_root=platform_root)
        return paths, DataRootMigrationReport(paths.data_dir, False, legacy_data_dir, 0, 0)

    if data_root_has_business_data(paths):
        ensure_runtime_dirs(paths, platform_root=platform_root)
        return paths, DataRootMigrationReport(
            paths.data_dir,
            False,
            legacy_data_dir,
            0,
            0,
            skipped="target_already_has_data",
        )

    staging = paths.data_dir.parent / f".{paths.data_dir.name}.migration-{uuid.uuid4().hex[:10]}"
    if staging.exists():
        shutil.rmtree(staging)
    staging_paths = build_runtime_paths(staging)
    copied_files = 0
    copied_dirs = 0
    copied_bytes = 0
    verified_files = 0
    try:
        staging.mkdir(parents=True, exist_ok=True)
        report = copy_tree_without_loss_detailed(legacy_data_dir, staging, ignored_dir_names={"backups"})
        copied_files += report.copied_files
        copied_dirs += report.copied_dirs
        copied_bytes += report.copied_bytes
        verified_files += report.verified_files
        migration_info = {
            "migratedAt": now_iso(),
            "legacyDataDir": str(legacy_data_dir),
            "copiedFiles": copied_files,
            "copiedDirs": copied_dirs,
            "copiedBytes": copied_bytes,
            "verifiedFiles": verified_files,
            "mode": "copy-then-promote",
        }
        ensure_runtime_dirs(
            staging_paths,
            platform_root=platform_root,
            migration=migration_info,
        )
        if paths.data_dir.exists():
            if not directory_is_empty(paths.data_dir) and not directory_is_runtime_shell(paths.data_dir):
                raise RuntimeError(f"目标数据目录在迁移期间出现数据，已停止迁移: {paths.data_dir}")
            shutil.rmtree(paths.data_dir)
        shutil.move(str(staging), str(paths.data_dir))
        ensure_runtime_dirs(paths, platform_root=platform_root, migration=migration_info)
    except Exception:
        shutil.rmtree(staging, ignore_errors=True)
        raise

    return paths, DataRootMigrationReport(
        paths.data_dir,
        True,
        legacy_data_dir,
        copied_files,
        copied_dirs,
        copied_bytes=copied_bytes,
        verified_files=verified_files,
    )
