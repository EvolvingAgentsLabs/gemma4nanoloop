"""Ship a branch and a report, not a mutated directory.

A crew that edits your working tree in place forces you to stand over it. A
crew that leaves a branch, a commit per solved task, and a written account of
what it did and what it could not, lets you review whenever you like. Reviewing
a diff is cheap; supervising a process is not.

THE REPORT IS GENERATED FROM DATA, NEVER NARRATED BY THE MODEL. Everything in
it — steps, repairs, anchor kinds, criteria met and unmet, plan repairs, call
counts, wall clock — is already recorded by `crew` and `calllog`. Asking the
model to summarise its own work would reintroduce exactly the unverified
opinion that D3 removes, and it would be the one part of the output nothing
checks.

GIVING UP IS A DELIVERABLE. A task that ends with "I could not, here is the
exact error and what I tried" is worth more than one that quietly ships doubtful
code. Failed work is reported and left uncommitted.
"""

from __future__ import annotations

import re
import subprocess
from dataclasses import dataclass, field
from pathlib import Path


def _git(workspace: Path, *args: str, timeout: int = 60) -> tuple[int, str]:
    try:
        p = subprocess.run(
            ["git", *args], cwd=str(workspace), capture_output=True, text=True, timeout=timeout
        )
        return p.returncode, (p.stdout or "") + (p.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, str(e)


# Build artefacts, not anyone's work. Harvest itself creates several of these
# on its way in — it runs pytest to find failing tests — so treating them as a
# dirty tree would make --deliver refuse to start on exactly the repos it is
# meant for.
EPHEMERAL = re.compile(
    r"(__pycache__/|\.pyc$|\.pytest_cache/|\.ruff_cache/|\.mypy_cache/"
    r"|NANOLOOP-REPORT\.md$|_acceptance_\d+\.py$)"
)


def _real_changes(status_output: str) -> list[str]:
    """Paths from `git status --porcelain` that represent actual work."""
    out = []
    for line in status_output.splitlines():
        path = line[3:].strip().strip('"')
        if path and not EPHEMERAL.search(path):
            out.append(path)
    return out


def is_git_repo(workspace: Path | str) -> bool:
    return _git(Path(workspace), "rev-parse", "--git-dir")[0] == 0


def slugify(text: str, limit: int = 40) -> str:
    s = re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")
    return (s[:limit].rstrip("-")) or "work"


@dataclass
class Delivered:
    branch: str = ""
    base: str = ""
    commits: list[str] = field(default_factory=list)
    report_path: str = ""
    pr_url: str = ""
    notes: list[str] = field(default_factory=list)


class Delivery:
    """A branch that collects the crew's work, one commit per solved task."""

    def __init__(self, workspace: Path | str, name: str):
        self.workspace = Path(workspace)
        self.branch = f"nanoloop/{slugify(name)}"
        self.result = Delivered(branch=self.branch)

    # --- branch lifecycle ---------------------------------------------------

    def start(self) -> tuple[bool, str]:
        """Create the working branch. Refuses on a dirty tree.

        A dirty tree means the crew's commits would sweep up changes that are
        not its own, and the diff you review would no longer be its work.
        """
        if not is_git_repo(self.workspace):
            return False, "not a git repository — the crew delivers branches, so init one first"

        code, out = _git(self.workspace, "status", "--porcelain")
        if code != 0:
            return False, f"git status failed: {out}"
        dirty = _real_changes(out)
        if dirty:
            listed = ", ".join(dirty[:5]) + ("…" if len(dirty) > 5 else "")
            return False, (
                f"the working tree has uncommitted changes ({listed}). Commit or "
                f"stash them first, or the crew's diff would include work that is "
                f"not its own"
            )

        self.result.base = _git(self.workspace, "rev-parse", "--abbrev-ref", "HEAD")[1].strip()
        code, out = _git(self.workspace, "checkout", "-b", self.branch)
        if code != 0:  # branch exists: reuse it rather than inventing a suffix
            code, out = _git(self.workspace, "checkout", self.branch)
            if code != 0:
                return False, f"could not switch to {self.branch}: {out}"
            self.result.notes.append(f"reused existing branch {self.branch}")
        return True, self.branch

    def commit(self, subject: str, body: str = "") -> bool:
        """Commit whatever the last task produced. False if nothing changed."""
        if not _real_changes(_git(self.workspace, "status", "--porcelain")[1]):
            return False
        # `add -A` would sweep in __pycache__ and friends, and the diff a human
        # reviews would be mostly bytecode. Exclude them explicitly.
        _git(
            self.workspace,
            "add",
            "-A",
            "--",
            ".",
            ":(exclude)**/__pycache__/**",
            ":(exclude)**/*.pyc",
            ":(exclude)**/.pytest_cache/**",
            ":(exclude)**/.ruff_cache/**",
            ":(exclude)**/.mypy_cache/**",
            ":(exclude)_acceptance_*.py",
        )
        message = f"{subject}\n\n{body}".strip() if body else subject
        code, _ = _git(self.workspace, "commit", "-m", message)
        if code != 0:
            return False
        sha = _git(self.workspace, "rev-parse", "--short", "HEAD")[1].strip()
        self.result.commits.append(f"{sha} {subject}")
        return True

    def discard_uncommitted(self) -> None:
        """Throw away a failed task's leftovers so the next one starts clean."""
        _git(self.workspace, "checkout", "--", ".")
        _git(self.workspace, "clean", "-fd")

    # --- the report ---------------------------------------------------------

    def write_report(
        self, title: str, sections: list[dict], path: str = "NANOLOOP-REPORT.md"
    ) -> str:
        """Render the run from recorded data. No model involved."""
        out = [f"# {title}", ""]
        solved = sum(1 for s in sections if s["solved"])
        out.append(f"**{solved}/{len(sections)} tasks solved** on branch `{self.branch}`.")
        if self.result.base:
            out.append(f"Branched from `{self.result.base}`.")
        out.append("")

        failed = [s for s in sections if not s["solved"]]
        if failed:
            # Up front, not buried: what it could not do is the part a reviewer
            # most needs and the part a summary is most tempted to soften.
            out += ["## Not solved", ""]
            for s in failed:
                out.append(f"### {s['goal_line']}")
                out.append(f"- source: `{s['source']}`  file: `{s['target_file']}`")
                if s.get("unmet"):
                    out.append("- unmet criteria:")
                    out += [f"  - {u}" for u in s["unmet"]]
                if s.get("evidence"):
                    out.append(f"- evidence:\n\n```\n{s['evidence'][:800]}\n```")
                out.append("")

        out += ["## Solved", ""] if solved else []
        for s in sections:
            if not s["solved"]:
                continue
            out.append(f"### {s['goal_line']}")
            out.append(f"- source: `{s['source']}`  file: `{s['target_file']}`")
            out.append(
                f"- {s['steps']} step(s), {s['model_calls']} model call(s), "
                f"{s['repairs']} repair(s), {s['rounds']} plan round(s)"
            )
            if s.get("anchors"):
                out.append(f"- anchors: {', '.join(s['anchors'])}")
            if s.get("plan_fixes"):
                out.append("- plan repaired:")
                out += [f"  - {f}" for f in s["plan_fixes"]]
            out.append("")

        out += [
            "## How this was verified",
            "",
            "Every criterion above is executable: it runs from the repo root and",
            "must exit 0. Nothing here is the model's assessment of its own work —",
            "the numbers come from the run log, the verdicts from running code.",
            "",
        ]
        target = self.workspace / path
        target.write_text("\n".join(out), encoding="utf-8")
        self.result.report_path = path
        return "\n".join(out)

    # --- publishing (opt-in) ------------------------------------------------

    def open_pr(self, title: str, body: str) -> tuple[bool, str]:
        """Push the branch and open a PR. Only ever called on explicit request:
        pushing is outward-facing and not something to do by default."""
        code, out = _git(self.workspace, "push", "-u", "origin", self.branch, timeout=180)
        if code != 0:
            return False, f"push failed: {out.strip()[:300]}"
        try:
            p = subprocess.run(
                ["gh", "pr", "create", "--title", title, "--body", body, "--head", self.branch],
                cwd=str(self.workspace),
                capture_output=True,
                text=True,
                timeout=180,
            )
        except (subprocess.TimeoutExpired, OSError) as e:
            return False, f"gh not usable: {e}"
        if p.returncode != 0:
            return False, f"gh pr create failed: {(p.stderr or p.stdout).strip()[:300]}"
        url = (p.stdout or "").strip().splitlines()[-1] if p.stdout else ""
        self.result.pr_url = url
        return True, url
