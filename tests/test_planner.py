"""Planner resilience: a degenerate greedy sample must not kill the run."""

from __future__ import annotations

import json

import pytest

from nanoloop import crew, planner


def test_extract_json_handles_a_fenced_block():
    assert planner._extract_json('```json\n{"steps": []}\n```') == {"steps": []}


def test_extract_json_handles_a_prose_preamble():
    assert planner._extract_json('Sure!\n{"steps": []}') == {"steps": []}


def test_retries_with_temperature_after_a_degenerate_sample(monkeypatch):
    """Observed: greedy fell into `items carrying the tags are ...` until the
    output cap, leaving unterminated JSON. Retrying at temperature 0 would
    reproduce it byte for byte — sampling is what breaks the loop."""
    seen: list[float] = []

    def fake_chat(system, user, **kw):
        seen.append(kw["temperature"])
        if len(seen) == 1:
            return '{"steps": [{"title": "t", "target_file": "a.py", "intent": "the tags are'
        return '{"steps": [{"title": "t", "target_file": "a.py", "intent": "i"}]}'

    monkeypatch.setattr(planner.model_ollama, "chat", fake_chat)
    plan = planner.propose_plan("goal", "map", skills_catalog="")
    assert len(plan.steps) == 1
    assert seen[0] == 0.0 and seen[1] > 0.0  # greedy, then sampled


def test_gives_up_cleanly_after_three_attempts(monkeypatch):
    monkeypatch.setattr(planner.model_ollama, "chat", lambda *a, **k: "not json at all")
    with pytest.raises(RuntimeError, match="no valid plan in 3 attempts"):
        planner.propose_plan("goal", "map", skills_catalog="")


def test_acceptance_criteria_survive_parsing(monkeypatch):
    payload = {
        "steps": [{"title": "t", "target_file": "a.py", "intent": "i"}],
        "acceptance": [{"symbol": "by_tag", "file": "a.py"}],
    }
    monkeypatch.setattr(planner.model_ollama, "chat", lambda *a, **k: json.dumps(payload))
    plan = planner.propose_plan("goal", "map", skills_catalog="")
    assert plan.acceptance[0].symbol == "by_tag"
    assert isinstance(plan.acceptance[0], crew.Acceptance)


def test_retries_a_transient_backend_failure(monkeypatch):
    """An empty completion or a rate limit surfaces as RuntimeError. Not
    catching it turned a recoverable hiccup into a traceback mid-run."""
    calls = {"n": 0}

    def flaky(system, user, **kw):
        calls["n"] += 1
        if calls["n"] == 1:
            raise RuntimeError("model returned empty content (0 chars of reasoning)")
        return '{"steps": [{"title": "t", "target_file": "a.py", "intent": "i"}]}'

    monkeypatch.setattr(planner.model_ollama, "chat", flaky)
    assert len(planner.propose_plan("g", "m", skills_catalog="").steps) == 1
    assert calls["n"] == 2


def test_persistent_backend_failure_reports_cleanly(monkeypatch):
    def dead(*a, **k):
        raise RuntimeError("backend down")

    monkeypatch.setattr(planner.model_ollama, "chat", dead)
    with pytest.raises(RuntimeError, match="no valid plan in 3 attempts"):
        planner.propose_plan("g", "m", skills_catalog="")
