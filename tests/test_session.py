"""Session memory: create, persist, task upsert, decisions, resume."""

from __future__ import annotations

import nanoloop.session as session_mod
from nanoloop.session import Session


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(session_mod, "SESSIONS_DIR", tmp_path / "sessions")


def test_create_persists(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Session.create("ship a thing")
    assert s.path.exists()
    assert len(s.id) == 8
    assert Session.load(s.id).goal == "ship a thing"


def test_upsert_task_dedupes_by_title(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Session.create("g")
    s.upsert_task("plan", "active")
    s.upsert_task("plan", "done", "ok")
    assert len(s.tasks) == 1
    assert s.tasks[0].status == "done"
    assert s.tasks[0].note == "ok"


def test_decisions_and_brief(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Session.create("build api")
    s.upsert_task("plan", "done")
    s.record_decision("pre-ship", "git push", "approved", "lgtm")
    brief = Session.load(s.id).context_brief()
    assert "build api" in brief
    assert "[done] plan" in brief
    assert "pre-ship" in brief


def test_transcript_bounded(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    s = Session.create("g")
    for i in range(250):
        s.log("builder", f"line {i}")
    assert len(s.transcript) == 200


def test_list_all_sorted_recent_first(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    a = Session.create("first")
    b = Session.create("second")
    b.upsert_task("x", "done")  # bumps b.updated
    ids = [s.id for s in Session.list_all()]
    assert ids[0] == b.id
    assert set(ids) == {a.id, b.id}
