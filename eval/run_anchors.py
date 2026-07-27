"""Phase 2 measurement: the anchor-hit rate.

PLAN.md §4 calls this "the phase that decides whether the project is viable" and
§7 lists it as open question #1. This harness answers it WITHOUT a working
planner — fixtures are hand-written (target_file, intent) pairs — so the kill
signal arrives before Phase 1 is built. See IMPLEMENTATION.md §1.

Reports the breakdown PLAN.md asks for:  exact / fuzzy / not_found / ambiguous

Thresholds from PLAN.md §4 Phase 2:
    >= 90%  proceed
    85-90%  turn on fuzzy anchoring, re-measure
    <  85%  STOP and report. Do not fall back to write_file (§6).

    python -m eval.run_anchors --fixtures eval/anchors.jsonl
    python -m eval.run_anchors --oracle          # A/B vs gemma-4-26b on AI Studio

THE ORACLE FLAG separates two failures that otherwise look identical:

    local fails, oracle passes  ->  12B ceiling. A bigger model is the fix.
    both fail                   ->  prompt/harness bug. A bigger model hides it.

That second row is the important one. A larger model developed against would
have silently papered over the thin repo map (IMPLEMENTATION §0a F7) — the bug
only surfaced because a 12B could not guess its way past it. The oracle is a
MEASUREMENT, not a development runtime.
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from nanoloop import anchors, calllog, crew, model_ollama
from nanoloop.proposer import propose


def load_fixtures(path: Path) -> list[dict]:
    return [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def measure(
    fixtures: list[dict], repo: Path, backend: str, fuzzy: bool
) -> tuple[Counter, int, list[dict]]:
    """Run every fixture through one backend. Returns (counts, fuzzy_recovered, failures)."""
    model_ollama.BACKEND = backend
    counts: Counter[str] = Counter()
    fuzzy_recovered = 0
    failures: list[dict] = []

    for i, fx in enumerate(fixtures):
        step = crew.Step(title=fx["title"], target_file=fx["target_file"], intent=fx["intent"])
        target = repo / step.target_file
        if not target.exists():
            counts["missing_file"] += 1
            continue
        contents = target.read_text(encoding="utf-8", errors="replace")
        ctx = crew.Ctx(goal=fx.get("goal", fx["intent"]), step=step, file_slice=contents)

        try:
            edit = propose(step, ctx.render(), "", 0.0, step_index=i)
        except Exception as e:  # noqa: BLE001
            counts["no_valid_edit"] += 1
            failures.append({"i": i, "title": step.title, "why": f"{type(e).__name__}: {e}"})
            continue

        # Exact classification first — that raw number is the diagnostic.
        kind = anchors.classify(contents, edit.anchor)
        counts[kind.value] += 1
        if kind is not anchors.Match.EXACT:
            failures.append(
                {"i": i, "title": step.title, "kind": kind.value, "anchor": edit.anchor[:200]}
            )
            if fuzzy and kind is anchors.Match.NOT_FOUND:
                if len(anchors.find_fuzzy(contents, edit.anchor)) == 1:
                    fuzzy_recovered += 1

    return counts, fuzzy_recovered, failures


def report(label: str, counts: Counter, fuzzy_recovered: int, fuzzy: bool) -> float:
    total = sum(counts.values()) or 1
    print(f"\n=== {label} ===")
    print(f"fixtures        {total}")
    for k in ("exact", "fuzzy", "not_found", "ambiguous", "no_valid_edit", "missing_file"):
        if counts[k]:
            print(f"{k:<15} {counts[k]:>4}  {100 * counts[k] / total:5.1f}%")
    rate = 100 * counts["exact"] / total
    print(f"EXACT-HIT RATE  {rate:.1f}%")
    if fuzzy and fuzzy_recovered:
        print(
            f"with fuzzy      {100 * (counts['exact'] + fuzzy_recovered) / total:.1f}%"
            f"  (+{fuzzy_recovered} recovered)"
        )
    return rate


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="eval/anchors.jsonl")
    ap.add_argument("--repo", default="eval/fixture-repo")
    ap.add_argument("--backend", default="ollama", help="ollama | litert | aistudio")
    ap.add_argument(
        "--oracle", action="store_true", help="also run aistudio and print the A/B comparison"
    )
    ap.add_argument(
        "--fuzzy",
        action="store_true",
        help="also report what fuzzy WOULD recover (measure exact first)",
    )
    ap.add_argument("--limit", type=int, default=0)
    args = ap.parse_args()

    calllog.reset_clock()
    repo = Path(args.repo).resolve()
    fixtures = load_fixtures(Path(args.fixtures))
    if args.limit:
        fixtures = fixtures[: args.limit]

    counts, recovered, failures = measure(fixtures, repo, args.backend, args.fuzzy)
    local_model = model_ollama.BACKENDS.get(args.backend, ("", "?"))[1]
    rate = report(f"{args.backend} ({local_model})", counts, recovered, args.fuzzy)

    if args.oracle:
        model_ollama.BACKEND = "aistudio"
        if not model_ollama.api_key():
            print("\n[oracle skipped] no API key — set GEMINI_API_KEY (e.g. in .env)")
        else:
            o_counts, o_recovered, o_failures = measure(fixtures, repo, "aistudio", args.fuzzy)
            o_model = model_ollama.BACKENDS["aistudio"][1]
            o_rate = report(f"oracle ({o_model})", o_counts, o_recovered, args.fuzzy)

            print("\n=== A/B ===")
            print(f"  local  {rate:5.1f}%      oracle {o_rate:5.1f}%")
            if rate < 90 <= o_rate:
                print("  DIAGNOSIS: the 12B is the ceiling here — the harness is fine.")
            elif rate < 90 and o_rate < 90:
                print("  DIAGNOSIS: BOTH fail — this is a prompt/harness bug, not model size.")
                print("  A bigger model would hide it, not fix it.")
            else:
                print("  DIAGNOSIS: local already clears the bar; the oracle adds nothing here.")
            failures = {"local": failures, "oracle": o_failures}

    if rate >= 90:
        print("\nVERDICT: >=90% — proceed (PLAN.md §4 Phase 2).")
    elif rate >= 85:
        print("\nVERDICT: 85-90% — enable NANOLOOP_FUZZY=1 and re-measure.")
    else:
        print("\nVERDICT: <85% — STOP AND REPORT. Do not fall back to write_file (§6).")

    if failures:
        Path("eval/anchor_failures.json").write_text(json.dumps(failures, indent=2))
        print("failures written to eval/anchor_failures.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
