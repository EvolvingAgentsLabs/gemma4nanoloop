"""Tests for the crew state machine, including the traps PLAN.md names explicitly."""

from __future__ import annotations

import pytest

from nanoloop import crew
from nanoloop.anchors import AnchorError, Match
from nanoloop.crew import Ctx, Edit, Plan, Step

# --- the gates=[] trap (PLAN.md §1: "Do not reintroduce") --------------------


def test_empty_gates_list_does_not_fall_through_to_defaults(tmp_path):
    """`gates or DEFAULT_GATES` makes gates=[] silently run the defaults.

    That bug was found and fixed once already. If this test fails, someone
    rewrote the `is None` check back into a truthiness check.
    """
    assert crew.run_gate(tmp_path, []) == []


def test_none_gates_uses_defaults(tmp_path, monkeypatch):
    monkeypatch.setattr(crew, "DEFAULT_GATES", ["true"])
    results = crew.run_gate(tmp_path, None)
    assert len(results) == 1 and results[0].ok


def test_gate_stops_at_first_failure(tmp_path):
    results = crew.run_gate(tmp_path, ["false", "echo second"])
    assert len(results) == 1
    assert results[0].failed


# --- truncation direction (tracebacks carry payload at the tail) -------------


def test_gate_output_truncates_from_the_front():
    text = "HEAD" + ("x" * 5000) + "AssertionError: the payload"
    out = crew._truncate_front(text, limit=100)
    assert out.endswith("AssertionError: the payload")
    assert "HEAD" not in out
    assert out.startswith("[...truncated...]")


def test_short_gate_output_untouched():
    assert crew._truncate_front("tiny", limit=100) == "tiny"


# --- anchor-based edits (D4) -------------------------------------------------


def test_apply_edit_replaces_unique_anchor(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def a():\n    return 1\n\ndef b():\n    return 2\n")
    kind = crew.apply_edit(tmp_path, Edit(path="m.py", anchor="return 1", replacement="return 42"))
    assert kind == Match.EXACT.value
    assert "return 42" in f.read_text()


def test_apply_edit_raises_on_ambiguous_anchor(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("x = 1\ny = 1\n")
    with pytest.raises(AnchorError) as exc:
        crew.apply_edit(tmp_path, Edit(path="m.py", anchor="= 1", replacement="= 2"))
    assert exc.value.kind is Match.AMBIGUOUS
    assert f.read_text() == "x = 1\ny = 1\n"  # unchanged: fail loudly, corrupt nothing


def test_apply_edit_raises_on_missing_anchor(tmp_path):
    (tmp_path / "m.py").write_text("a = 1\n")
    with pytest.raises(AnchorError) as exc:
        crew.apply_edit(tmp_path, Edit(path="m.py", anchor="nope", replacement="x"))
    assert exc.value.kind is Match.NOT_FOUND


def test_apply_edit_blocks_path_escape(tmp_path):
    with pytest.raises(ValueError, match="escapes workspace"):
        crew.apply_edit(tmp_path, Edit(path="../evil.py", anchor="a", replacement="b"))


# --- context compiler (D6) ---------------------------------------------------


def test_ctx_render_includes_error_and_omits_transcript():
    ctx = Ctx(
        goal="G",
        done=["one"],
        step=Step(title="T", target_file="f.py", intent="I"),
        last_error="boom",
    )
    out = ctx.render()
    assert "G" in out and "one" in out and "T" in out and "boom" in out


def test_ctx_render_is_stateless_between_calls():
    ctx = Ctx(goal="G")
    first = ctx.render()
    assert ctx.render() == first  # renders fresh, accumulates nothing


# --- build_step: the verified 2-call behaviour (PLAN.md §1) ------------------


def test_greedy_failure_then_repair_costs_two_calls(tmp_path):
    """Greedy fails a gate -> exact error is injected -> second attempt passes.

    2 model calls, not 7. This reproduces the mock-model result PLAN.md §1
    reports as verified, and it is the regression test for D7.
    """
    target = tmp_path / "m.py"
    target.write_text("VALUE = 1\n")
    seen_feedback = []
    calls = {"n": 0}

    def propose(step, ctx_text, feedback, temperature):
        calls["n"] += 1
        seen_feedback.append(feedback)
        if calls["n"] == 1:
            return Edit(path="m.py", anchor="VALUE = 1", replacement="VALUE = 2")
        return Edit(path="m.py", anchor="VALUE = 2", replacement="VALUE = 3")

    # Gate passes only once the file says 3.
    gate = [f"grep -q 'VALUE = 3' {target}"]
    step = Step(title="bump", target_file="m.py", intent="VALUE is 3")
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, propose, gates=gate)

    assert res.ok
    assert res.model_calls == 2
    assert res.repair_attempts == 1
    assert seen_feedback[0] == ""  # greedy gets no feedback
    assert "failed" in seen_feedback[1]  # repair gets the exact error


def test_greedy_success_costs_one_call(tmp_path):
    (tmp_path / "m.py").write_text("A = 1\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="A = 1", replacement="A = 2")

    step = Step(title="t", target_file="m.py", intent="i")
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, propose, gates=["true"])
    assert res.ok and res.model_calls == 1 and res.repair_attempts == 0


def test_anchor_error_feeds_the_repair_loop(tmp_path):
    (tmp_path / "m.py").write_text("A = 1\n")
    feedback_seen = []

    def propose(step, ctx_text, feedback, temperature):
        feedback_seen.append(feedback)
        anchor = "MISSING" if not feedback else "A = 1"
        return Edit(path="m.py", anchor=anchor, replacement="A = 2")

    step = Step(title="t", target_file="m.py", intent="i")
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, propose, gates=["true"])
    assert res.ok
    assert "anchor not found" in feedback_seen[1]
    assert res.anchor_kinds == ["not_found", "exact"]


def test_n_candidates_defaults_to_two_not_three():
    """PLAN.md §2 D7: on this hardware best-of-N is expensive. Default low."""
    assert crew.DEFAULT_N_CANDIDATES == 2


# --- phase binding (the -85% result) ----------------------------------------


def test_plan_and_test_phases_offer_no_tools():
    assert crew.PHASE_TOOLS["plan"] == []
    assert crew.PHASE_TOOLS["test"] == []


def test_every_phase_has_a_context_budget():
    assert set(crew.PHASE_TOOLS) == set(crew.PHASE_NUM_CTX)
    assert all(v <= 32768 for v in crew.PHASE_NUM_CTX.values())  # LiteRT-LM ceiling


def test_schemas_are_small():
    """Schema cost is paid on every call; keep an eye on it."""
    assert crew.schema_of(Edit)["properties"].keys() == {"path", "anchor", "replacement"}
    assert "steps" in crew.schema_of(Plan)["properties"]


# --- run_plan stops on failure ----------------------------------------------


def test_run_plan_halts_after_a_failed_step(tmp_path):
    (tmp_path / "a.py").write_text("A = 1\n")
    (tmp_path / "b.py").write_text("B = 1\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path=step.target_file, anchor="NOPE", replacement="x")

    plan = Plan(
        steps=[
            Step(title="s1", target_file="a.py", intent="i"),
            Step(title="s2", target_file="b.py", intent="i"),
        ]
    )
    results = crew.run_plan(
        plan, "g", tmp_path, propose, gates=["true"], max_repairs=0, n_candidates=1
    )
    assert len(results) == 1 and not results[0].ok
