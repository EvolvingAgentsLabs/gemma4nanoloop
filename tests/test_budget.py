"""Per-task budget. Running out is a result, not a crash."""

from __future__ import annotations

import time

import pytest

from nanoloop import budget as budget_mod
from nanoloop.budget import Budget, BudgetExhausted


def test_no_limits_never_stops():
    b = Budget()
    for _ in range(100):
        b.check()
        b.spend(1000)
    assert b.calls == 100


def test_call_limit_stops_before_spending():
    """Checked BEFORE the call: starting work you cannot pay for wastes the
    most expensive thing in the loop."""
    b = Budget(max_calls=3)
    for _ in range(3):
        b.check()
        b.spend()
    with pytest.raises(BudgetExhausted) as exc:
        b.check()
    assert b.calls == 3  # nothing spent past the limit
    assert "max_calls=3" in str(exc.value)


def test_token_limit():
    b = Budget(max_tokens=100)
    b.check()
    b.spend(150)
    with pytest.raises(BudgetExhausted, match="max_tokens"):
        b.check()


def test_time_limit():
    b = Budget(max_seconds=0.05)
    b.check()
    time.sleep(0.06)
    with pytest.raises(BudgetExhausted, match="max_seconds"):
        b.check()


def test_reset_keeps_limits_and_clears_spending():
    b = Budget(max_calls=2)
    b.spend()
    b.spend()
    b.reset()
    assert b.calls == 0 and b.max_calls == 2
    b.check()  # affordable again


def test_remaining_reports_only_configured_limits():
    assert Budget(max_calls=5).remaining() == {"calls": 5}
    assert Budget().remaining() == {}


def test_summary_mentions_spend_and_limits():
    b = Budget(max_calls=4)
    b.spend(50)
    s = b.summary()
    assert "1 call" in s and "50 tokens" in s and "max_calls=4" in s


def test_module_level_helpers_are_inert_without_a_budget():
    budget_mod.set_active(None)
    budget_mod.check()  # must not raise
    budget_mod.spend(10)


def test_module_level_helpers_use_the_active_budget():
    b = Budget(max_calls=1)
    budget_mod.set_active(b)
    try:
        budget_mod.check()
        budget_mod.spend(7)
        with pytest.raises(BudgetExhausted):
            budget_mod.check()
        assert b.tokens == 7
    finally:
        budget_mod.set_active(None)


# --- integration with the loop ----------------------------------------------


def test_running_out_ends_the_goal_as_gave_up(tmp_path):
    """Not a crash and not a failure of the work: a decision to stop."""
    from nanoloop import crew

    (tmp_path / "s.py").write_text("X = 1\n")
    b = Budget(max_calls=0)
    budget_mod.set_active(b)

    def plan_fn(goal, repo_map, gaps):
        budget_mod.check()
        return crew.Plan(steps=[])

    try:
        b.max_calls = 1
        b.spend()  # already at the limit
        res = crew.run_goal("g", tmp_path, plan_fn, lambda *a: None, gates=["true"])
    finally:
        budget_mod.set_active(None)

    assert res.gave_up and "max_calls" in res.gave_up
    assert not res.ok


def test_gave_up_is_distinct_from_unmet_criteria(tmp_path):
    from nanoloop import crew

    res = crew.GoalResult(gave_up="budget exhausted (max_calls=1): 1 call(s), 0s")
    assert not res.ok and not res.unmet  # stopped, not judged wrong


def test_is_not_a_runtimeerror():
    """`chat()` raises RuntimeError for transient backend trouble and callers
    retry on it. Subclassing RuntimeError made "stop spending" look like "try
    again": the planner retried three times and reported a bogus "no valid plan
    in 3 attempts" instead of the budget stop."""
    assert not issubclass(BudgetExhausted, RuntimeError)


def test_a_retry_handler_for_transient_errors_does_not_swallow_it():
    def retrying():
        for _ in range(3):
            try:
                raise BudgetExhausted(Budget(max_calls=1), "max_calls=1")
            except RuntimeError:  # the planner's transient-failure handler
                continue
        return "retried"

    with pytest.raises(BudgetExhausted):
        retrying()
