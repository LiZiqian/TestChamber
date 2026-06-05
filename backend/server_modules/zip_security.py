"""Safe ZIP extraction for import packages."""

from __future__ import annotations

import re
import zipfile
from pathlib import Path


MAX_FILE_BYTES = 100 * 1024 * 1024
MAX_TOTAL_BYTES = 500 * 1024 * 1024
ALLOWED_PREFIXES = (
    "manifest.json",
    "state.json",
    "checksums.json",
    "dossier.json",
    "sample/",
    "domains/",
    "assets/index.json",
    "assets/samples/",
)
DANGEROUS_RE = re.compile(
    r"(^|[/\\])\.\.[/\\]"
    r"|^[/\\]"
    r"|^[A-Za-z]:[/\\]"
)


def safe_extract_zip(zf: zipfile.ZipFile, dest_dir: str | Path) -> None:
    dest = Path(dest_dir).resolve()
    total_bytes = 0

    for entry in zf.infolist():
        name = entry.filename
        normalized = name.replace("\\", "/")

        if DANGEROUS_RE.search(normalized):
            raise ValueError(f"ZIP 包含不安全路径: {name}")

        mode = (entry.external_attr >> 16) & 0o170000
        if mode == 0o120000:
            raise ValueError(f"ZIP 包含符号链接，拒绝: {name}")

        allowed = any(name == prefix or name.startswith(prefix) for prefix in ALLOWED_PREFIXES)
        if not allowed:
            raise ValueError(f"ZIP 包含不允许的文件: {name}")

        target = (dest / normalized).resolve()
        try:
            target.relative_to(dest)
        except ValueError:
            raise ValueError(f"ZIP 路径越界: {name}")

        file_size = entry.file_size
        if file_size > MAX_FILE_BYTES:
            raise ValueError(f"ZIP 文件过大 ({file_size} bytes): {name}")
        total_bytes += file_size
        if total_bytes > MAX_TOTAL_BYTES:
            raise ValueError(f"ZIP 总解压大小超过 {MAX_TOTAL_BYTES} bytes")

        if entry.is_dir():
            target.mkdir(parents=True, exist_ok=True)
        else:
            target.parent.mkdir(parents=True, exist_ok=True)
            with zf.open(entry) as src, open(target, "wb") as dst:
                while True:
                    chunk = src.read(8192)
                    if not chunk:
                        break
                    dst.write(chunk)
