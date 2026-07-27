"""Phase 6 measurement: semantic recall vs the keyword baseline.

Accept when semantic beats keyword on the labeled query set (PLAN.md §4 Phase 6).
Both retrievers run over the SAME corpus (`recall._corpus()`) in the same
process, so the only variable is the retrieval method.

SWEEPS k RATHER THAN REPORTING ONE VALUE. PLAN.md specifies recall@5, but @5
over a small corpus is SATURATED: with 8 notes, k=5 retrieves 62% of everything
and both methods score 1.000 — a tie that reads as "semantic failed to win"
when it actually means "the metric cannot discriminate". The sweep makes that
visible instead of letting a single number mislead, and the verdict is taken
from the smallest k that still separates the two.

    python -m eval.run_recall --queries eval/recall.jsonl [--reindex]
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nanoloop import memory, recall

KS = (1, 2, 3, 5)


def recall_at_k(hits: list[str], relevant: list[str], k: int) -> float:
    if not relevant:
        return 0.0
    top = hits[:k]
    return sum(1 for r in relevant if r in top) / len(relevant)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="eval/recall.jsonl")
    ap.add_argument("--k", type=int, default=0, help="report a single k instead of the sweep")
    ap.add_argument("--reindex", action="store_true")
    args = ap.parse_args()

    if args.reindex:
        print("building index...")
        recall.build_index()

    index = recall.load_index()
    if not index:
        print("empty index — run with --reindex (and `ollama pull embeddinggemma`)")
        return 1

    queries = [
        json.loads(ln)
        for ln in Path(args.queries).read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]
    corpus_n = len({c.note for c in index})
    ks = (args.k,) if args.k else KS

    # Retrieve once at max(k); every k is a prefix of the same ranking.
    kmax = max(ks)
    rows = []
    for q in queries:
        sem = [r["note"] for r in recall.search(q["query"], kmax, index=index)]
        kw = [n.name for n in memory.search(q["query"], kmax)]
        rows.append((q, sem, kw))

    print(f"\ncorpus: {corpus_n} notes, {len(index)} chunks | queries: {len(queries)}")
    print(f"\n{'':<44}", end="")
    for k in ks:
        print(f"{'@' + str(k):>16}", end="")
    print(f"\n{'query':<44}", end="")
    for _ in ks:
        print(f"{'kw':>8}{'sem':>8}", end="")
    print()

    totals = {k: [0.0, 0.0] for k in ks}
    for q, sem, kw in rows:
        print(f"{q['query'][:42]:<44}", end="")
        for k in ks:
            s = recall_at_k(sem, q["relevant"], k)
            w = recall_at_k(kw, q["relevant"], k)
            totals[k][0] += w
            totals[k][1] += s
            print(f"{w:>8.2f}{s:>8.2f}", end="")
        print()

    n = len(queries)
    print(f"\n{'MEAN':<44}", end="")
    for k in ks:
        print(f"{totals[k][0] / n:>8.2f}{totals[k][1] / n:>8.2f}", end="")
    print("\n")

    # Verdict from the smallest k that still separates the methods. A tie at
    # large k over a small corpus is saturation, not a failure to improve.
    verdict_k, saturated = None, []
    for k in ks:
        kw_avg, sem_avg = totals[k][0] / n, totals[k][1] / n
        if kw_avg == sem_avg == 1.0:
            saturated.append(k)
        elif verdict_k is None:
            verdict_k = k

    for k in saturated:
        print(
            f"  note: @{k} is SATURATED (both 1.000) — k={k} over {corpus_n} notes "
            f"retrieves {100 * k / corpus_n:.0f}% of the corpus; it cannot discriminate."
        )

    if verdict_k is None:
        print("\nVERDICT: INCONCLUSIVE — every k saturated. Grow the corpus or shrink k.")
        return 1

    kw_avg, sem_avg = totals[verdict_k][0] / n, totals[verdict_k][1] / n
    better = sem_avg > kw_avg
    print(
        f"\nrecall@{verdict_k} (smallest discriminating k)  "
        f"keyword {kw_avg:.3f}   semantic {sem_avg:.3f}"
    )
    print(f"VERDICT: {'PASS' if better else 'FAIL'} — semantic must beat keyword")

    if corpus_n < 2 * max(ks):
        print(
            f"\n  CAVEAT: {corpus_n} notes is a small corpus for k up to {max(ks)}. "
            f"PLAN.md asks for 30 labeled queries; this set has {len(queries)}."
        )
    return 0 if better else 1


if __name__ == "__main__":
    raise SystemExit(main())
