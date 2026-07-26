"""Render PLAN.md §5's metrics table from the JSONL call log.

    python -m eval.report --log calls.jsonl

Every metric here is derived from `calls.jsonl` alone. That is deliberate: the
log is the regression suite (PLAN.md §4 Phase 0.4), so anything that cannot be
recovered from it is not measurable across a runtime change.
"""

from __future__ import annotations

import argparse
import statistics
from collections import Counter, defaultdict
from pathlib import Path

from nanoloop import calllog


def _pct(n: int, d: int) -> str:
    return f"{100 * n / d:.1f}%" if d else "n/a"


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--log", default="calls.jsonl")
    args = ap.parse_args()

    rows = calllog.read(Path(args.log))
    if not rows:
        print(f"no records in {args.log}")
        return 1

    live = [r for r in rows if not r["phase"].endswith(".parsed")]
    by_phase: dict[str, list[dict]] = defaultdict(list)
    for r in live:
        by_phase[r["phase"]].append(r)

    print(f"\n=== call log: {len(live)} model calls ===\n")
    print(
        f"{'phase':<12} {'calls':>6} {'p50 ms':>9} {'p90 ms':>9} {'prompt tok':>11} {'errors':>7}"
    )
    for phase, rs in sorted(by_phase.items()):
        lat = sorted(r["latency_ms"] for r in rs)
        toks = [r["prompt_tokens"] for r in rs if r.get("prompt_tokens")]
        errs = sum(1 for r in rs if r.get("error"))
        p50 = statistics.median(lat) if lat else 0
        p90 = lat[int(len(lat) * 0.9)] if lat else 0
        print(
            f"{phase:<12} {len(rs):>6} {p50:>9.0f} {p90:>9.0f} "
            f"{(statistics.median(toks) if toks else 0):>11.0f} {errs:>7}"
        )

    # --- model calls per step + repair depth (Phase 3) ---
    steps: dict[int, list[dict]] = defaultdict(list)
    for r in live:
        if r.get("step_index") is not None:
            steps[r["step_index"]].append(r)
    if steps:
        per_step = [len(v) for v in steps.values()]
        depths = [max((x.get("attempt") or 0) for x in v) for v in steps.values()]
        print(f"\nsteps observed          {len(steps)}")
        print(
            f"model calls per step    median {statistics.median(per_step):.1f}  max {max(per_step)}"
        )
        print(f"repair depth            median {statistics.median(depths):.1f}  max {max(depths)}")
        print(f"first-attempt success   {_pct(sum(1 for d in depths if d == 0), len(depths))}")
        print("\nrepair-depth distribution")
        for d, n in sorted(Counter(depths).items()):
            print(f"  depth {d}: {'#' * n} ({n})")

    # --- throttling curve (Phase 4) ---
    # The headline number for a fanless Air. PLAN.md §4 Phase 4: if step 30 is
    # >2x step 1, cut n_candidates or add cooldowns.
    if len(steps) >= 4:
        idx = sorted(steps)
        med = {i: statistics.median([r["latency_ms"] for r in steps[i]]) for i in idx}
        print("\n=== throttling curve (median latency per step) ===")
        peak = max(med.values()) or 1
        for i in idx:
            bar = "█" * max(1, int(40 * med[i] / peak))
            print(f"  step {i:>3} {med[i]:>7.0f}ms {bar}")
        first = statistics.median([med[i] for i in idx[: max(1, len(idx) // 10)]])
        last = statistics.median([med[i] for i in idx[-max(1, len(idx) // 10) :]])
        ratio = last / first if first else 0
        print(f"\n  early median {first:.0f}ms -> late median {last:.0f}ms = {ratio:.2f}x")
        if ratio > 2:
            print("  THROTTLING: >2x. Cut n_candidates to 1 or add cooldowns (PLAN.md §4 Phase 4).")

    # --- parse reliability ---
    parsed = [r for r in rows if r["phase"].endswith(".parsed")]
    if live:
        print(
            f"\nstructured-output parse  {_pct(len(parsed), len(live))} ({len(parsed)}/{len(live)})"
        )

    total_s = max((r["wall_clock_since_start"] for r in rows), default=0)
    print(f"wall clock               {total_s:.1f}s")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
