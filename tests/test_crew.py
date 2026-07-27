"""Tests for the crew state machine, including the traps PLAN.md names explicitly."""

from __future__ import annotations

import os
from pathlib import Path

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


# --- gates must see the venv (found by the first end-to-end run) -------------


def test_gate_env_puts_the_interpreter_bin_first():
    """Gates run through `sh`, which does not inherit an activated virtualenv.
    Without this, bare `ruff` fails with `command not found` and the repair loop
    burns attempts on an error no edit can fix."""
    import sys
    from pathlib import Path

    env = crew._gate_env()
    assert env["PATH"].split(os.pathsep)[0] == str(Path(sys.executable).parent)


def test_gates_can_actually_run_ruff(tmp_path):
    (tmp_path / "ok.py").write_text("x = 1\n")
    results = crew.run_gate(tmp_path, ["ruff --version"])
    assert results[0].ok, results[0].output


# --- file creation: empty anchor, new file only -----------------------------


def test_empty_anchor_creates_a_new_file(tmp_path):
    kind = crew.apply_edit(tmp_path, Edit(path="pkg/new.py", anchor="", replacement="X = 1\n"))
    assert kind == "created"
    assert (tmp_path / "pkg" / "new.py").read_text() == "X = 1\n"


def test_empty_anchor_refuses_to_overwrite_an_existing_file(tmp_path):
    """D4's real content: never regenerate a file that already exists."""
    f = tmp_path / "m.py"
    f.write_text("IMPORTANT = 1\n")
    with pytest.raises(AnchorError) as exc:
        crew.apply_edit(tmp_path, Edit(path="m.py", anchor="", replacement="wiped"))
    assert exc.value.kind is Match.AMBIGUOUS
    assert f.read_text() == "IMPORTANT = 1\n"


def test_missing_file_with_a_real_anchor_says_how_to_create_it(tmp_path):
    with pytest.raises(AnchorError) as exc:
        crew.apply_edit(tmp_path, Edit(path="a.py", anchor="x", replacement="y"))
    assert "leave `anchor` empty" in str(exc.value)


# --- skill steps: zero model calls -------------------------------------------


def test_skill_step_runs_without_calling_the_model(tmp_path, monkeypatch):
    import nanoloop.skills as sk

    monkeypatch.setattr(sk, "SKILLS_DIR", Path(__file__).resolve().parent.parent / "Skills")

    def propose(*a):
        raise AssertionError("a skill step must not call the model")

    step = Step(
        title="scaffold",
        target_file="app/main.py",
        intent="service exists",
        skill="scaffold-fastapi",
        skill_data='{"title": "svc"}',
    )
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, propose, gates=["true"])
    assert res.ok
    assert res.model_calls == 0
    assert res.anchor_kinds == ["skill"]
    assert (tmp_path / "app" / "main.py").exists()


def test_unknown_skill_fails_loudly(tmp_path):
    step = Step(title="x", target_file="a.py", intent="i", skill="does-not-exist")
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, lambda *a: None, gates=["true"])
    assert not res.ok and "no skill" in res.final_error


def test_bad_skill_data_fails_loudly(tmp_path, monkeypatch):
    import nanoloop.skills as sk

    monkeypatch.setattr(sk, "SKILLS_DIR", Path(__file__).resolve().parent.parent / "Skills")
    step = Step(
        title="x", target_file="a.py", intent="i", skill="setup-pytest", skill_data="{not json"
    )
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, lambda *a: None, gates=["true"])
    assert not res.ok and "not valid JSON" in res.final_error


def test_ordinary_steps_still_have_no_skill():
    assert Step(title="t", target_file="f.py", intent="i").skill == ""


# --- syntax validation before writing ---------------------------------------


def test_unparseable_python_is_rejected_before_touching_disk(tmp_path):
    """Observed 4x in a row: `store.add("Task 1", ["work"]` — one missing paren.
    ruff would catch it a gate later; this catches it with line and reason, and
    the broken file never exists at all."""
    bad = 'def f():\n    g("a", ["b"]\n    h("c")\n'
    with pytest.raises(crew.SyntaxErrorInEdit) as exc:
        crew.apply_edit(tmp_path, Edit(path="t.py", anchor="", replacement=bad))
    assert "not valid" in str(exc.value)
    assert not (tmp_path / "t.py").exists()


def test_valid_python_is_created(tmp_path):
    crew.apply_edit(tmp_path, Edit(path="t.py", anchor="", replacement="X = 1\n"))
    assert (tmp_path / "t.py").read_text() == "X = 1\n"


def test_non_python_files_are_not_syntax_checked(tmp_path):
    crew.apply_edit(tmp_path, Edit(path="notes.md", anchor="", replacement="# ((("))
    assert (tmp_path / "notes.md").exists()


