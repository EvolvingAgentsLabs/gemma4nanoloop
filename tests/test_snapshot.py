"""D8: every candidate starts from a clean tree.

Without restore, edits from rejected candidates stack and the gate output stops
describing the change under test.
"""

from __future__ import annotations

import subprocess

import pytest

from nanoloop import snapshot


def test_restore_undoes_a_modification(tmp_path):
    f = tmp_path / "a.py"
    f.write_text("original\n")
    snap = snapshot.CopySnapshot(tmp_path)
    snap.save()
    f.write_text("candidate edit\n")
    snap.restore()
    assert f.read_text() == "original\n"


def test_restore_removes_files_created_by_a_candidate(tmp_path):
    (tmp_path / "keep.py").write_text("keep\n")
    snap = snapshot.CopySnapshot(tmp_path)
    snap.save()
    (tmp_path / "new.py").write_text("added by a rejected candidate\n")
    snap.restore()
    assert not (tmp_path / "new.py").exists()
    assert (tmp_path / "keep.py").exists()


def test_restore_handles_nested_directories(tmp_path):
    pkg = tmp_path / "pkg"
    pkg.mkdir()
    (pkg / "m.py").write_text("v1\n")
    snap = snapshot.CopySnapshot(tmp_path)
    snap.save()
    (pkg / "m.py").write_text("v2\n")
    (pkg / "extra.py").write_text("x\n")
    snap.restore()
    assert (pkg / "m.py").read_text() == "v1\n"
    assert not (pkg / "extra.py").exists()


def test_venv_and_git_are_preserved_across_restore(tmp_path):
    """Restoring must not nuke the virtualenv the gates need to run."""
    venv = tmp_path / ".venv"
    venv.mkdir()
    (venv / "marker").write_text("do not delete\n")
    snap = snapshot.CopySnapshot(tmp_path)
    snap.save()
    (tmp_path / "x.py").write_text("edit\n")
    snap.restore()
    assert (venv / "marker").exists()


def test_context_manager_cleans_up(tmp_path):
    (tmp_path / "a.py").write_text("a\n")
    with snapshot.CopySnapshot(tmp_path) as snap:
        store = snap._store
        assert store and store.exists()
    assert not store.exists()


def test_make_selects_backend(tmp_path):
    assert isinstance(snapshot.make(tmp_path, "copy"), snapshot.CopySnapshot)
    assert isinstance(snapshot.make(tmp_path, "git"), snapshot.GitSnapshot)


# --- GitSnapshot: the same contract, or it is not a drop-in ------------------


def _repo(path):
    def git(*args):
        return subprocess.run(
            ["git", *args], cwd=str(path), capture_output=True, text=True, check=False
        )

    if git("init", "-q", ".").returncode != 0:
        pytest.skip("git unavailable")
    git("config", "user.email", "t@example.com")
    git("config", "user.name", "t")
    (path / "mod.py").write_text("committed\n")
    git("add", "-A")
    git("commit", "-qm", "init")
    return git


@pytest.mark.parametrize("kind", ["copy", "git"])
def test_save_does_not_touch_the_working_tree(tmp_path, kind):
    """The regression that cost a three-step plan two of its steps.

    `git stash push` reverts the tree to HEAD, so the save() at the start of step
    2 threw away step 1's work — which the crew has not committed and cannot get
    back. Both backends must leave the tree exactly as they found it.
    """
    _repo(tmp_path)
    (tmp_path / "mod.py").write_text("committed\nstep 1 work\n")
    (tmp_path / "new.py").write_text("created by step 1\n")

    snap = snapshot.make(tmp_path, kind)
    snap.save()

    assert (tmp_path / "mod.py").read_text() == "committed\nstep 1 work\n"
    assert (tmp_path / "new.py").read_text() == "created by step 1\n"


@pytest.mark.parametrize("kind", ["copy", "git"])
def test_restore_returns_to_the_saved_state_not_to_head(tmp_path, kind):
    """Restore means "undo this candidate", never "undo everything so far"."""
    _repo(tmp_path)
    (tmp_path / "mod.py").write_text("committed\nstep 1 work\n")

    snap = snapshot.make(tmp_path, kind)
    snap.save()
    (tmp_path / "mod.py").write_text("committed\nstep 1 work\ncandidate\n")
    (tmp_path / "junk.py").write_text("from a rejected candidate\n")
    snap.restore()

    assert (tmp_path / "mod.py").read_text() == "committed\nstep 1 work\n"
    assert not (tmp_path / "junk.py").exists()


def test_git_snapshot_leaves_no_stash_behind(tmp_path):
    """A run must not litter the user's repo with one stash entry per step."""
    git = _repo(tmp_path)
    snap = snapshot.GitSnapshot(tmp_path)
    for i in range(3):
        (tmp_path / "mod.py").write_text(f"committed\nstep {i}\n")
        snap.save()
    snap.discard()
    assert git("stash", "list").stdout.strip() == ""


def test_git_snapshot_save_is_a_noop_on_a_clean_tree(tmp_path):
    """Nothing to stash must not mean "apply somebody else's stash"."""
    git = _repo(tmp_path)
    git("stash", "push", "-u", "-m", "someone else's work")  # nothing to stash
    (tmp_path / "unrelated.py").write_text("pre-existing\n")
    git("add", "-A")
    git("commit", "-qm", "second")

    snap = snapshot.GitSnapshot(tmp_path)
    snap.save()
    assert snap._stashed is False
    assert (tmp_path / "unrelated.py").read_text() == "pre-existing\n"
