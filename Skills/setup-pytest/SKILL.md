---
name: setup-pytest
description: Configure pytest and ruff for a Python project so the quality gates can run.
---

Set up the test and lint configuration the crew's gates depend on.

Parameters:
  testpaths   directory holding tests (default "tests")
  line_length ruff line length         (default 100)

Writes/updates `pyproject.toml` with `[tool.pytest.ini_options]` and `[tool.ruff]`,
and creates `tests/__init__.py` plus a `tests/conftest.py` that puts the repo root
on `sys.path`.

Run this before relying on `python -m pytest -q` in a fresh repo. Gates that fail
because pytest is unconfigured produce error text the repair loop cannot act on —
it looks like a broken edit rather than a missing config.

## Examples

- "set up pytest for this project"
- "configure the test runner"
- "add ruff and pytest config"
- "tests aren't discovered / pytest can't import the package"

Do NOT use this to write an individual test — tests come with the skill that
creates the code they cover.
