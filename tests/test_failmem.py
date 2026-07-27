"""Failure memory. The danger is staleness, not storage."""

from __future__ import annotations

import time

from nanoloop import failmem
from nanoloop.failmem import Attempt


def _p(tmp_path):
    return tmp_path / "attempts.jsonl"


def test_a_failure_is_recalled_for_a_similar_goal(tmp_path):
    """Goals are worded differently every run; an exact key matched almost
    nothing, so one extra word made a goal unrecognisable to its own failure."""
    p = _p(tmp_path)
    failmem.record(Attempt("add by_tag to Store", "todo/store.py", "unmet", "check failed"), p)
    assert failmem.lessons("implement by_tag(tag) on Store", path=p)


def test_an_unrelated_goal_recalls_nothing(tmp_path):
    p = _p(tmp_path)
    failmem.record(Attempt("add by_tag to Store", "todo/store.py", "unmet", "x"), p)
    assert failmem.lessons("configure the CI pipeline", path=p) == []


def test_a_later_success_supersedes_the_failure(tmp_path):
    """A remembered failure that has since been fixed is WORSE than no memory:
    it steers the planner away from something that now works."""
    p = _p(tmp_path)
    failmem.record(Attempt("add by_tag", "todo/store.py", "unmet", "x", ts=1.0), p)
    failmem.record(Attempt("add by_tag", "todo/store.py", "solved", ts=2.0), p)
    assert failmem.lessons("add by_tag", path=p) == []


def test_an_earlier_success_does_not_supersede_a_newer_failure(tmp_path):
    """It worked once and broke again — that is exactly worth remembering."""
    p = _p(tmp_path)
    failmem.record(Attempt("add by_tag", "todo/store.py", "solved", ts=1.0), p)
    failmem.record(Attempt("add by_tag", "todo/store.py", "unmet", "broke", ts=2.0), p)
    assert failmem.lessons("add by_tag", path=p)


def test_matching_also_works_by_file(tmp_path):
    p = _p(tmp_path)
    failmem.record(Attempt("something else entirely", "todo/store.py", "gave_up", "budget"), p)
    assert failmem.lessons("unrelated words", target_file="todo/store.py", path=p)


def test_lessons_are_capped(tmp_path):
    p = _p(tmp_path)
    for i in range(10):
        failmem.record(Attempt("add by_tag to Store", "s.py", "unmet", f"fail {i}"), p)
    assert len(failmem.lessons("add by_tag to Store", path=p)) == failmem.MAX_LESSONS


def test_newest_failure_comes_first(tmp_path):
    p = _p(tmp_path)
    failmem.record(Attempt("add by_tag", "s.py", "unmet", "older", ts=1.0), p)
    failmem.record(Attempt("add by_tag", "s.py", "unmet", "newer", ts=2.0), p)
    assert "newer" in failmem.lessons("add by_tag", path=p)[0]


def test_render_is_empty_without_history(tmp_path):
    assert failmem.render("anything", path=_p(tmp_path)) == ""


def test_render_tells_the_planner_what_to_do(tmp_path):
    p = _p(tmp_path)
    failmem.record(Attempt("add by_tag", "s.py", "unmet", "check failed"), p)
    text = failmem.render("add by_tag", path=p)
    assert "Previous attempts" in text and "Plan differently" in text


def test_recording_never_raises(tmp_path):
    blocked = tmp_path / "dir"
    blocked.mkdir()
    failmem.record(Attempt("g", "f", "unmet"), blocked)  # a flight recorder must not crash


def test_a_truncated_line_is_tolerated(tmp_path):
    p = _p(tmp_path)
    failmem.record(Attempt("add by_tag", "s.py", "unmet", "x"), p)
    with p.open("a") as fh:
        fh.write('{"goal": "cut')
    assert len(failmem.read(p)) == 1


def test_timestamps_default_to_now():
    assert Attempt("g", "f", "unmet").ts > time.time() - 5
