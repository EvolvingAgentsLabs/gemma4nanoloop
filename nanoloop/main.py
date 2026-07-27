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

    con.print(f"[plan] {args.goal}")
    plan = propose_plan(args.goal, repomap.build(workspace))
    for i, s in enumerate(plan.steps):
        con.print(f"  {i + 1}. {s.title}  ({s.target_file})")

    verdict = tools.human_review.invoke(
        {
            "gate": "plan-approval",
            "summary": f"{len(plan.steps)} steps for: {args.goal}",
            "action": "; ".join(s.title for s in plan.steps),
        }
    )
    con.print(f"[gate] {verdict}")
    if verdict.startswith("REJECTED"):
        return 2

    from . import snapshot as snap_mod

    snap = snap_mod.make(workspace, args.snapshot)
    catalog = skills.catalog_text()

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
            f"[step {i + 1}/{len(plan.steps)}] {status} — "
            f"{res.model_calls} calls, {res.repair_attempts} repairs, "
            f"anchors={res.anchor_kinds}"
        )
        if not res.ok:
            con.print(f"  {res.final_error[:400]}")

    results = crew.run_plan(
        plan,
        args.goal,
        workspace,
        _propose,
        gates=None if not args.no_gates else [],
        snapshot=snap,
        on_step=_on_step,
        n_candidates=args.n_candidates,
    )

    ok = all(r.ok for r in results) and len(results) == len(plan.steps)
    if ok:
        con.print(
            tools.human_review.invoke(
                {
                    "gate": "pre-ship",
                    "summary": f"All {len(results)} steps passed gates.",
                    "action": args.goal,
                }
            )
        )
    con.print(
        f"[done] {sum(r.ok for r in results)}/{len(plan.steps)} steps, "
        f"{sum(r.model_calls for r in results)} model calls"
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
    sr.set_defaults(fn=cmd_run)

    args = p.parse_args(argv)
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(cli())
