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

    session = Session.create(args.goal) if hasattr(Session, "create") else None
    tools.set_session(session)
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

    from . import snapshot as snap_mod

    snap = snap_mod.make(workspace, args.snapshot)
    catalog = skills.catalog_text()
    approved = {"ok": True}

    user_criteria = _load_criteria(args.accept) if args.accept else []
    if user_criteria:
        con.print(
            f"[acceptance] {len(user_criteria)} criterion(s) supplied by you "
            f"(the planner's own are ignored)"
        )

    def _plan_fn(goal, repo_map, gaps):
        plan = propose_plan(goal, repo_map, gaps=gaps)
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

    def _propose(step, ctx_text, feedback, temperature):
        text = ctx_text if not catalog else f"{ctx_text}\n\n# Available skills\n{catalog}"
        # Two different jobs, two different prompts: copying an anchor out of an
        # existing file, versus writing a file from nothing. Sharing one prompt
        # for both is what produced 0/4 valid new files.
        if not (workspace / step.target_file).exists():
            return propose_new_file(step, text, feedback, temperature)
        return propose(step, text, feedback, temperature)

    def _on_step(i, res):
        status = "ok" if res.ok else "FAILED"
        con.print(
            f"[step {i + 1}] {status} — {res.model_calls} calls, "
            f"{res.repair_attempts} repairs, anchors={res.anchor_kinds}"
        )
        if not res.ok:
            con.print(f"  {res.final_error[:400]}")

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
    )

    if not approved["ok"]:
        return 2

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
    con.print(
        f"[done] {sum(r.ok for r in result.steps)}/{len(result.steps)} steps, "
        f"{result.rounds} plan round(s), "
        f"{sum(r.model_calls for r in result.steps)} model calls"
    )
    return 0 if ok else 1


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
    sr.set_defaults(fn=cmd_run)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(cli())
