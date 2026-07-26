"""Deterministic executor for scaffold-fastapi.

run(params, workspace) -> str

Templates, not prose. The model chooses to invoke this and supplies parameters;
the bytes that land on disk are fixed.
"""

from __future__ import annotations

from pathlib import Path

MAIN = '''"""{title} — FastAPI service."""
from fastapi import FastAPI

app = FastAPI(title="{title}")


@app.get("/health")
def health() -> dict[str, str]:
    return {{"status": "ok"}}
'''

TEST = '''"""Health-route test for {title}."""
from fastapi.testclient import TestClient

from {app_dir}.main import app

client = TestClient(app)


def test_health_ok():
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {{"status": "ok"}}
'''

REQUIREMENTS = "fastapi>=0.110\nuvicorn[standard]>=0.29\nhttpx>=0.27\n"


def run(params: dict, workspace: Path) -> str:
    app_dir = str(params.get("app_dir", "app")).strip("/") or "app"
    title = str(params.get("title", "service"))

    pkg = workspace / app_dir
    pkg.mkdir(parents=True, exist_ok=True)
    (pkg / "__init__.py").write_text("", encoding="utf-8")
    (pkg / "main.py").write_text(MAIN.format(title=title), encoding="utf-8")

    tests = workspace / "tests"
    tests.mkdir(parents=True, exist_ok=True)
    (tests / "test_health.py").write_text(
        TEST.format(title=title, app_dir=app_dir), encoding="utf-8"
    )

    (workspace / "requirements.txt").write_text(REQUIREMENTS, encoding="utf-8")

    return (
        f"scaffolded FastAPI service '{title}': "
        f"{app_dir}/main.py, {app_dir}/__init__.py, tests/test_health.py, "
        f"requirements.txt"
    )
