"""Deterministic executor for setup-pytest.

Idempotent: safe to run twice, appends config sections only when absent.
"""

from __future__ import annotations

from pathlib import Path

CONFTEST = '''"""Put the repo root on sys.path so tests import the package under test."""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
'''


def run(params: dict, workspace: Path) -> str:
    testpaths = str(params.get("testpaths", "tests"))
    line_length = int(params.get("line_length", 100))

    tests = workspace / testpaths
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "__init__.py").touch()
    (tests / "conftest.py").write_text(CONFTEST, encoding="utf-8")

    pyproject = workspace / "pyproject.toml"
    existing = pyproject.read_text(encoding="utf-8") if pyproject.exists() else ""
    added = []

    if "[tool.pytest.ini_options]" not in existing:
        existing = existing.rstrip("\n") + (
            f'\n\n[tool.pytest.ini_options]\ntestpaths = ["{testpaths}"]\n'
        )
        added.append("[tool.pytest.ini_options]")

    if "[tool.ruff]" not in existing:
        existing = existing.rstrip("\n") + (
            f"\n\n[tool.ruff]\nline-length = {line_length}\n\n"
            f'[tool.ruff.lint]\nselect = ["E", "F", "I", "UP", "B"]\n'
        )
        added.append("[tool.ruff]")

    pyproject.write_text(existing.lstrip("\n"), encoding="utf-8")

    what = ", ".join(added) if added else "no config changes needed"
    return f"pytest/ruff configured ({what}); {testpaths}/__init__.py and conftest.py written"
