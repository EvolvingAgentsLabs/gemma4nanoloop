"""Skill discovery + loading from ./Skills (file form and SKILL.md dir form)."""

from __future__ import annotations

import nanoloop.skills as sk


def _seed(tmp_path, monkeypatch):
    d = tmp_path / "Skills"
    d.mkdir()
    monkeypatch.setattr(sk, "SKILLS_DIR", d)
    return d


def test_discover_file_form(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    (d / "lint.md").write_text("---\nname: lint\ndescription: run linters\n---\nrun ruff.\n")
    skills = sk.discover()
    assert [s.name for s in skills] == ["lint"]
    assert skills[0].description == "run linters"
    assert "ruff" in skills[0].body


def test_discover_dir_form_and_name_fallback(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    sub = d / "deploy"
    sub.mkdir()
    (sub / "SKILL.md").write_text("---\ndescription: ship it\n---\nsteps.\n")
    s = sk.get("deploy")
    assert s is not None
    assert s.name == "deploy"  # falls back to dir name
    assert s.description == "ship it"


def test_get_missing(tmp_path, monkeypatch):
    _seed(tmp_path, monkeypatch)
    assert sk.get("nope") is None


def test_catalog_text(tmp_path, monkeypatch):
    d = _seed(tmp_path, monkeypatch)
    (d / "a.md").write_text("---\nname: a\ndescription: do a\n---\nx\n")
    assert sk.catalog_text() == "- a: do a"
