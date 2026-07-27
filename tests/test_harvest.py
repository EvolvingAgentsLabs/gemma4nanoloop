"""Harvest: work read off the repo, with its oracle attached.

The point is that nobody writes the goal and nobody writes the criterion — a
failing test already contains both, and unlike a criterion the model invents,
it cannot be satisfied by a stub.
"""

from __future__ import annotations

from nanoloop import harvest


def _repo(tmp_path, *, broken=True):
    (tmp_path / "pkg").mkdir()
    (tmp_path / "pkg" / "__init__.py").write_text("")
    body = "    return 'TODO'\n" if broken else "    return a + b\n"
    (tmp_path / "pkg" / "calc.py").write_text(f"def add(a, b):\n{body}")
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests" / "test_calc.py").write_text(
        '"""T."""\n\nfrom pkg.calc import add\n\n\ndef test_add():\n    assert add(1, 2) == 3\n'
    )
    (tmp_path / "pyproject.toml").write_text(
        '[project]\nname = "t"\nversion = "0.1.0"\n\n[tool.pytest.ini_options]\ntestpaths = ["tests"]\n'
    )
    return tmp_path


def test_a_failing_test_becomes_a_task(tmp_path):
    tasks = harvest.from_pytest(_repo(tmp_path))
    assert len(tasks) == 1
    t = tasks[0]
    assert t.source == "pytest"
    assert "test_add" in t.goal
    assert t.acceptance and t.acceptance[0].check


def test_a_green_repo_yields_nothing(tmp_path):
    assert harvest.from_pytest(_repo(tmp_path, broken=False)) == []


def test_the_task_points_at_the_code_not_the_test(tmp_path):
    """Pointing the planner at the test invites it to edit the test until it
    passes — the one outcome that makes the exercise worthless."""
    t = harvest.from_pytest(_repo(tmp_path))[0]
    assert t.target_file == "pkg/calc.py"
    assert t.acceptance[0].file == "tests/test_calc.py"  # the oracle stays on the test


def test_the_goal_forbids_editing_the_test(tmp_path):
    assert "not the test itself" in harvest.from_pytest(_repo(tmp_path))[0].goal


def test_the_criterion_actually_runs_that_test(tmp_path):
    """A stub cannot satisfy it: the check shells out to pytest for that node."""
    from nanoloop import crew

    repo = _repo(tmp_path)
    t = harvest.from_pytest(repo)[0]
    assert crew.run_check(repo, t.acceptance[0].check, 0)  # currently failing
    (repo / "pkg" / "calc.py").write_text("def add(a, b):\n    return a + b\n")
    assert crew.run_check(repo, t.acceptance[0].check, 0) == ""  # now passing


def test_module_under_test_is_read_from_imports(tmp_path):
    repo = _repo(tmp_path)
    assert harvest.module_under_test(repo, "tests/test_calc.py") == "pkg/calc.py"


def test_module_under_test_falls_back_to_the_test_file(tmp_path):
    (tmp_path / "t.py").write_text("import os\n\n\ndef test_x():\n    assert os\n")
    assert harvest.module_under_test(tmp_path, "t.py") == "t.py"


def test_unknown_source_is_ignored(tmp_path):
    assert harvest.harvest(tmp_path, ["not-a-source"]) == []


def test_a_broken_source_does_not_kill_the_harvest(tmp_path, monkeypatch):
    monkeypatch.setitem(
        harvest.SOURCES, "pytest", lambda w: (_ for _ in ()).throw(RuntimeError("boom"))
    )
    harvest.harvest(_repo(tmp_path), ["pytest", "ruff"])  # must not raise


def test_tasks_serialise_to_json(tmp_path):
    import json

    tasks = harvest.from_pytest(_repo(tmp_path))
    rows = json.loads(harvest.dump(tasks))
    assert rows[0]["source"] == "pytest"
    assert rows[0]["acceptance"][0]["check"]
