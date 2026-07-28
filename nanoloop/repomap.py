"""Repo map: file tree + first docstring per file. Never file contents.

PLAN.md §4 Phase 1 is specific about this. The plan phase gets 16384 tokens of
budget and must fit "with room to spare"; dumping contents blows that instantly
and teaches the model to reason about code it will not be editing this step.
"""

from __future__ import annotations

import ast
import os
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
    # The crew's OWN artefacts. Found by pointing the crew at this repo: 57
    # session files under .nanoloop/ were 30% of the map's rows and ~664 tokens
    # of the 16,384-token plan budget, every one of them rendering as `— {`.
    # A planner reading the map to decide what to edit must never be shown the
    # runtime's bookkeeping — it is not part of the repo it is working on, and
    # it grows with every run.
    ".nanoloop",
    ".claude",
    ".vscode",
    ".idea",
}
CODE_SUFFIXES = {".py", ".toml", ".md", ".cfg", ".yaml", ".yml", ".json", ".txt", ".sh"}


def _summarize(path: Path, limit: int = 12) -> tuple[str, list[str]]:
    """Docstring and top-level symbol names, from ONE read and ONE parse.

    They used to be two functions each doing their own `read_text` +
    `ast.parse` of the same file. On a repo of any size the map is rebuilt every
    planning round, so that was twice the I/O and twice the parse for a result
    that never differs between the two calls.
    """
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return "", []

    if path.suffix != ".py":
        first = next((ln for ln in text.splitlines() if ln.strip()), "")
        first = " ".join(first.split())[:120]
        # A JSON or YAML file whose first line is `{` or `---` describes nothing.
        # Spending map budget on it is worse than leaving the row bare.
        return ("" if first.strip(" {[-\"'") == "" else first), []

    try:
        tree = ast.parse(text)
    except SyntaxError:
        # A file that does not parse still belongs on the map — it is often
        # exactly the file the goal is about.
        return "", []

    doc = " ".join((ast.get_docstring(tree) or "").split())[:120]
    names = [
        node.name
        for node in tree.body
        if isinstance(node, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if len(names) > limit:
        names = [*names[:limit], "..."]
    return doc, names


def _first_docstring(path: Path) -> str:
    """Module docstring for .py; first heading/line otherwise. One line, bounded."""
    return _summarize(path)[0]


def _symbols(path: Path, limit: int = 12) -> list[str]:
    """Top-level class and function names defined in a .py file.

    WHY THIS EXISTS. PLAN.md §4 Phase 1 specifies the map as "file tree + first
    docstring per file. Not file contents." That is too thin to ROUTE A SYMBOL
    TO A FILE. Observed on the first multi-step run: asked to add a field to
    `Item`, the planner targeted `todo/__init__.py` — a file containing one
    docstring and nothing else — because nothing in the map said `Item` lives in
    `todo/store.py`. Every downstream anchor then missed, unfixably, because the
    text being anchored to was not in that file.

    Names only, never bodies, so the map stays a map: ~5-15 tokens per file
    against the 16K plan budget.
    """
    return _summarize(path, limit)[1]


def _files(root: Path) -> list[Path]:
    """Every mappable file, without ever descending into a skipped directory.

    `rglob("*")` walked and SORTED the whole tree and only then dropped
    `SKIP_DIRS` — so a repo with a virtualenv paid for enumerating every file in
    `.venv` before discarding all of them, on every planning round. `os.walk`
    lets the skip list prune the traversal instead of filtering its output.
    """
    out: list[Path] = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = sorted(d for d in dirnames if d not in SKIP_DIRS)
        here = Path(dirpath)
        out.extend(here / name for name in filenames if Path(name).suffix in CODE_SUFFIXES)
    # Sorted for stability — a map that reorders between calls defeats prefix
    # caching and makes two runs incomparable.
    return sorted(out)


def build(root: Path | str, *, max_files: int = 300) -> str:
    """Render the map."""
    root = Path(root)
    rows: list[str] = []
    for p in _files(root):
        if len(rows) >= max_files:
            rows.append("[...truncated: repo larger than max_files...]")
            break
        doc, syms = _summarize(p)
        row = f"{p.relative_to(root)}" + (f"  — {doc}" if doc else "")
        if syms:
            row += f"\n    defines: {', '.join(syms)}"
        rows.append(row)
    return "\n".join(rows) if rows else "[empty repo]"
