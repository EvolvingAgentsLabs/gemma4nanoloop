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
"""

from __future__ import annotations

import argparse
import json
from collections import Counter
from pathlib import Path

from nanoloop import anchors, calllog, crew
from nanoloop.proposer import propose


def load_fixtures(path: Path) -> list[dict]:
    return [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="eval/anchors.jsonl")
    ap.add_argument("--repo", default="eval/fixture-repo")
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
            if args.fuzzy and kind is anchors.Match.NOT_FOUND:
                if len(anchors.find_fuzzy(contents, edit.anchor)) == 1:
                    fuzzy_recovered += 1

    total = sum(counts.values()) or 1
    print("\n=== Phase 2: anchor-hit ===")
    print(f"fixtures        {total}")
    for k in ("exact", "fuzzy", "not_found", "ambiguous", "no_valid_edit", "missing_file"):
        if counts[k]:
            print(f"{k:<15} {counts[k]:>4}  {100 * counts[k] / total:5.1f}%")

    exact_rate = 100 * counts["exact"] / total
    print(f"\nEXACT-HIT RATE  {exact_rate:.1f}%")
    if args.fuzzy:
        with_fuzzy = 100 * (counts["exact"] + fuzzy_recovered) / total
        print(f"with fuzzy      {with_fuzzy:.1f}%  (+{fuzzy_recovered} recovered)")

    if exact_rate >= 90:
        print("VERDICT: >=90% — proceed (PLAN.md §4 Phase 2).")
    elif exact_rate >= 85:
        print("VERDICT: 85-90% — enable NANOLOOP_FUZZY=1 and re-measure.")
    else:
        print("VERDICT: <85% — STOP AND REPORT. Do not fall back to write_file (§6).")

    if failures:
        Path("eval/anchor_failures.json").write_text(
            json.dumps(failures, indent=2), encoding="utf-8"
        )
        print(f"\n{len(failures)} failures written to eval/anchor_failures.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
