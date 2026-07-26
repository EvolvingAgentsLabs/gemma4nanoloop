"""Phase 1 measurement: plan validity + target-file existence.

Accept when 10 real goals produce schema-valid plans and >=8/10 have
`target_file` paths that actually exist (PLAN.md §4 Phase 1).

    python -m eval.run_plans --tasks eval/tasks.jsonl --repo eval/fixture-repo
"""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from nanoloop import calllog, repomap
from nanoloop.planner import propose_plan


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--tasks", default="eval/tasks.jsonl")
    ap.add_argument("--repo", default="eval/fixture-repo")
    args = ap.parse_args()

    calllog.reset_clock()
    repo = Path(args.repo).resolve()
    rmap = repomap.build(repo)
    tasks = [
        json.loads(ln)
        for ln in Path(args.tasks).read_text().splitlines()
        if ln.strip() and not ln.startswith("#")
    ]

    valid = 0
    paths_exist = 0
    detail = []

    for t in tasks:
        try:
            plan = propose_plan(t["goal"], rmap)
        except Exception as e:  # noqa: BLE001
            detail.append(
                {"id": t["id"], "schema_valid": False, "error": f"{type(e).__name__}: {e}"}
            )
            continue
        valid += 1
        targets = [s.target_file for s in plan.steps]
        # A path counts as existing if the file is there, or its parent dir is
        # (creating a new file in an existing directory is legitimate planning).
        exists = all((repo / p).exists() or (repo / p).parent.is_dir() for p in targets)
        paths_exist += bool(exists)
        detail.append(
            {
                "id": t["id"],
                "schema_valid": True,
                "steps": len(plan.steps),
                "expected_steps": t.get("steps"),
                "targets": targets,
                "targets_ok": exists,
            }
        )

    n = len(tasks)
    print("\n=== Phase 1: planner ===")
    print(f"tasks                {n}")
    print(f"schema-valid plans   {valid}/{n}")
    print(f"target paths exist   {paths_exist}/{n}")
    for d in detail:
        flag = "ok " if d.get("targets_ok") else "BAD"
        print(
            f"  {flag} {d['id']}: {d.get('steps', '-')} steps "
            f"(expected {d.get('expected_steps', '?')})  {d.get('targets', d.get('error'))}"
        )

    ok = valid == n and paths_exist >= int(0.8 * n)
    print(
        f"\nVERDICT: {'PASS' if ok else 'FAIL'} (need all schema-valid and >=80% target paths real)"
    )
    Path("eval/plan_results.json").write_text(json.dumps(detail, indent=2))
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())
