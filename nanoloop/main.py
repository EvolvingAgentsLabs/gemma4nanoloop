"""CLI for the crew.

The DeepAgents orchestrator that used to live here is gone (D1). What remains is
a thin dispatcher over the graph in crew.py plus the Phase 0 verification
subcommands, because a runtime you cannot interrogate is a runtime you cannot
trust.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from . import calllog, crew, repomap, skills, tools
from .planner import propose_plan
from .proposer import propose, propose_new_file
from .session import Session


def _console():
    try:
        from rich.console import Console

        return Console()
    except ImportError:

        class Plain:
            def print(self, *a, **k):
                print(*[str(x) for x in a])

        return Plain()


def cmd_probe(args) -> int:
    """Phase 0: do the endpoints answer?"""
    from . import model_ollama

    con = _console()
    for backend in args.backend.split(",") if args.backend else ["ollama"]:
        os.environ["NANOLOOP_BACKEND"] = backend
        model_ollama.BACKEND = backend
        con.print(json.dumps(model_ollama.probe(), indent=2))
    return 0


def cmd_verify_ctx(args) -> int:
    """Phase 0 verification #1: is num_ctx actually honored?

    Sends a prompt deliberately larger than num_ctx. A server that honors the
    setting reports truncation; one that silently drops it just answers. PLAN.md
    §1 warns this failure is invisible in an agent loop — it looks like the model
    forgetting, not like a config error.
    """
    from . import model_ollama

    con = _console()
    num_ctx = args.num_ctx
    # ~4 chars/token, so overshoot the window by ~3x with countable content.
    filler = "\n".join(
        f"line {i}: the quick brown fox jumps over the lazy dog" for i in range(num_ctx * 3 // 4)
    )
    prompt = (
        f"{filler}\n\nWhat was the number on the FIRST line of this message? "
        f"Answer with just the number."
    )
    con.print(
        f"[verify-ctx] num_ctx={num_ctx}, prompt chars={len(prompt)} (~{len(prompt) // 4} tokens)"
    )
    con.print(f"[verify-ctx] extra_body={json.dumps(model_ollama.build_extra_body(num_ctx))}")
    try:
        out = model_ollama.chat("Answer in one word.", prompt, phase="verify_ctx", num_ctx=num_ctx)
        con.print(f"[verify-ctx] reply: {out.strip()[:120]}")
        con.print(
            "[verify-ctx] If the reply is NOT 'line 0'/'0', the front of the "
            "prompt was truncated — which is the expected, correct behaviour. "
            "Now confirm the server LOGGED the truncation: check `ollama serve` "
            "output for a context/truncation warning. No warning + correct "
            "answer means num_ctx never reached the server."
        )
    except RuntimeError as e:
        con.print(f"[verify-ctx] call failed: {e}")
        return 1
    return 0


def cmd_map(args) -> int:
    print(repomap.build(args.workspace))
    return 0


def cmd_plan(args) -> int:
    con = _console()
    rmap = repomap.build(args.workspace)
    plan = propose_plan(args.goal, rmap)
    con.print(json.dumps(plan.model_dump(), indent=2))
    return 0


def _load_criteria(path: str) -> list:
    """Read acceptance criteria from a JSON file: [{symbol, file, check}, ...]."""
    raw = json.loads(Path(path).read_text(encoding="utf-8"))
    return [crew.Acceptance.model_validate(r) for r in raw]


def cmd_run(args) -> int:
    """Full loop: plan -> iterate steps -> gates, with HITL at both ends."""
    con = _console()
    calllog.reset_clock()
    workspace = Path(args.workspace).resolve()
    workspace.mkdir(parents=True, exist_ok=True)

    session = Session.create(args.goal)
    tools.set_session(session)
    tools.set_workdir(workspace)  # keep the tools' root and --workspace the same
    if args.interactive:
        os.environ["HARNESS_HITL"] = "1"

    # Before anything: is this repo even sane? A pre-existing failure is
    # indistinguishable from a bad edit once the repair loop sees it.
    if not args.skip_preflight:
        pf = crew.preflight(workspace, None if not args.no_gates else [])
        con.print(pf.report())
        if not pf.ok:
            con.print(
                "[preflight] refusing to start. Fix the repo (or pass "
                "--skip-preflight if you know what you are doing)."
            )
            return 3

    con.print(f"[plan] {args.goal}")

    from . import budget as budget_mod
    from . import snapshot as snap_mod

    task_budget = budget_mod.Budget(
        max_calls=getattr(args, "max_calls", 0),
        max_seconds=getattr(args, "max_seconds", 0.0),
        max_tokens=getattr(args, "max_tokens", 0),
    )
    budget_mod.set_active(task_budget.reset())

    snap = snap_mod.make(workspace, args.snapshot)
    catalog = skills.catalog_text()
    approved = {"ok": True}

    user_criteria = getattr(args, "_criteria", None) or (
        _load_criteria(args.accept) if args.accept else []
    )
    if user_criteria:
        con.print(
            f"[acceptance] {len(user_criteria)} criterion(s) supplied by you "
            f"(the planner's own are ignored)"
        )

    def _plan_fn(goal, repo_map, gaps):
        from . import failmem

        # Only on the first pass: within a run, `gaps` already says what is
        # missing, and adding old failures on top would just crowd the prompt.
        past = failmem.render(goal) if not gaps else ""
        if past:
            con.print(f"[memory] {past.count(chr(10) + '-')} past failure(s) inform this plan")
        plan = propose_plan(goal, repo_map, gaps=gaps, lessons=past)
        # Yours win outright. The planner has been observed inventing criteria
        # and forgetting others; "done" is the one judgement worth keeping.
        if user_criteria:
            plan.acceptance = list(user_criteria)
        if gaps:
            con.print(f"[replan] {len(gaps)} unmet criterion(s) -> new plan")
        for i, st in enumerate(plan.steps):
            con.print(f"  {i + 1}. {st.title}  ({st.target_file})")
        if plan.acceptance:
            con.print("  acceptance:")
            for a in plan.acceptance:
                con.print(f"    - {a.symbol} in {a.file}")
        # Gate only the FIRST plan: a replan is bounded, targets criteria the
        # human already approved, and pausing on each round defeats the point.
        if not gaps:
            verdict = tools.human_review.invoke(
                {
                    "gate": "plan-approval",
                    "summary": f"{len(plan.steps)} steps for: {goal}",
                    "action": "; ".join(st.title for st in plan.steps),
                }
            )
            con.print(f"[gate] {verdict}")
            approved["ok"] = not verdict.startswith("REJECTED")
        return plan

    def _propose(step, ctx_text, feedback, temperature, *, step_index=None, attempt=None):
        text = ctx_text if not catalog else f"{ctx_text}\n\n# Available skills\n{catalog}"
        # step_index/attempt are pure telemetry, and the only path that carries
        # them into calls.jsonl — without them eval/report.py cannot say which
        # step a call belonged to or how deep the repair went.
        where = {"step_index": step_index, "attempt": attempt}
        # Two different jobs, two different prompts: copying an anchor out of an
        # existing file, versus writing a file from nothing. Sharing one prompt
        # for both is what produced 0/4 valid new files.
        if not (workspace / step.target_file).exists():
            return propose_new_file(step, text, feedback, temperature, **where)
        return propose(step, text, feedback, temperature, **where)

    def _on_step(i, res):
        status = "ok" if res.ok else "FAILED"
        con.print(
            f"[step {i + 1}] {status} — {res.model_calls} calls, "
            f"{res.repair_attempts} repairs, anchors={res.anchor_kinds}"
        )
        if not res.ok:
            con.print(f"  {res.final_error[:400]}")

    scorer = None
    if getattr(args, "optimize", ""):
        scorer = crew.load_scorer(args.optimize)
        con.print(
            f"[optimize] scoring every candidate with {args.optimize} "
            f"(lower is better); each step spends {args.n_candidates} call(s)"
        )

    # The budget is process-global (see budget.py), so it has to be cleared on
    # EVERY exit from the work — not just the happy one. `harvest --run` calls
    # this function once per task in a loop: a rejected plan gate returning
    # early, or anything raising, used to leave the finished task's budget
    # active, and the next task started already partly spent.
    try:
        result = crew.run_goal(
            args.goal,
            workspace,
            _plan_fn,
            _propose,
            gates=None if not args.no_gates else [],
            max_replans=args.max_replans,
            snapshot=snap,
            on_step=_on_step,
            n_candidates=args.n_candidates,
            scorer=scorer,
        )
    finally:
        budget_mod.set_active(None)

    if not approved["ok"]:
        return 2

    if result.gave_up:
        con.print(f"[budget] GAVE UP — {result.gave_up}")
    if result.unmet:
        con.print(
            f"[acceptance] {len(result.unmet)} criterion(s) NOT met after {result.rounds} round(s):"
        )
        for u in result.unmet:
            con.print(f"  - {u}")

    ok = result.ok
    if ok:
        con.print(
            tools.human_review.invoke(
                {
                    "gate": "pre-ship",
                    "summary": f"{len(result.steps)} steps passed, all criteria met.",
                    "action": args.goal,
                }
            )
        )
    if result.plan_fixes:
        con.print(f"[plan] {len(result.plan_fixes)} plan fix(es):")
        for d in result.plan_fixes:
            con.print(f"  - {d}")
    con.print(
        f"[done] {sum(r.ok for r in result.steps)}/{len(result.steps)} steps, "
        f"{result.rounds} plan round(s), "
        f"{sum(r.model_calls for r in result.steps)} model calls"
        f" | budget: {task_budget.summary()}"
    )

    from . import failmem

    failmem.record(
        failmem.Attempt(
            goal=args.goal,
            target_file=(result.steps[0].step.target_file if result.steps else ""),
            outcome="solved" if ok else ("gave_up" if result.gave_up else "unmet"),
            detail=result.gave_up or ("; ".join(result.unmet) if result.unmet else ""),
        )
    )
    if getattr(args, "_collect", None) is not None:
        args._collect.append(result)
    return 0 if ok else 1


def cmd_harvest(args) -> int:
    """Read work off the repo's own failing signals."""
    from . import harvest as hv

    con = _console()
    problems: list[tuple[str, str]] = []
    tasks = hv.harvest(
        args.workspace,
        args.sources.split(",") if args.sources else None,
        args.tests,
        on_problem=lambda source, reason: problems.append((source, reason)),
    )

    # Before the verdict, never after: a source that could not run is not a
    # source that found nothing, and printing "all green" over it is how a
    # harvest reports a repo it never actually inspected.
    for source, reason in problems:
        con.print(f"[harvest] {source}: COULD NOT RUN — {reason}")

    if not tasks:
        if problems:
            con.print(
                f"[harvest] no tasks, but {len(problems)} source(s) could not run. "
                f"This is NOT a green repo — it is a repo that was not fully checked."
            )
            return 5
        con.print("[harvest] nothing to do — the repo's signals are all green")
        return 0

    con.print(f"[harvest] {len(tasks)} task(s) from the repo:")
    for i, t in enumerate(tasks, 1):
        con.print(f"\n  {i}. [{t.source}] {t.goal.splitlines()[0][:88]}")
        con.print(f"     fix in:   {t.target_file}")
        con.print(f"     evidence: {t.evidence.splitlines()[0][:88]}")
        con.print(f"     oracle:   {len(t.acceptance)} executable criterion(s)")

    if args.json:
        Path(args.json).write_text(hv.dump(tasks), encoding="utf-8")
        con.print(f"\n[harvest] written to {args.json}")

    if not args.run:
        con.print("\n[harvest] pass --run to work through them")
        return 0

    # Preflight is skipped on purpose: the repo IS red, and that red is the
    # work. Refusing to start here would make harvest useless by construction.
    delivery = None
    if args.deliver or args.pr:
        from . import deliver as dl

        delivery = dl.Delivery(args.workspace, f"harvest-{tasks[0].source}")
        ok, msg = delivery.start()
        if not ok:
            con.print(f"[deliver] cannot start: {msg}")
            return 4
        con.print(f"[deliver] working on branch {msg}")

    # Everything failing right now. A task may leave these alone; it may not
    # add to them. Without this, task 2 can undo task 1 and both report success.
    baseline = hv.failing_tests(args.workspace, args.tests)
    if baseline:
        con.print(f"[harvest] baseline: {len(baseline)} test(s) already failing")

    sections: list[dict] = []
    done = 0
    for i, t in enumerate(tasks[: args.limit or len(tasks)], 1):
        con.print(f"\n=== task {i}: [{t.source}] {t.target_file} ===")
        collected: list = []
        rc = cmd_run(
            argparse.Namespace(
                _collect=collected,
                goal=t.goal,
                workspace=args.workspace,
                interactive=False,
                no_gates=True,  # the repo is red; its own criterion is the gate
                snapshot=args.snapshot,
                n_candidates=args.n_candidates,
                max_replans=args.max_replans,
                accept="",
                skip_preflight=True,
                max_calls=args.max_calls,
                max_seconds=args.max_seconds,
                max_tokens=args.max_tokens,
                _criteria=t.acceptance,
            )
        )
        regressed = hv.regressions(args.workspace, baseline, args.tests) if rc == 0 else set()
        if regressed:
            con.print(f"  REGRESSION: {len(regressed)} test(s) newly broken by this task:")
            for r in sorted(regressed)[:5]:
                con.print(f"    - {r}")
            con.print("  reverting this task")
            if delivery:
                delivery.discard_uncommitted()
            rc = 1

        done += rc == 0
        con.print(f"=== task {i}: {'SOLVED' if rc == 0 else 'not solved'} ===")

        res = collected[0] if collected else None
        sections.append(
            {
                "solved": rc == 0,
                "goal_line": t.goal.splitlines()[0],
                "source": t.source,
                "target_file": t.target_file,
                "evidence": t.evidence,
                "unmet": (list(res.unmet) if res else [])
                + [f"regressed {r}" for r in sorted(regressed)],
                "steps": len(res.steps) if res else 0,
                "model_calls": sum(r.model_calls for r in res.steps) if res else 0,
                "repairs": sum(r.repair_attempts for r in res.steps) if res else 0,
                "rounds": res.rounds if res else 0,
                "anchors": [k for r in (res.steps if res else []) for k in r.anchor_kinds],
                "plan_fixes": list(res.plan_fixes) if res else [],
                "gave_up": res.gave_up if res else "",
            }
        )
        if delivery:
            if rc == 0:
                delivery.commit(
                    f"{t.goal.splitlines()[0][:68]}",
                    f"Source: {t.source}\nEvidence: {t.evidence.splitlines()[0][:200]}\n\n"
                    f"Verified by an executable criterion, not by assertion.",
                )
            else:
                # Failed work is reported, never committed.
                delivery.discard_uncommitted()

    total = min(len(tasks), args.limit or len(tasks))
    con.print(f"\n[harvest] {done}/{total} solved")

    if delivery:
        title = f"nanoloop: {done}/{total} harvested task(s)"
        report = delivery.write_report(title, sections)
        delivery.commit("Add nanoloop run report")
        con.print(f"[deliver] {len(delivery.result.commits)} commit(s) on {delivery.branch}")
        con.print(f"[deliver] report at {delivery.result.report_path}")
        if args.pr:
            ok, msg = delivery.open_pr(title, report)
            con.print(f"[deliver] {'PR: ' + msg if ok else 'PR failed: ' + msg}")
    return 0 if done else 1


