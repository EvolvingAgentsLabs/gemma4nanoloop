"""Replanning: an unmet criterion becomes the goal of a second pass."""

from __future__ import annotations

from nanoloop import crew
from nanoloop.crew import Acceptance, Edit, Plan, Step


def _plan(steps, acceptance):
    return Plan(steps=steps, acceptance=acceptance)


def test_replans_until_the_criterion_is_satisfied(tmp_path):
    """The observed gap: planner covered add() but not by_tag, every step green,
    goal half done. Round 2 gets the unmet criterion as its brief."""
    (tmp_path / "s.py").write_text("def add():\n    pass\n")
    seen_gaps = []

    def plan_fn(goal, repo_map, gaps):
        seen_gaps.append(gaps)
        acc = [Acceptance(symbol="add", file="s.py"), Acceptance(symbol="by_tag", file="s.py")]
        if not gaps:  # first pass forgets by_tag, exactly as observed
            return _plan([Step(title="add", target_file="s.py", intent="i")], acc)
        return _plan([Step(title="by_tag", target_file="s.py", intent="i")], acc)

    def propose(step, ctx_text, feedback, temperature):
        if step.title == "by_tag":
            return Edit(
                path="s.py",
                anchor="def add():",
                replacement="def by_tag():\n    pass\n\n\ndef add():",
            )
        return Edit(path="s.py", anchor="def add():", replacement="def add():")

    res = crew.run_goal("add by_tag and add", tmp_path, plan_fn, propose, gates=["true"])
    assert res.ok
    assert res.rounds == 2
    assert seen_gaps[0] is None
    assert "by_tag" in seen_gaps[1][0]
    assert crew.defines_symbol(tmp_path, "s.py", "by_tag")


def test_no_replan_when_the_first_plan_covers_the_goal(tmp_path):
    (tmp_path / "s.py").write_text("def by_tag():\n    pass\n")
    calls = {"n": 0}

    def plan_fn(goal, repo_map, gaps):
        calls["n"] += 1
        return _plan([], [Acceptance(symbol="by_tag", file="s.py")])

    res = crew.run_goal("add by_tag", tmp_path, plan_fn, lambda *a: None, gates=["true"])
    assert res.ok and res.rounds == 1 and calls["n"] == 1


def test_replanning_is_bounded(tmp_path):
    """A planner that cannot satisfy a criterion in two extra passes will not on
    the third; looping would burn tokens forever on an impossible criterion."""
    (tmp_path / "s.py").write_text("x = 1\n")
    calls = {"n": 0}

    def plan_fn(goal, repo_map, gaps):
        calls["n"] += 1
        return _plan([], [Acceptance(symbol="never_appears", file="s.py")])

    # The goal must MENTION the symbol, or _grounded() rightly discards the
    # criterion as invented and the run passes.
    res = crew.run_goal(
        "add never_appears", tmp_path, plan_fn, lambda *a: None, gates=["true"], max_replans=2
    )
    assert not res.ok
    assert res.rounds == 3 and calls["n"] == 3
    assert "never_appears" in res.unmet[0]


def test_criteria_carry_across_rounds(tmp_path):
    """A second plan may drop or reword a criterion; the goal's requirements do
    not change just because the planner forgot one."""
    (tmp_path / "s.py").write_text("def add():\n    pass\n")

    def plan_fn(goal, repo_map, gaps):
        if not gaps:
            return _plan(
                [],
                [Acceptance(symbol="add", file="s.py"), Acceptance(symbol="by_tag", file="s.py")],
            )
        return _plan([], [])  # round 2 forgets everything

    res = crew.run_goal(
        "add by_tag and add", tmp_path, plan_fn, lambda *a: None, gates=["true"], max_replans=1
    )
    assert not res.ok
    assert any("by_tag" in u for u in res.unmet)


