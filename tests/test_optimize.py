"""Scored selection: find the best that works, not the first that works."""

from __future__ import annotations

import pytest

from nanoloop import crew
from nanoloop import snapshot as snap_mod
from nanoloop.crew import Ctx, Edit, Step


def _step():
    return Step(title="shrink", target_file="m.py", intent="fewer lines")


def test_the_best_candidate_wins_not_the_first(tmp_path):
    """The whole reason this mode exists. Greedy stops at candidate 0 because it
    passes; scored keeps looking because a passing candidate is still comparable
    to the next one."""
    # Starts at 99 so every candidate is an improvement; the question under test
    # is which improvement wins, not whether any does.
    (tmp_path / "m.py").write_text("V = 99\n")
    sizes = iter([30, 10, 20])  # candidate 1 is the best

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="V = 99", replacement=f"V = {next(sizes)}")

    def scorer(ws):
        return float((ws / "m.py").read_text().split("=")[1])

    step = _step()
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["true"],
        n_candidates=3,
        scorer=scorer,
        snapshot=snap_mod.CopySnapshot(tmp_path),
    )
    assert res.ok
    assert (tmp_path / "m.py").read_text() == "V = 10\n"  # the best, not the first


def test_scored_mode_always_spends_the_whole_population(tmp_path):
    """No early exit: stopping at the first pass would throw the search away."""
    (tmp_path / "m.py").write_text("V = 0\n")
    calls = {"n": 0}

    def propose(step, ctx_text, feedback, temperature):
        calls["n"] += 1
        return Edit(path="m.py", anchor="V = 0", replacement="V = 1")

    step = _step()
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["true"],
        n_candidates=4,
        scorer=lambda ws: 1.0,
        snapshot=snap_mod.CopySnapshot(tmp_path),
    )
    assert calls["n"] == 4 and res.model_calls == 4


def test_a_candidate_scoring_none_is_out_of_the_running(tmp_path):
    (tmp_path / "m.py").write_text("V = 99\n")
    vals = iter(["1", "2"])

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="V = 99", replacement=f"V = {next(vals)}")

    def scorer(ws):
        text = (tmp_path / "m.py").read_text()
        if "V = 99" in text:
            return 50.0  # the incumbent
        return None if "V = 1" in text else 5.0

    step = _step()
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["true"],
        n_candidates=2,
        scorer=scorer,
        snapshot=snap_mod.CopySnapshot(tmp_path),
    )
    assert res.ok
    assert (tmp_path / "m.py").read_text() == "V = 2\n"


def test_failing_the_gate_removes_a_candidate_however_good_its_score(tmp_path):
    """Correctness is not the scorer's job, and a good score must never buy a
    candidate past the gate."""
    (tmp_path / "m.py").write_text("V = 0\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="V = 0", replacement="V = 1")

    step = _step()
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["false"],
        n_candidates=2,
        scorer=lambda ws: 0.0,
        snapshot=snap_mod.CopySnapshot(tmp_path),
    )
    assert not res.ok


def test_no_valid_candidate_reports_why(tmp_path):
    (tmp_path / "m.py").write_text("V = 0\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="MISSING", replacement="x")

    step = _step()
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["true"],
        n_candidates=2,
        scorer=lambda ws: 1.0,
        snapshot=snap_mod.CopySnapshot(tmp_path),
    )
    assert not res.ok and "anchor" in res.final_error


def test_without_a_scorer_the_greedy_path_is_untouched(tmp_path):
    """One call when the first candidate passes — the default economics."""
    (tmp_path / "m.py").write_text("V = 0\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="V = 0", replacement="V = 1")

    step = _step()
    res = crew.build_step(
        step, Ctx(goal="g", step=step), tmp_path, propose, gates=["true"], n_candidates=4
    )
    assert res.ok and res.model_calls == 1


def test_load_scorer_requires_a_score_function(tmp_path):
    bad = tmp_path / "s.py"
    bad.write_text("x = 1\n")
    with pytest.raises(ValueError, match="no score"):
        crew.load_scorer(bad)


def test_load_scorer_returns_the_callable(tmp_path):
    good = tmp_path / "s.py"
    good.write_text("def score(workspace):\n    return 1.0\n")
    assert crew.load_scorer(good)(tmp_path) == 1.0


def test_scored_mode_refuses_to_run_without_a_snapshot(tmp_path):
    """Without a clean tree per candidate, candidate 2 sees candidate 1's edit
    and the population collapses into a single accumulating chain."""
    (tmp_path / "m.py").write_text("V = 0\n")
    step = _step()
    with pytest.raises(ValueError, match="requires a snapshot"):
        crew.build_step(
            step,
            Ctx(goal="g", step=step),
            tmp_path,
            lambda *a: None,
            gates=["true"],
            scorer=lambda ws: 1.0,
        )


def test_a_candidate_that_does_not_improve_is_not_a_win(tmp_path):
    """Observed: a run reported 1/1 steps solved having gone from 10 gates to
    10 gates. Picking the best CANDIDATE is not the same as beating the
    incumbent, and an optimisation that does not optimise is a failure."""
    (tmp_path / "m.py").write_text("V = 5\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="V = 5", replacement="V = 5")

    def scorer(ws):
        return float((ws / "m.py").read_text().split("=")[1])

    step = _step()
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["true"],
        n_candidates=2,
        scorer=scorer,
        snapshot=snap_mod.CopySnapshot(tmp_path),
    )
    assert not res.ok
    assert "no candidate improved" in res.final_error


def test_a_real_improvement_is_still_accepted(tmp_path):
    (tmp_path / "m.py").write_text("V = 5\n")

    def propose(step, ctx_text, feedback, temperature):
        return Edit(path="m.py", anchor="V = 5", replacement="V = 2")

    def scorer(ws):
        return float((ws / "m.py").read_text().split("=")[1])

    step = _step()
    res = crew.build_step(
        step,
        Ctx(goal="g", step=step),
        tmp_path,
        propose,
        gates=["true"],
        n_candidates=2,
        scorer=scorer,
        snapshot=snap_mod.CopySnapshot(tmp_path),
    )
    assert res.ok and (tmp_path / "m.py").read_text() == "V = 2\n"
