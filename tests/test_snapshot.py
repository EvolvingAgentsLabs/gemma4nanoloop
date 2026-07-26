"""D8: every candidate starts from a clean tree.

Without restore, edits from rejected candidates stack and the gate output stops
describing the change under test.
"""

from __future__ import annotations

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