def test_syntax_error_reaches_the_repair_loop(tmp_path):
    """SyntaxErrorInEdit is a ValueError, so build_step feeds it back as text."""
    seen = []

    def propose(step, ctx_text, feedback, temperature):
        seen.append(feedback)
        body = "def f(:\n" if not feedback else "X = 1\n"
        return Edit(path="t.py", anchor="", replacement=body)

    step = Step(title="t", target_file="t.py", intent="i")
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, propose, gates=["true"])
    assert res.ok
    assert "not valid" in seen[1]


def test_repo_map_is_rendered_only_for_new_files():
    """Writing a module means writing its imports. Without the map the model
    invents package names (`todo_app` for a package called `todo`); for an
    ordinary edit the map is just noise in a tight budget."""
    step = Step(title="t", target_file="new.py", intent="i")
    with_map = Ctx(goal="g", step=step, repo_map="todo/store.py\n    defines: Store").render()
    assert "do not invent" in with_map and "todo/store.py" in with_map
    assert "Modules that exist" not in Ctx(goal="g", step=step).render()


# --- deterministic normalization before gating ------------------------------


def test_autofix_removes_an_unused_import(tmp_path):
    """F401 and I001 are in ruff's auto-fixable set. Spending a model repair
    round trip on them — observed three times on one task — is pure waste."""
    f = tmp_path / "t.py"
    f.write_text('"""D."""\n\nimport pytest\n\nX = 1\n')
    crew.autofix(tmp_path, "t.py")
    assert "import pytest" not in f.read_text()
    assert "X = 1" in f.read_text()


def test_autofix_sorts_imports(tmp_path):
    f = tmp_path / "t.py"
    f.write_text('"""D."""\n\nimport sys\nimport os\n\nprint(os, sys)\n')
    crew.autofix(tmp_path, "t.py")
    text = f.read_text()
    assert text.index("import os") < text.index("import sys")


def test_autofix_leaves_real_errors_alone(tmp_path):
    """A genuine mistake must still reach the model as gate feedback."""
    f = tmp_path / "t.py"
    f.write_text('"""D."""\n\nX = undefined_name\n')
    crew.autofix(tmp_path, "t.py")
    assert "undefined_name" in f.read_text()


def test_autofix_ignores_non_python(tmp_path):
    f = tmp_path / "a.md"
    f.write_text("# hi\n")
    crew.autofix(tmp_path, "a.md")
    assert f.read_text() == "# hi\n"


def test_autofix_tolerates_a_missing_file(tmp_path):
    crew.autofix(tmp_path, "nope.py")  # must not raise


# --- per-step intent verification --------------------------------------------


def test_gates_green_is_not_enough_when_a_step_must_define_something(tmp_path):
    """The failure this exists for: a step titled "Add by_tag method" instead
    made complete() case-insensitive. Valid code, all three gates green,
    reported ok — and by_tag never existed. Gates prove the repo is healthy,
    not that THIS step happened."""
    f = tmp_path / "m.py"
    f.write_text("def existing():\n    return 1\n")

    def propose(step, ctx_text, feedback, temperature):
        # A real but unrelated edit — exactly the observed failure.
        return Edit(path="m.py", anchor="return 1", replacement="return 2")

    step = Step(title="add by_tag", target_file="m.py", intent="i", defines="by_tag")
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["true"],
        max_repairs=0,
        n_candidates=1,
    )
    assert not res.ok
    assert "by_tag" in res.final_error and "still not defined" in res.final_error


def test_step_passes_once_the_symbol_appears(tmp_path):
    f = tmp_path / "m.py"
    f.write_text("def existing():\n    return 1\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(
            path="m.py",
            anchor="def existing():",
            replacement="def by_tag(tag):\n    return []\n\n\ndef existing():",
        )

    step = Step(title="add by_tag", target_file="m.py", intent="i", defines="by_tag")
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, propose, gates=["true"])
    assert res.ok


def test_steps_without_a_named_symbol_are_unaffected(tmp_path):
    (tmp_path / "m.py").write_text("X = 1\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="X = 1", replacement="X = 2")

    step = Step(title="bump", target_file="m.py", intent="i")  # defines=""
    res = crew.build_step(step, Ctx(goal="g", step=step), tmp_path, propose, gates=["true"])
    assert res.ok


def test_defines_symbol_finds_methods_inside_classes(tmp_path):
    (tmp_path / "m.py").write_text("class S:\n    def by_tag(self):\n        pass\n")
    assert crew.defines_symbol(tmp_path, "m.py", "by_tag")
    assert not crew.defines_symbol(tmp_path, "m.py", "missing")
