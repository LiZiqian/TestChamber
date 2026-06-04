#!/usr/bin/env python3
"""Migrate legacy TestChamber runtime data into an external data root.

This is the operator-facing wrapper around server_modules.runtime_paths. The
server also runs the same copy-then-promote migration on startup by default.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from server_modules import runtime_paths  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="Migrate TestChamber data/backups to an external data root")
    parser.add_argument("--platform-root", default=str(ROOT), help="Platform source directory, default: repository root")
    parser.add_argument("--data-dir", default=None, help="External target data directory")
    parser.add_argument("--no-migrate", action="store_true", help="Only create/check target runtime directories")
    args = parser.parse_args()

    platform_root = Path(args.platform_root).expanduser().resolve()
    try:
        paths, report = runtime_paths.prepare_runtime_paths(
            platform_root,
            args.data_dir,
            migrate_legacy=not args.no_migrate,
        )
    except Exception as exc:
        print(f"[ERROR] {exc}", file=sys.stderr)
        return 2

    print(f"platform_root={platform_root}")
    print(f"data_dir={paths.data_dir}")
    print(f"db_path={paths.db_path}")
    print(f"samples_dir={paths.sample_data_dir}")
    print(f"backups_dir={paths.backup_dir}")
    print(f"import_previews_dir={paths.import_preview_dir}")
    print(f"exports_dir={paths.export_dir}")
    if report.migrated:
        print(
            "migrated=true "
            f"copied_files={report.copied_files} "
            f"copied_dirs={report.copied_dirs} "
            f"copied_bytes={report.copied_bytes} "
            f"verified_files={report.verified_files}"
        )
    elif report.skipped:
        print(f"migrated=false skipped={report.skipped}")
    else:
        print("migrated=false")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
