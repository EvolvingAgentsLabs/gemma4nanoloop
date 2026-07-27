"""Phase 6: the prefix convention is the thing most likely to be silently wrong.

Query and document prefixes DIFFER, Ollama applies neither, and using the wrong
one degrades retrieval asymmetrically without raising. These tests are cheap
insurance against a failure that otherwise looks like "embeddings aren't great".
No network: everything here is pure.
"""

from __future__ import annotations

import math

from nanoloop import recall


def test_query_prefix_is_exact():
    assert recall.query_text("hello") == "task: search result | query: hello"


def test_document_prefix_is_exact():
    assert recall.document_text("", "body") == "title: none | text: body"
    assert recall.document_text("T", "body") == "title: T | text: body"


def test_query_and_document_prefixes_differ():
    assert recall.query_text("x") != recall.document_text("", "x")


def test_truncation_renormalizes(monkeypatch):
    """A Matryoshka-truncated vector is no longer unit length; not renormalizing
    quietly breaks cosine similarity."""
    monkeypatch.setattr(recall, "TRUNCATE_DIMS", 2)
    out = recall._post([3.0, 4.0, 100.0, 100.0])
    assert len(out) == 2
    assert math.isclose(math.sqrt(sum(x * x for x in out)), 1.0, rel_tol=1e-9)


def test_no_truncation_by_default(monkeypatch):
    monkeypatch.setattr(recall, "TRUNCATE_DIMS", 0)
    assert len(recall._post([1.0] * 768)) == 768


def test_cosine_of_identical_unit_vectors_is_one():
    v = recall._post([1.0, 2.0, 3.0])
    assert math.isclose(recall.cosine(v, v), 1.0, rel_tol=1e-9)


def test_short_note_is_one_chunk():
    assert recall.chunk("a short note") == ["a short note"]


def test_long_note_is_chunked_with_overlap():
    text = "\n\n".join(f"paragraph {i} " + "word " * 100 for i in range(20))
    chunks = recall.chunk(text)
    assert len(chunks) > 1
    assert all(len(c) <= recall.CHUNK_CHARS + recall.CHUNK_OVERLAP for c in chunks)


def test_empty_text_produces_no_chunks():
    assert recall.chunk("   ") == []


def test_link_regex_finds_graph_edges():
    assert recall.LINK_RE.findall("see [[other-note]] and [[third]]") == ["other-note", "third"]


# --- corpus selection --------------------------------------------------------


def test_corpus_excludes_the_generated_index(tmp_path, monkeypatch):
    """MEMORY.md lists every note's description. Indexed, it would match every
    query and beat the real notes — and it would do so silently."""
    import nanoloop.memory as mem

    monkeypatch.setattr(mem, "MEMORY_DIR", tmp_path)
    (tmp_path / "MEMORY.md").write_text("- [A](a.md) — hook\n- [B](b.md) — hook\n")
    (tmp_path / "a.md").write_text("---\nname: a\ndescription: d\n---\nbody a\n")
    names = {n["name"] for n in recall._corpus()}
    assert "MEMORY" not in names and "a" in names


def test_corpus_returns_plain_dicts():
    """memory.all_notes() yields dataclasses; build_index subscripts dicts."""
    for n in recall._corpus():
        assert set(n) == {"name", "description", "body"}
