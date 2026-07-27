"""Deterministic executor for add-endpoint.

Appends one route to an existing FastAPI app and writes a matching test.
Appending, never rewriting — see PLAN.md D4.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

METHODS = {"get", "post", "put", "delete", "patch"}


def _py_literal(obj) -> str:
    """Render a value as PYTHON source that ruff format will not touch.

    Neither obvious option works on its own:
      json.dumps({"ok": True}) -> {"ok": true}   valid JSON, NameError in Python
      repr({"ok": True})       -> {'ok': True}   valid Python, wrong quote style

    The second one is not merely cosmetic here: `ruff format --check` is a
    DEFAULT GATE, so single quotes make every generated endpoint fail the gate
    and take the whole step down with it.
    """
    if isinstance(obj, bool):
        return "True" if obj else "False"
    if obj is None:
        return "None"
    if isinstance(obj, str):
        return json.dumps(obj)  # double-quoted and properly escaped
    if isinstance(obj, int | float):
        return repr(obj)
    if isinstance(obj, dict):
        return "{" + ", ".join(f"{_py_literal(k)}: {_py_literal(v)}" for k, v in obj.items()) + "}"
    if isinstance(obj, list | tuple):
        return "[" + ", ".join(_py_literal(v) for v in obj) + "]"
    return json.dumps(str(obj))


def _fn_name(path: str, method: str) -> str:
    slug = re.sub(r"[^a-zA-Z0-9]+", "_", path).strip("_") or "root"
    return f"{method}_{slug}"


def run(params: dict, workspace: Path) -> str:
    route = str(params.get("path", "")).strip()
    if not route:
        raise ValueError("add-endpoint requires a 'path' parameter, e.g. '/items'")
    if not route.startswith("/"):
        route = "/" + route

    method = str(params.get("method", "get")).lower().strip()
    if method not in METHODS:
        raise ValueError(f"method must be one of {sorted(METHODS)}, got '{method}'")

    app_file = workspace / str(params.get("app_file", "app/main.py"))
    if not app_file.exists():
        raise FileNotFoundError(
            f"{app_file.relative_to(workspace)} does not exist — "
            f"run the scaffold-fastapi skill first"
        )

    fn = str(params.get("name") or _fn_name(route, method))
    returns = params.get("returns", {"ok": True})
    if isinstance(returns, str):
        try:
            returns = json.loads(returns)
        except json.JSONDecodeError:
            pass
    literal = _py_literal(returns)

    source = app_file.read_text(encoding="utf-8")
    if f'@app.{method}("{route}")' in source:
        return f"[no-op] {method.upper()} {route} already exists in {app_file.name}"

    # THREE newlines: rstrip leaves none, and ruff format requires two blank
    # lines between top-level definitions.
    block = f'\n\n\n@app.{method}("{route}")\ndef {fn}():\n    return {literal}\n'
    app_file.write_text(source.rstrip("\n") + block, encoding="utf-8")

    module = str(params.get("app_file", "app/main.py"))[:-3].replace("/", ".")
    tests = workspace / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    test_file = tests / f"test_{fn}.py"
    test_file.write_text(
        f'"""Test for {method.upper()} {route}."""\n\n'
        f"from fastapi.testclient import TestClient\n\n"
        f"from {module} import app\n\n"
        f"client = TestClient(app)\n\n\n"
        f"def test_{fn}():\n"
        f'    resp = client.{method}("{route}")\n'
        f"    assert resp.status_code == 200\n"
        f"    assert resp.json() == {literal}\n",
        encoding="utf-8",
    )

    return f"added {method.upper()} {route} as {fn}() in {module}, test at tests/{test_file.name}"
