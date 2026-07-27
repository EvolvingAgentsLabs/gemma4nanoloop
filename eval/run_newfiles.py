"""G4: how good is whole-file generation, really?

Anchored edits measure ~100%. Writing a file from nothing has been the visible
weak point since the first multi-step run (0/4 valid, every one with unbalanced
brackets) but it has never had a number, so every change to the prompt has been
guesswork.

Reports a FUNNEL rather than a pass rate, because "it failed" is not actionable
and "it failed at the import step" is:

    parsed      the reply was a valid NewFile
    syntax      ast.parse accepts it            <- where it used to die
    lint        ruff check passes
    imports     the module actually imports
    defines     it contains the symbol it was asked for

Each stage is a superset of the failures below it, so the biggest drop names the
thing worth fixing.

    python -m eval.run_newfiles --repo eval/fixture-repo
"""

from __future__ import annotations

import argparse
import ast
import json
import shutil
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

from nanoloop import calllog, crew, repomap
from nanoloop.proposer import propose_new_file

STAGES = ["parsed", "syntax", "lint", "imports", "defines"]


def load(path: Path) -> list[dict]:
    return [
        json.loads(ln)
        for ln in path.read_text(encoding="utf-8").splitlines()
        if ln.strip() and not ln.startswith("#")
    ]


def _check_one(repo: Path, fx: dict, content: str, autofix: bool) -> tuple[str, str]:
    """Run one generated file through the funnel. Returns (deepest_stage, why).

    `autofix` decides whether this measures the RAW model output or what the
    pipeline actually produces. `crew.autofix` (ruff --fix + format) runs after
    every edit in build_step, so measuring without it reports a weakness the
    system does not really have — and the first run of this harness did exactly
    that, blaming the model for unsorted imports a tool fixes every time.
    """
    target = repo / fx["target_file"]
    try:
        ast.parse(content)
    except SyntaxError as e:
        return "parsed", f"line {e.lineno}: {e.msg}"

    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(content, encoding="utf-8")
    if autofix:
        crew.autofix(repo, fx["target_file"])

    ruff = str(Path(sys.executable).parent / "ruff")
    proc = subprocess.run(
        [ruff, "check", fx["target_file"]], cwd=repo, capture_output=True, text=True
    )
    if proc.returncode != 0:
        return "syntax", (proc.stdout or proc.stderr).strip().splitlines()[0][:120]

    module = fx["target_file"][:-3].replace("/", ".")
    proc = subprocess.run(
        [sys.executable, "-c", f"import {module}"], cwd=repo, capture_output=True, text=True
    )
    if proc.returncode != 0:
        tail = (proc.stderr or "").strip().splitlines()
        return "lint", tail[-1][:120] if tail else "import failed"

    wanted = fx.get("defines", "")
    if wanted and not crew.defines_symbol(repo, fx["target_file"], wanted):
        return "imports", f"does not define {wanted}"
    return "defines", ""


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fixtures", default="eval/newfiles.jsonl")
    ap.add_argument("--repo", default="eval/fixture-repo")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument(
        "--raw",
        action="store_true",
        help="measure the model's output WITHOUT the pipeline's autofix",
    )
    args = ap.parse_args()

    calllog.reset_clock()
    source = Path(args.repo).resolve()
    fixtures = load(Path(args.fixtures))
    if args.limit:
        fixtures = fixtures[: args.limit]

    reached: Counter[str] = Counter()
    failures: list[dict] = []

    for i, fx in enumerate(fixtures):
        # A pristine copy per fixture: a file left behind would change the repo
        # map for the next one, and the runs would stop being comparable.
        work = Path(tempfile.mkdtemp(prefix="newfiles-"))
        repo = work / "repo"
        shutil.copytree(source, repo, ignore=shutil.ignore_patterns("__pycache__", "*.pyc"))
        try:
            step = crew.Step(
                title=fx["title"],
                target_file=fx["target_file"],
                intent=fx["intent"],
                defines=fx.get("defines", ""),
            )
            ctx = crew.Ctx(goal=fx["intent"], step=step, repo_map=repomap.build(repo))
            try:
                edit = propose_new_file(step, ctx.render(), "", 0.0, step_index=i)
            except Exception as e:  # noqa: BLE001
                reached["none"] += 1
                failures.append(
                    {
                        "i": i,
                        "file": fx["target_file"],
                        "stage": "none",
                        "why": f"{type(e).__name__}: {e}"[:160],
                    }
                )
                continue

            stage, why = _check_one(repo, fx, edit.replacement, autofix=not args.raw)
            reached[stage] += 1
            if stage != "defines":
                failures.append({"i": i, "file": fx["target_file"], "stage": stage, "why": why})
            print(
                f"  {i + 1:>2}. {fx['target_file']:<28} reached: {stage}"
                f"{'' if stage == 'defines' else f'  ({why})'}"
            )
        finally:
            shutil.rmtree(work, ignore_errors=True)

    n = sum(reached.values()) or 1
    mode = "RAW model output" if args.raw else "as the pipeline produces it (with autofix)"
    print(f"\n=== G4: whole-file generation, {n} fixtures — {mode} ===")
    print("  stage      passed   cumulative")
    # Cumulative: a file that reached `imports` also cleared parse, syntax, lint.
    order = ["parsed", "syntax", "lint", "imports", "defines"]
    for idx, stage in enumerate(order):
        cleared = sum(reached[s] for s in order[idx:])
        print(f"  {stage:<10} {cleared:>5}   {100 * cleared / n:5.1f}%")

    ok = reached["defines"]
    print(f"\n  FULLY VALID: {ok}/{n} = {100 * ok / n:.1f}%")
    print("  (compare: anchored edits measure ~100% on eval/anchors.jsonl)")

    if failures:
        worst = Counter(f["stage"] for f in failures).most_common(1)[0]
        print(f"  biggest drop-off: {worst[0]} ({worst[1]} fixture(s)) — fix that first")
        Path("eval/newfile_failures.json").write_text(json.dumps(failures, indent=2))
        print("  detail in eval/newfile_failures.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
