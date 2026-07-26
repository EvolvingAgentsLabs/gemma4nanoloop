"""Phase 6 measurement: semantic recall@5 vs the keyword baseline.

Accept when semantic beats keyword on the labeled query set (PLAN.md §4 Phase 6).
Both retrievers run over the SAME corpus in the same process, so the only
variable is the retrieval method.

    python -m eval.run_recall --queries eval/recall.jsonl
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nanoloop import memory, recall


def recall_at_k(hits: list[str], relevant: list[str], k: int = 5) -> float:
    if not relevant:
        return 0.0
    top = hits[:k]
    return sum(1 for r in relevant if r in top) / len(relevant)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--queries", default="eval/recall.jsonl")
    ap.add_argument("--k", type=int, default=5)
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

    sem_scores, kw_scores = [], []
    print(f"\n{'query':<52} {'keyword':>8} {'semantic':>9}")
    for q in queries:
        sem = [r["note"] for r in recall.search(q["query"], args.k, index=index)]
        kw = [n.name for n in memory.search(q["query"], args.k)]
        s = recall_at_k(sem, q["relevant"], args.k)
        k_ = recall_at_k(kw, q["relevant"], args.k)
        sem_scores.append(s)
        kw_scores.append(k_)
        print(f"{q['query'][:50]:<52} {k_:>8.2f} {s:>9.2f}")

    sem_avg = sum(sem_scores) / len(sem_scores)
    kw_avg = sum(kw_scores) / len(kw_scores)
    print(f"\nrecall@{args.k}  keyword {kw_avg:.3f}   semantic {sem_avg:.3f}")
    better = sem_avg > kw_avg
    print(f"VERDICT: {'PASS' if better else 'FAIL'} — semantic must beat keyword")
    return 0 if better else 1


if __name__ == "__main__":
    raise SystemExit(main())
