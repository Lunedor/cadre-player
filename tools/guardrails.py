#!/usr/bin/env python3
"""Lightweight local guardrails for refactor chunks.

Default checks:
- Parse key Python files with `ast.parse`.

Usage:
- python tools/guardrails.py
- python tools/guardrails.py --files player_window.py playlist.py
"""

from __future__ import annotations

import argparse
import ast
from pathlib import Path
import sys


DEFAULT_FILES = [
    "player_window.py",
    "playlist.py",
    "ui/events.py",
    "logic.py",
    "main.py",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run lightweight syntax guardrails.")
    parser.add_argument(
        "--files",
        nargs="*",
        default=DEFAULT_FILES,
        help="Paths to Python files to validate (defaults to project key files).",
    )
    return parser.parse_args()


def check_syntax(path: Path) -> tuple[bool, str]:
    if not path.exists():
        return False, "missing"
    if not path.is_file():
        return False, "not a file"
    try:
        # Accept UTF-8 files with or without BOM to keep local checks stable.
        source = path.read_text(encoding="utf-8-sig")
    except UnicodeDecodeError:
        source = path.read_text(encoding="utf-8", errors="replace")
    try:
        ast.parse(source, filename=str(path))
        return True, "ok"
    except SyntaxError as exc:
        location = f"{exc.lineno}:{exc.offset}" if exc.lineno else "unknown"
        return False, f"syntax error at {location}: {exc.msg}"


def main() -> int:
    args = parse_args()
    root = Path(__file__).resolve().parent.parent
    files = [root / f for f in args.files]

    print("Guardrails: syntax parse")
    print(f"Root: {root}")

    failures = 0
    for file_path in files:
        ok, detail = check_syntax(file_path)
        rel = file_path.relative_to(root)
        prefix = "PASS" if ok else "FAIL"
        print(f"[{prefix}] {rel} - {detail}")
        if not ok:
            failures += 1

    if failures:
        print(f"Result: FAILED ({failures} file(s))")
        return 1
    print("Result: PASSED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

