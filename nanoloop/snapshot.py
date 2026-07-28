"""D8: every candidate starts from a clean tree.

Without this, edits from rejected candidates stack — attempt 3 is applied on top
of the wreckage of attempts 1 and 2, and the gate output stops describing the
change you think you are testing.

PLAN.md offers "git stash or a workspace copy". Copy is the default here.
`git stash` is global repo state: it interacts badly with anything else touching
the tree, a failed `pop` leaves a dirty tree that the loop cannot detect, and it
silently ignores untracked files unless you remember `-u` — which is exactly the
case that matters, since a step's first action is often creating a file.
`GitSnapshot` is provided for large repos where copying is too slow, with those
caveats made explicit.
"""

from __future__ import annotations

import shutil
import subprocess
import tempfile
from pathlib import Path

IGNORE = shutil.ignore_patterns(
    ".git",
    ".venv",
    "venv",
    "__pycache__",
    "*.pyc",
    ".mypy_cache",
    ".pytest_cache",
    ".ruff_cache",
    "node_modules",
)


class CopySnapshot:
    """Snapshot by copying the workspace aside. Simple, isolated, no repo state."""

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace)
        self._store: Path | None = None

    def save(self) -> None:
        self.discard()
        self._store = Path(tempfile.mkdtemp(prefix="nanoloop-snap-"))
        dest = self._store / "tree"
        shutil.copytree(self.workspace, dest, ignore=IGNORE, symlinks=True)

    def restore(self) -> None:
        if not self._store:
            return
        src = self._store / "tree"
        if not src.exists():
            return
        # Remove only what we manage; leave ignored dirs (.git, .venv) untouched
        # so restoring doesn't nuke the virtualenv the gates need.
        for child in self.workspace.iterdir():
            if child.name in {".git", ".venv", "venv", "node_modules"}:
                continue
            shutil.rmtree(child) if child.is_dir() else child.unlink()
        for child in src.iterdir():
            target = self.workspace / child.name
            shutil.copytree(child, target, symlinks=True) if child.is_dir() else shutil.copy2(
                child, target
            )

    def discard(self) -> None:
        if self._store and self._store.exists():
            shutil.rmtree(self._store, ignore_errors=True)
        self._store = None

    def __enter__(self):
        self.save()
        return self

    def __exit__(self, *exc):
        self.discard()
        return False


class GitSnapshot:
    """Snapshot via `git stash -u`. Faster on big repos; global repo state.

    Only for workspaces that are their own git repo and that nothing else is
    touching concurrently.

    SAVE MUST NOT MUTATE THE TREE. `git stash push` on its own reverts the
    working tree to HEAD, which is a different operation from what CopySnapshot
    does and silently destroys work: by the time step 2 called save(), step 1's
    edit — committed nowhere, since the crew only commits at delivery time — was
    in the stash and gone from the tree. A three-step plan finished with only the
    last step applied, and nothing in the run reported a problem because every
    gate had passed at the time it ran.

    So save() stashes and immediately applies the stash back. The tree is
    unchanged, and a copy of it lives in the stash for restore() to return to.
    The two snapshots then mean the same thing, which is the only way `--snapshot
    git` can be a drop-in for the default.
    """

    def __init__(self, workspace: Path | str):
        self.workspace = Path(workspace)
        self._stashed = False

    def _git(self, *args: str) -> subprocess.CompletedProcess:
        return subprocess.run(
            ["git", *args], cwd=str(self.workspace), capture_output=True, text=True
        )

    def save(self) -> None:
        # Drop any earlier snapshot first, exactly as CopySnapshot does. Without
        # it a run leaves one stash entry per step behind on the user's repo.
        self.discard()
        # -u so untracked files are captured: a step's first act is often to
        # create a file, and a stash without -u would leave it behind on restore.
        r = self._git("stash", "push", "-u", "-m", "nanoloop-candidate")
        self._stashed = r.returncode == 0 and "No local changes" not in (r.stdout or "")
        if self._stashed:
            # Put the working tree back the way we found it. `apply` (not `pop`)
            # keeps the entry, which is what restore() returns to.
            self._git("stash", "apply", "--quiet")

    def restore(self) -> None:
        self._git("checkout", "--", ".")
        self._git("clean", "-fd")
        if self._stashed:
            self._git("stash", "pop")
            self._stashed = False

    def discard(self) -> None:
        if self._stashed:
            self._git("stash", "drop")
            self._stashed = False

    def __enter__(self):
        self.save()
        return self

    def __exit__(self, *exc):
        self.discard()
        return False


def make(workspace: Path | str, kind: str = "copy"):
    return GitSnapshot(workspace) if kind == "git" else CopySnapshot(workspace)
