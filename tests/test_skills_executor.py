"""D5: skills are data with deterministic executors, and list_skills is gone."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from nanoloop import skills, tools

SKILLS_ROOT = Path(__file__).resolve().parent.parent / "Skills"


@pytest.fixture(autouse=True)
def _real_skills(monkeypatch):
    monkeypatch.setattr(skills, "SKILLS_DIR", SKILLS_ROOT)


def test_list_skills_tool_no_longer_exists():
    """PLAN.md D5 corollary: the catalog is already in the prompt; the tool was
    a wasted slot and a wasted round trip. Do not re-add it."""
    assert not hasattr(tools, "list_skills")
    assert "list_skills" not in [t.name for t in tools.HARNESS_TOOLS]


def test_use_skill_is_still_bound():
    assert "use_skill" in [t.name for t in tools.HARNESS_TOOLS]


def test_three_skills_ship():
    names = {s.name for s in skills.discover()}
    assert {"scaffold-fastapi", "add-endpoint", "setup-pytest"} <= names


def test_catalog_is_one_line_per_skill():
    lines = skills.catalog_text().splitlines()
    assert len(lines) == len(skills.discover())
    assert all(ln.startswith("- ") for ln in lines)


def test_catalog_cost_stays_near_23_tokens_per_skill():
    """Phase 5 acceptance: a 4th skill must cost <30 tokens of catalog."""
    text = skills.catalog_text()
    approx_tokens = len(text) / 4  # ~4 chars/token
    assert approx_tokens / len(skills.discover()) < 30


def test_every_skill_has_examples_for_routing():
    """Skill-selection ambiguity is the same 21x failure mode as tool ambiguity;
    ## Examples are the routing anchors that keep descriptions apart."""
    for s in skills.discover():
        assert "## Examples" in s.body, f"{s.name} has no ## Examples section"


def test_skills_have_executors():
    for s in skills.discover():
        assert s.has_executor, f"{s.name} ships no deterministic executor"


# --- the executors actually run ---------------------------------------------


def test_scaffold_fastapi_writes_a_working_tree(tmp_path):
    out = skills.execute(skills.get("scaffold-fastapi"), {"title": "demo"}, tmp_path)
    assert (tmp_path / "app" / "main.py").exists()
    assert (tmp_path / "tests" / "test_health.py").exists()
    assert (tmp_path / "requirements.txt").exists()
    assert "demo" in (tmp_path / "app" / "main.py").read_text()
    assert "scaffolded" in out


def test_add_endpoint_appends_and_does_not_rewrite(tmp_path):
    skills.execute(skills.get("scaffold-fastapi"), {}, tmp_path)
    before = (tmp_path / "app" / "main.py").read_text()
    skills.execute(skills.get("add-endpoint"), {"path": "/items"}, tmp_path)
    after = (tmp_path / "app" / "main.py").read_text()
    assert after.startswith(before.rstrip("\n"))  # appended, never regenerated
    assert '@app.get("/items")' in after
    assert (tmp_path / "tests" / "test_get_items.py").exists()


def test_add_endpoint_is_idempotent(tmp_path):
    skills.execute(skills.get("scaffold-fastapi"), {}, tmp_path)
    skills.execute(skills.get("add-endpoint"), {"path": "/items"}, tmp_path)
    out = skills.execute(skills.get("add-endpoint"), {"path": "/items"}, tmp_path)
    assert "no-op" in out


def test_add_endpoint_fails_loudly_without_an_app(tmp_path):
    with pytest.raises(FileNotFoundError, match="scaffold-fastapi"):
        skills.execute(skills.get("add-endpoint"), {"path": "/x"}, tmp_path)


def test_add_endpoint_rejects_a_bad_method(tmp_path):
    skills.execute(skills.get("scaffold-fastapi"), {}, tmp_path)
    with pytest.raises(ValueError, match="method must be"):
        skills.execute(skills.get("add-endpoint"), {"path": "/x", "method": "fetch"}, tmp_path)


def test_setup_pytest_is_idempotent(tmp_path):
    skills.execute(skills.get("setup-pytest"), {}, tmp_path)
    first = (tmp_path / "pyproject.toml").read_text()
    skills.execute(skills.get("setup-pytest"), {}, tmp_path)
    assert (tmp_path / "pyproject.toml").read_text() == first
    assert (tmp_path / "tests" / "conftest.py").exists()


# --- the tool wrapper --------------------------------------------------------


def test_use_skill_tool_parses_json_data(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    out = tools.use_skill.invoke({"name": "scaffold-fastapi", "data": json.dumps({"title": "svc"})})
    assert "scaffolded" in out
    assert (tmp_path / "app" / "main.py").exists()


def test_use_skill_reports_a_missing_skill():
    out = tools.use_skill.invoke({"name": "nope", "data": ""})
    assert "[no skill 'nope']" in out


def test_use_skill_surfaces_executor_errors(tmp_path, monkeypatch):
    monkeypatch.setattr(tools, "WORKDIR", tmp_path)
    out = tools.use_skill.invoke({"name": "add-endpoint", "data": "{}"})
    assert "failed" in out and "path" in out


# --- executors must emit gate-clean code ------------------------------------


@pytest.mark.parametrize(
    ("name", "params"),
    [
        ("scaffold-fastapi", {"title": "svc"}),
        ("setup-pytest", {}),
    ],
)
def test_executor_output_passes_the_default_gates(tmp_path, name, params):
    """A skill whose output fails `ruff format --check` makes EVERY skill step
    fail — found when the first scaffold-from-scratch run died on a missing
    blank line after a module docstring. The model was never involved."""
    import subprocess
    import sys

    skills.execute(skills.get(name), params, tmp_path)
    ruff = str(Path(sys.executable).parent / "ruff")
    for cmd in ([ruff, "check", "."], [ruff, "format", "--check", "."]):
        proc = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
        assert proc.returncode == 0, f"{' '.join(cmd)}:\n{proc.stdout}{proc.stderr}"


def test_add_endpoint_output_passes_the_gates(tmp_path):
    import subprocess
    import sys

    skills.execute(skills.get("scaffold-fastapi"), {}, tmp_path)
    skills.execute(skills.get("add-endpoint"), {"path": "/items"}, tmp_path)
    ruff = str(Path(sys.executable).parent / "ruff")
    for cmd in ([ruff, "check", "."], [ruff, "format", "--check", "."]):
        proc = subprocess.run(cmd, cwd=tmp_path, capture_output=True, text=True)
        assert proc.returncode == 0, f"{' '.join(cmd)}:\n{proc.stdout}{proc.stderr}"


def test_py_literal_emits_python_not_json(tmp_path):
    """json.dumps gives `true`; repr gives single quotes. Both fail a gate."""
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        "add_ep", SKILLS_ROOT / "add-endpoint" / "execute.py"
    )
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    assert mod._py_literal({"ok": True}) == '{"ok": True}'
    assert mod._py_literal({"a": None, "b": [1, "x"]}) == '{"a": None, "b": [1, "x"]}'
    assert eval(mod._py_literal({"ok": False})) == {"ok": False}  # noqa: S307