def test_repo_map_is_rebuilt_each_round(tmp_path):
    """Round 2 must see what round 1 built, or it plans the same work again."""
    (tmp_path / "s.py").write_text("def add():\n    pass\n")
    maps = []

    def plan_fn(goal, repo_map, gaps):
        maps.append(repo_map)
        if not gaps:
            return _plan(
                [Step(title="mk", target_file="s.py", intent="i")],
                [Acceptance(symbol="by_tag", file="s.py")],
            )
        return _plan([], [Acceptance(symbol="by_tag", file="s.py")])

    def propose(step, ctx_text, feedback, temperature):
        return Edit(
            path="s.py", anchor="def add():", replacement="def by_tag():\n    pass\n\n\ndef add():"
        )

    crew.run_goal("g", tmp_path, plan_fn, propose, gates=["true"])
    assert "by_tag" not in maps[0]
    assert len(maps) == 1 or "by_tag" in maps[1]


def test_merged_criteria_keep_their_executable_check(tmp_path):
    """Rebuilding criteria from (symbol, file) dropped `check`, so verification
    silently fell back to "does this name exist". A task that committed a
    summarize() returning the wrong type was reported SOLVED because the test
    function it was meant to satisfy still existed."""
    (tmp_path / "s.py").write_text("def wrong():\n    return 'nope'\n")
    check = "from s import wrong\nassert wrong() == 'right'\n"

    def plan_fn(goal, repo_map, gaps):
        return _plan([], [Acceptance(symbol="wrong", file="s.py", check=check)])

    res = crew.run_goal(
        "fix wrong", tmp_path, plan_fn, lambda *a: None, gates=["true"], max_replans=0
    )
    assert not res.ok
    assert "check failed" in res.unmet[0]


def test_a_later_round_cannot_weaken_an_earlier_criterion(tmp_path):
    (tmp_path / "s.py").write_text("def wrong():\n    return 'nope'\n")
    check = "from s import wrong\nassert wrong() == 'right'\n"
    rounds = {"n": 0}

    def plan_fn(goal, repo_map, gaps):
        rounds["n"] += 1
        if rounds["n"] == 1:
            return _plan([], [Acceptance(symbol="wrong", file="s.py", check=check)])
        return _plan([], [Acceptance(symbol="wrong", file="s.py")])  # no check

    res = crew.run_goal(
        "fix wrong", tmp_path, plan_fn, lambda *a: None, gates=["true"], max_replans=1
    )
    assert not res.ok and "check failed" in res.unmet[0]


def test_a_met_criterion_outranks_a_failed_step(tmp_path):
    """The mirror image of "green but not done". Observed: a run reduced a
    circuit exactly as asked, its criterion passed, and it still exited 1
    because a later step found nothing left to remove. Under harvest --deliver
    that discards completed work instead of committing it."""
    (tmp_path / "s.py").write_text("def done():\n    return 1\n")

    def plan_fn(goal, repo_map, gaps):
        return _plan(
            [Step(title="impossible", target_file="s.py", intent="i")],
            [
                Acceptance(
                    symbol="done", file="s.py", check="from s import done\nassert done() == 1\n"
                )
            ],
        )

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="s.py", anchor="NOT PRESENT", replacement="x")

    res = crew.run_goal(
        "make done work", tmp_path, plan_fn, propose, gates=["true"], max_replans=0, n_candidates=1
    )
    assert not all(r.ok for r in res.steps)  # a step really did fail
    assert res.unmet == []  # but the goal is met
    assert res.ok


def test_without_criteria_a_failed_step_still_fails_the_goal(tmp_path):
    """Nothing better to go on, so the steps remain the verdict."""
    (tmp_path / "s.py").write_text("X = 1\n")

    def plan_fn(goal, repo_map, gaps):
        return _plan([Step(title="t", target_file="s.py", intent="i")], [])

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="s.py", anchor="NOT PRESENT", replacement="x")

    res = crew.run_goal(
        "g", tmp_path, plan_fn, propose, gates=["true"], max_replans=0, n_candidates=1
    )
    assert not res.ok


def test_giving_up_still_overrides_everything(tmp_path):
    res = crew.GoalResult(gave_up="budget exhausted")
    assert not res.ok
