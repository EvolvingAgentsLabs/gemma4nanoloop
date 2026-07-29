"""Session: the goal, the task log, and the audit trail of human decisions.

Resume is NOT tested here because it does not exist. `load()`, `list_all()`,
`context_brief()` and the transcript were removed along with the tests that
covered them — they were fork inheritance for a resume path nothing ever built
(GAPS.md G8), and a green test over an API no caller uses is the most
comfortable kind of dead code: it looks like coverage.
"""

from __future__ import annotations

import json

import nanoloop.session as session_mod
from nanoloop.session import Session


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "SESSIONS_DIR", tmp_path / "sessions")


def test_create_persists(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Session.create("ship a thing")
    assert s.path.exists()
    assert len(s.id) == 8
    assert json.loads(s.path.read_text())["goal"] == "ship a thing"


def test_upsert_task_dedupes_by_title(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Session.create("g")
    s.upsert_task("plan", "active")
    s.upsert_task("plan", "done", "ok")
    assert len(s.tasks) == 1
    assert s.tasks[0].status == "done"
    assert s.tasks[0].note == "ok"


def test_decisions_are_recorded_and_persisted(tmp_path, monkeypatch):
    """The one thing the crew actually writes here: the human gates in
    `tools.human_review`, so an unattended run still leaves an audit trail."""
    _isolate(tmp_path, monkeypatch)
    s = Session.create("build api")
    s.record_decision("pre-ship", "git push", "approved", "lgtm")

    on_disk = json.loads(s.path.read_text())["decisions"]
    assert len(on_disk) == 1
    assert on_disk[0]["gate"] == "pre-ship"
    assert on_disk[0]["verdict"] == "approved"
    assert on_disk[0]["action"] == "git push"


def test_an_auto_approval_is_recorded_too(tmp_path, monkeypatch):
    """Non-interactive runs auto-approve; the point of the trail is that it says
    so rather than silently omitting the gate."""
    _isolate(tmp_path, monkeypatch)
    s = Session.create("g")
    s.record_decision("plan-approval", "", "auto", "non-interactive")
    assert json.loads(s.path.read_text())["decisions"][0]["verdict"] == "auto"
