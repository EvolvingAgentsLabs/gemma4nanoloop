"""Repo map: file tree + first docstring per file. Never file contents.

PLAN.md §4 Phase 1 is specific about this. The plan phase gets 16384 tokens of
budget and must fit "with room to spare"; dumping contents blows that instantly
and teaches the model to reason about code it will not be editing this step.
"""

from __future__ import annotations

import ast
from pathlib import Path

SKIP_DIRS = {
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "node_modules",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "dist",
    "build",
    ".eggs",
}
CODE_SUFFIXES = {".py", ".toml", ".md", ".cfg", ".yaml", ".yml", ".json", ".txt", ".sh"}


def _first_docstring(path: Path) -> str:
    """Module docstring for .py; first heading/line otherwise. One line, bounded."""
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    if path.suffix == ".py":
        try:
            doc = ast.get_docstring(ast.parse(text)) or ""
        except SyntaxError:
            doc = ""
    else:
        doc = next((ln for ln in text.splitlines() if ln.strip()), "")
    doc = " ".join(doc.split())
    return doc[:120]


def build(root: Path | str, *, max_files: int = 300) -> str:
    """Render the map. Sorted for stability — a map that reorders between calls
    defeats prefix caching and makes two runs incomparable."""
    root = Path(root)
    rows: list[str] = []
    for p in sorted(root.rglob("*")):
        if len(rows) >= max_files:
            rows.append("[...truncated: repo larger than max_files...]")
            break
        if not p.is_file() or p.suffix not in CODE_SUFFIXES:
            continue
        if any(part in SKIP_DIRS for part in p.parts):
            continue
        rel = p.relative_to(root)
        doc = _first_docstring(p)
        rows.append(f"{rel}" + (f"  — {doc}" if doc else ""))
    return "\n".join(rows) if rows else "[empty repo]"