def cli(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="gemma4nanoloop")
    sub = p.add_subparsers(dest="cmd", required=True)

    sp = sub.add_parser("probe", help="Phase 0: check endpoints answer")
    sp.add_argument("--backend", default="ollama", help="comma-separated: ollama,litert")
    sp.set_defaults(fn=cmd_probe)

    sv = sub.add_parser("verify-ctx", help="Phase 0: prove num_ctx is honored")
    sv.add_argument("--num-ctx", type=int, default=2048, dest="num_ctx")
    sv.set_defaults(fn=cmd_verify_ctx)

    sm = sub.add_parser("map", help="print the repo map")
    sm.add_argument("--workspace", default="./workspace")
    sm.set_defaults(fn=cmd_map)

    spl = sub.add_parser("plan", help="Phase 1: plan only, no edits")
    spl.add_argument("goal")
    spl.add_argument("--workspace", default="./workspace")
    spl.set_defaults(fn=cmd_plan)

    sr = sub.add_parser("run", help="full loop")
    sr.add_argument("goal")
    sr.add_argument("--workspace", default="./workspace")
    sr.add_argument("--interactive", action="store_true", help="enable HITL gates")
    sr.add_argument("--no-gates", action="store_true")
    sr.add_argument("--snapshot", default="copy", choices=["copy", "git"])
    sr.add_argument(
        "--n-candidates", type=int, default=crew.DEFAULT_N_CANDIDATES, dest="n_candidates"
    )
    sr.add_argument(
        "--skip-preflight",
        action="store_true",
        dest="skip_preflight",
        help="start even if the repo does not pass its own gates",
    )
    sr.add_argument(
        "--accept",
        default="",
        metavar="FILE",
        help="JSON file of acceptance criteria you wrote; overrides the planner's",
    )
    sr.add_argument(
        "--max-replans",
        type=int,
        default=crew.MAX_REPLANS,
        dest="max_replans",
        help="extra planning rounds when acceptance criteria are unmet",
    )
    sr.add_argument(
        "--optimize",
        default="",
        metavar="FILE",
        help="a Python file defining score(workspace) -> float|None (lower is "
        "better). Scores every candidate and keeps the best, instead of "
        "stopping at the first that passes. Always spends --n-candidates calls.",
    )
    sr.add_argument(
        "--max-calls",
        type=int,
        default=0,
        dest="max_calls",
        help="stop the task after N model calls (0 = no limit)",
    )
    sr.add_argument(
        "--max-seconds",
        type=float,
        default=0.0,
        dest="max_seconds",
        help="stop the task after N seconds (0 = no limit)",
    )
    sr.add_argument(
        "--max-tokens",
        type=int,
        default=0,
        dest="max_tokens",
        help="stop the task after N tokens (0 = no limit)",
    )
    sr.set_defaults(fn=cmd_run)

    sh = sub.add_parser("harvest", help="read work off the repo's failing signals")
    sh.add_argument("--workspace", default="./workspace")
    sh.add_argument("--sources", default="", help="comma-separated: pytest,mypy,ruff")
    sh.add_argument(
        "--tests",
        default="",
        metavar="PATH",
        help="scope pytest to this path — required on any real repo",
    )
    sh.add_argument("--json", default="", metavar="FILE", help="write the tasks as JSON")
    sh.add_argument("--run", action="store_true", help="work through the tasks")
    sh.add_argument("--limit", type=int, default=0, help="stop after N tasks")
    sh.add_argument("--snapshot", default="copy", choices=["copy", "git"])
    sh.add_argument(
        "--n-candidates", type=int, default=crew.DEFAULT_N_CANDIDATES, dest="n_candidates"
    )
    sh.add_argument("--max-replans", type=int, default=crew.MAX_REPLANS, dest="max_replans")
    sh.add_argument(
        "--max-calls",
        type=int,
        default=0,
        dest="max_calls",
        help="stop the task after N model calls (0 = no limit)",
    )
    sh.add_argument(
        "--max-seconds",
        type=float,
        default=0.0,
        dest="max_seconds",
        help="stop the task after N seconds (0 = no limit)",
    )
    sh.add_argument(
        "--max-tokens",
        type=int,
        default=0,
        dest="max_tokens",
        help="stop the task after N tokens (0 = no limit)",
    )
    sh.add_argument(
        "--deliver",
        action="store_true",
        help="work on a branch, one commit per solved task, plus a report",
    )
    sh.add_argument(
        "--pr",
        action="store_true",
        help="push the branch and open a pull request (implies --deliver)",
    )
    sh.set_defaults(fn=cmd_harvest)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(cli())
