"""G7: refuse to start in a repo that is already broken.

The repair loop cannot tell "my edit was wrong" from "this repo was already
red" — both arrive as identical gate output. A missing `ruff` on PATH once cost
a whole run: 4 model calls, every anchor exact, every attempt doomed.
"""

from __future__ import annotations

from nanoloop import crew


def test_green_repo_passes(tmp_path):
    (tmp_path / "m.py").write_text("X = 1\n")
    pf = crew.preflight(tmp_path, ["true"])
    assert pf.ok and not pf.skipped
    assert "starts green" in pf.report()


def test_red_repo_is_refused(tmp_path):
    (tmp_path / "m.py").write_text("X = 1\n")
    pf = crew.preflight(tmp_path, ["false"])
    assert not pf.ok
    assert "does not pass its own gates" in pf.reason
    assert pf.failures and pf.failures[0].command == "false"


def test_empty_workspace_is_skipped_not_failed(tmp_path):
    """Scaffolding from nothing is a legitimate goal, and pytest rightly fails
    when there are no tests yet — the FastAPI demo starts exactly here."""
    pf = crew.preflight(tmp_path, ["false"])
    assert pf.ok and pf.skipped
    assert "scaffolding" in pf.reason


def test_workspace_with_only_non_python_is_skipped(tmp_path):
    (tmp_path / "README.md").write_text("# hi\n")
    assert crew.preflight(tmp_path, ["false"]).skipped


def test_venv_contents_do_not_count_as_project_code(tmp_path):
    (tmp_path / ".venv").mkdir()
    (tmp_path / ".venv" / "lib.py").write_text("X = 1\n")
    assert crew.preflight(tmp_path, ["false"]).skipped


def test_missing_tooling_is_named_specifically(tmp_path):
    """A missing tool needs a different message from a failing test: one is a
    setup problem, the other is the repo's own state."""
    (tmp_path / "m.py").write_text("X = 1\n")
    pf = crew.preflight(tmp_path, ["definitely-not-a-real-tool-xyz check ."])
    assert not pf.ok
    assert "not on PATH" in pf.reason
    assert "definitely-not-a-real-tool-xyz" in pf.reason


def test_report_includes_the_failing_output(tmp_path):
    (tmp_path / "m.py").write_text("X = 1\n")
    pf = crew.preflight(tmp_path, ["echo boom && false"])
    assert "boom" in pf.report()


def test_real_gates_pass_on_the_fixture_repo():
    """The eval fixture must stay startable, or every eval run is measuring the
    wrong thing."""
    assert crew.preflight("eval/fixture-repo").ok
