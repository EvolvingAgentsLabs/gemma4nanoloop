"""Markdown knowledge-graph memory: write, read, links, search, index."""

from __future__ import annotations

import nanoloop.memory as mem
from nanoloop import frontmatter


def _isolate(tmp_path, monkeypatch):
    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path / "Memory")


def test_frontmatter_roundtrip():
    meta = {"name": "x", "description": "d", "metadata.type": "project"}
    text = frontmatter.dump(meta, "body [[y]]")
    parsed, body = frontmatter.parse(text)
    assert parsed["name"] == "x"
    assert parsed["metadata.type"] == "project"
    assert "[[y]]" in body


def test_write_read(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mem.write("Likes Pytest", "user prefers pytest", "Always use pytest.", "user")
    n = mem.read("likes-pytest")
    assert n.type == "user"
    assert n.description == "user prefers pytest"
    assert "pytest" in n.body


def test_slugify_and_links(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mem.write("API style", "d", "Follow [[Likes Pytest]] and [[rest-conventions]].")
    n = mem.read("api-style")
    assert n.name == "api-style"
    assert "likes-pytest" in n.links
    assert "rest-conventions" in n.links


def test_search_ranks(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mem.write("a", "deployment policy", "never deploy on fridays")
    mem.write("b", "lunch", "tacos are good")
    hits = mem.search("deploy friday")
    assert hits and hits[0].name == "a"


def test_graph_inbound_outbound(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mem.write("a", "d", "see [[b]]")
    mem.write("b", "d", "leaf")
    nb = mem.neighbors("b")
    assert nb["inbound"] == ["a"]
    assert nb["outbound"] == []


def test_reindex_written(tmp_path, monkeypatch):
    _isolate(tmp_path, monkeypatch)
    mem.write("a", "first note", "body")
    idx = (tmp_path / "Memory" / "MEMORY.md").read_text()
    assert "first note" in idx
    assert "[a](a.md)" in idx
