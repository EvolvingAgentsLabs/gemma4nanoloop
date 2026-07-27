"""G3: how stable is the planner? Same goal, N times.

The instability was only ever noticed by accident — the same goal produced 1, 2,
4 and 5 steps across a session, and one run emitted two identical steps. Nothing
measured it, so nothing could tell whether a change made it better or worse.

Plans only. No edits, no gates: this measures the planner in isolation.

    python -m eval.run_variance --goal "..." --runs 10 --repo eval/fixture-repo
"""

from __future__ import annotations

import argparse
import statistics as st
from collections import Counter
from pathlib import Path

from nanoloop import calllog, crew, repomap
from nanoloop.planner import propose_plan

DEFAULT_GOAL = (
    "Add a by_tag(tag) method to the todo Store returning items carrying that "
    "tag, and make Store.add accept an optional tags list"
)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--goal", default=DEFAULT_GOAL)
    ap.add_argument("--repo", default="eval/fixture-repo")
    ap.add_argument("--runs", type=int, default=10)
    args = ap.parse_args()

    calllog.reset_clock()
    rmap = repomap.build(Path(args.repo).resolve())

    raw_counts, clean_counts, dropped_total = [], [], 0
    files_seen: Counter[str] = Counter()
    acc_counts, checked = [], 0

    for i in range(args.runs):
        try:
            plan = propose_plan(args.goal, rmap)
        except Exception as e:  # noqa: BLE001
            print(f"  run {i + 1}: FAILED — {type(e).__name__}: {e}")
            continue
        cleaned, dropped = crew.normalize_plan(plan)
        raw_counts.append(len(plan.steps))
        clean_counts.append(len(cleaned.steps))
        dropped_total += len(dropped)
        acc_counts.append(len(plan.acceptance))
        checked += sum(1 for a in plan.acceptance if a.check)
        for s in cleaned.steps:
            files_seen[s.target_file] += 1
        print(
            f"  run {i + 1:>2}: {len(plan.steps)} steps"
            f"{f' -> {len(cleaned.steps)} after dedup' if dropped else ''}"
            f", {len(plan.acceptance)} criteria"
        )

    if not raw_counts:
        print("no successful runs")
        return 1

    n = len(raw_counts)
    print(f"\n=== planner variance over {n} runs ===")
    for label, data in (("steps (raw)", raw_counts), ("steps (deduped)", clean_counts)):
        spread = f"{min(data)}-{max(data)}"
        sd = st.pstdev(data)
        print(
            f"  {label:<17} median {st.median(data):>4.1f}  range {spread:<6} "
            f"sd {sd:.2f}  {dict(sorted(Counter(data).items()))}"
        )
    print(f"  redundant steps dropped   {dropped_total} across {n} runs")
    print(f"  acceptance criteria       median {st.median(acc_counts):.1f}")
    total_acc = sum(acc_counts)
    print(
        f"  criteria WITH a check     {checked}/{total_acc}"
        f"{f' ({100 * checked / total_acc:.0f}%)' if total_acc else ''}"
    )
    print("\n  target files chosen:")
    for f, c in files_seen.most_common(8):
        print(f"    {c:>3}x  {f}")

    # A planner that cannot agree with itself on the shape of the work is the
    # thing to fix; the loop downstream can only compensate for omissions.
    sd = st.pstdev(clean_counts)
    print(
        f"\n  VERDICT: {'stable' if sd < 1.0 else 'UNSTABLE'} "
        f"(sd {sd:.2f} steps after dedup; <1.0 is stable)"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
