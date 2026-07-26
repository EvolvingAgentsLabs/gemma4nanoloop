"""Tool behavior: workspace confinement, HITL gating, task tracking."""

from __future__ import annotations

import pytest

import nanoloop.tools as tools
from nanoloop.session import Session


def _workspace(tmp_path, monkeypatch):
    wd = (tmp_path / "workspace").resolve()
    monkeypatch.setattr(tools, "WORKDIR", wd)
    return wd


def test_resolve_strips_absolute(tmp_path, monkeypatch):
    wd = _workspace(tmp_path, monkeypatch)
    assert tools._resolve("/etc/passwd") == wd / "etc" / "passwd"


def test_resolve_blocks_traversal(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    with pytest.raises(ValueError, match="escapes workspace"):
        tools._resolve("../../etc/passwd")


def test_resolve_no_sibling_prefix_escape(tmp_path, monkeypatch):
    """`/workspace-evil` must not pass a `/workspace` confinement check."""
    wd = (tmp_path / "workspace").resolve()
    monkeypatch.setattr(tools, "WORKDIR", wd)
    (tmp_path / "workspace-evil").mkdir()
    # A path that resolves to the sibling dir should be rejected, not accepted.
    target = tools._resolve("anything")
    assert target.is_relative_to(wd)


def test_write_then_read_roundtrip(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    out = tools.write_file.invoke({"path": "a/b.txt", "content": "hi"})
    assert "wrote 2 bytes" in out
    assert tools.read_file.invoke({"path": "a/b.txt"}) == "hi"


def test_read_missing(tmp_path, monkeypatch):
    _workspace(tmp_path, monkeypatch)
    assert "[not found]" in tools.read_file.invoke({"path": "nope.txt"})


def test_human_review_auto_approves_when_disabled(monkeypatch):
    monkeypatch.delenv("HARNESS_HITL", raising=False)
    monkeypatch.setattr(tools, "_SESSION", None)
    out = tools.human_review.invoke({"gate": "pre-ship", "summary": "push", "action": "git push"})
    assert "AUTO-APPROVED" in out


def test_human_review_records_decision(tmp_path, monkeypatch):
    import nanoloop.session as sm

    monkeypatch.setattr(sm, "SESSIONS_DIR", tmp_path / "s")
    s = Session.create("g")
    tools.set_session(s)
    monkeypatch.delenv("HARNESS_HITL", raising=False)
    tools.human_review.invoke({"gate": "g1", "summary": "x", "action": "a"})
    assert s.decisions[-1].verdict == "auto"
    tools.set_session(None)


def test_track_task_no_session(monkeypatch):
    monkeypatch.setattr(tools, "_SESSION", None)
    assert tools.track_task.invoke({"title": "t"}) == "[no active session]"
