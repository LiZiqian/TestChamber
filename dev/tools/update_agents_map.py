#!/usr/bin/env python3
"""Refresh function line references in AGENTS.md from current source files."""

from __future__ import annotations

import re
import argparse
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
AGENTS_PATH = ROOT / "AGENTS.md"


PY_DEF_RE = re.compile(r"^(?P<indent>\s*)(?:async\s+)?def\s+(?P<name>[A-Za-z_]\w*)\s*\(")
PY_CLASS_RE = re.compile(r"^(?P<indent>\s*)class\s+(?P<name>[A-Za-z_]\w*)\b")
JS_FUNCTION_RE = re.compile(r"^\s*(?:async\s+)?function\s+(?P<name>[A-Za-z_$][\w$]*)\s*\(")
JS_METHOD_RE = re.compile(r"^\s*(?:async\s+)?(?P<name>[A-Za-z_$][\w$]*)\s*\([^)]*\)\s*\{")
JS_CONST_RE = re.compile(r"^\s*(?:const|let|var)\s+(?P<name>[A-Za-z_$][\w$]*)\b")


def rel(path: Path) -> str:
    return path.relative_to(ROOT).as_posix()


def scan_python(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    class_stack: list[tuple[int, str]] = []
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        class_match = PY_CLASS_RE.match(line)
        def_match = PY_DEF_RE.match(line)
        indent = len(line) - len(line.lstrip(" "))
        class_stack = [(level, name) for level, name in class_stack if level < indent]
        if class_match:
            name = class_match.group("name")
            symbols[name] = line_no
            class_stack.append((indent, name))
            continue
        if def_match:
            name = def_match.group("name")
            symbols[name] = line_no
            if class_stack:
                symbols[f"{class_stack[-1][1]}.{name}"] = line_no
            else:
                symbols[name] = line_no
    return symbols


def scan_js(path: Path) -> dict[str, int]:
    symbols: dict[str, int] = {}
    for line_no, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
        for pattern in (JS_FUNCTION_RE, JS_METHOD_RE, JS_CONST_RE):
            match = pattern.match(line)
            if match:
                name = match.group("name")
                if name not in {"if", "for", "while", "switch", "catch"}:
                    symbols.setdefault(name, line_no)
                break
    return symbols


def build_index() -> dict[str, dict[str, int]]:
    index: dict[str, dict[str, int]] = {}
    for path in ROOT.rglob("*"):
        if not path.is_file() or any(part in {".git", "__pycache__", "data"} for part in path.parts):
            continue
        if path.suffix == ".py":
            index[rel(path)] = scan_python(path)
        elif path.suffix == ".js":
            index[rel(path)] = scan_js(path)
    return index


def update_inline_file_refs(text: str, index: dict[str, dict[str, int]]) -> str:
    pattern = re.compile(
        r"`(?P<file>[^`:\n]+\.(?:py|js)):(?P<line>\d+)`\s+"
        r"`(?P<symbol>[A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)(?:\(\))?`"
    )

    def repl(match: re.Match[str]) -> str:
        file_name = match.group("file")
        symbol = match.group("symbol")
        line_no = index.get(file_name, {}).get(symbol)
        if not line_no:
            return match.group(0)
        suffix = "()" if match.group(0).rstrip("`").endswith("()") else ""
        return f"`{file_name}:{line_no}` `{symbol}{suffix}`"

    return pattern.sub(repl, text)


def update_heading_counts(text: str) -> str:
    server_lines = len((ROOT / "backend" / "server.py").read_text(encoding="utf-8").splitlines())
    text = re.sub(r"`(?:backend/)?server\.py` 约 [\d,]+ 行", f"`backend/server.py` 约 {server_lines:,} 行", text)
    text = re.sub(r"### (?:backend/)?server\.py \(\d+ 行", f"### backend/server.py ({server_lines} 行", text)
    return text


def normalize_project_paths(text: str) -> str:
    replacements = (
        ("`server_modules/", "`backend/server_modules/"),
        ("`js/", "`frontend/js/"),
        ("`css/", "`frontend/css/"),
        ("`index.html`", "`frontend/index.html`"),
        ("### js/", "### frontend/js/"),
        ("### css/", "### frontend/css/"),
    )
    for old, new in replacements:
        text = text.replace(old, new)
    text = re.sub(r"`server\.py:(\d+)`", r"`backend/server.py:\1`", text)
    return text


def update_table_rows(text: str, index: dict[str, dict[str, int]]) -> str:
    current_file = ""
    output: list[str] = []
    for line in text.splitlines():
        heading = re.match(r"^###\s+([^(\s]+)", line)
        if heading:
            candidate = heading.group(1).strip()
            current_file = candidate if candidate in index else ""
            output.append(line)
            continue
        if current_file and line.startswith("|") and "`" in line:
            cells = line.split("|")
            if len(cells) >= 4:
                symbols = [
                    item.replace("()", "")
                    for item in re.findall(r"`([A-Za-z_$][\w$]*(?:\.[A-Za-z_$][\w$]*)?)(?:\(\))?`", cells[2])
                ]
                lines = [index[current_file].get(symbol) for symbol in symbols]
                if symbols and all(lines):
                    cells[1] = " " + " / ".join(str(item) for item in lines) + " "
                    line = "|".join(cells)
        output.append(line)
    return "\n".join(output) + "\n"


def refresh_agents_text(text: str, index: dict[str, dict[str, int]]) -> str:
    text = normalize_project_paths(text)
    text = update_heading_counts(text)
    text = update_inline_file_refs(text, index)
    text = update_table_rows(text, index)
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Refresh or check AGENTS.md function line references.")
    parser.add_argument("--check", action="store_true", help="fail without writing when AGENTS.md references are stale")
    args = parser.parse_args(argv)

    index = build_index()
    text = AGENTS_PATH.read_text(encoding="utf-8")
    refreshed = refresh_agents_text(text, index)
    if args.check:
        if refreshed != text:
            print("AGENTS.md file map is stale; run: python dev\\tools\\update_agents_map.py")
            return 1
        return 0
    AGENTS_PATH.write_text(refreshed, encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
