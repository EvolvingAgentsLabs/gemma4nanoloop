"""Phase 6: semantic recall over ./Memory with EmbeddingGemma.

THE PREFIXES ARE NON-NEGOTIABLE (PLAN.md §4 Phase 6).

EmbeddingGemma is trained with task prefixes, and Ollama does NOT apply them.
Queries and documents use DIFFERENT prefixes, so getting this wrong does not
raise — it silently degrades retrieval asymmetrically, which looks like "the
embeddings aren't very good" rather than a bug. There is exactly one function
for each, and both the indexer and the query path must go through them.

    query    "task: search result | query: "
    document "title: none | text: "

Chunking: EmbeddingGemma's window is 2K, so notes are chunked at 800-1000 tokens.
Dimensions: 768 is fine at this corpus size. Matryoshka truncation to 256 (with
RENORMALIZATION — a truncated vector is no longer unit-length) only if the index
becomes a problem.
"""

from __future__ import annotations

import json
import math
import os
import re
import urllib.error
import urllib.request
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from . import memory
from .model_ollama import GEMMA_RE, check_model

# Gemma family, enforced like the generation path (see model_ollama). There is
# no Gemma 4 embedder, so EmbeddingGemma is the model here — same family, older
# generation. Anything outside the family is refused rather than documented.
EMBED_MODEL = check_model(
    os.environ.get("NANOLOOP_EMBED_MODEL", "embeddinggemma"), family=GEMMA_RE, what="Gemma"
)
EMBED_URL = os.environ.get("NANOLOOP_EMBED_URL", "http://localhost:11434/api/embed")
INDEX_PATH = Path(os.environ.get("NANOLOOP_EMBED_INDEX", "./Memory/.index.json"))

CHUNK_CHARS = 3600  # ~900 tokens at ~4 chars/token, inside the 2K window
CHUNK_OVERLAP = 400
TRUNCATE_DIMS = int(os.environ.get("NANOLOOP_EMBED_DIMS", "0"))  # 0 = keep 768


# --- the one place prefixes are applied -------------------------------------


def query_text(q: str) -> str:
    return f"task: search result | query: {q}"


def document_text(title: str, text: str) -> str:
    # Google's convention uses the literal "none" when there is no title.
    return f"title: {title or 'none'} | text: {text}"


# --- embedding ---------------------------------------------------------------


def embed(texts: list[str]) -> list[list[float]]:
    """Call Ollama's /api/embed. Texts must ALREADY be prefixed."""
    req = urllib.request.Request(
        EMBED_URL,
        data=json.dumps({"model": EMBED_MODEL, "input": texts}).encode(),
        headers={"Content-Type": "application/json"},
    )
    try:
        with urllib.request.urlopen(req, timeout=120) as resp:
            payload = json.loads(resp.read())
    except (urllib.error.URLError, OSError) as e:
        raise RuntimeError(f"embedding backend unreachable at {EMBED_URL}: {e}") from e
    vecs = payload.get("embeddings") or []
    return [_post(v) for v in vecs]


def _post(vec: list[float]) -> list[float]:
    """Matryoshka truncation + renormalization. Truncating without renormalizing
    leaves a non-unit vector and quietly breaks cosine similarity."""
    if TRUNCATE_DIMS and len(vec) > TRUNCATE_DIMS:
        vec = vec[:TRUNCATE_DIMS]
    n = math.sqrt(sum(x * x for x in vec)) or 1.0
    return [x / n for x in vec]


def cosine(a: list[float], b: list[float]) -> float:
    return sum(x * y for x, y in zip(a, b, strict=False))


# --- chunking + index --------------------------------------------------------


def chunk(text: str, size: int = CHUNK_CHARS, overlap: int = CHUNK_OVERLAP) -> list[str]:
    text = text.strip()
    if len(text) <= size:
        return [text] if text else []
    out, start = [], 0
    while start < len(text):
        end = start + size
        piece = text[end - overlap : end] if end < len(text) else ""
        # Prefer a paragraph boundary inside the tail so chunks stay coherent.
        if piece and "\n\n" in piece:
            end = end - overlap + piece.rindex("\n\n")
        out.append(text[start:end].strip())
        if end >= len(text):
            break
        start = max(start + 1, end - overlap)
    return [c for c in out if c]


@dataclass
class Chunk:
    note: str
    description: str
    text: str
    vector: list[float]


def _corpus() -> list[dict]:
    """The notes to index, as plain dicts.

    `memory.all_notes()` returns Note dataclasses and — importantly — skips
    MEMORY.md, the generated table of contents. That file lists every note's
    description, so indexing it would produce one chunk that matches every query
    and quietly beats the real notes. The keyword baseline goes through the same
    function, so both retrievers see exactly the same corpus.
    """
    if hasattr(memory, "all_notes"):
        return [
            {"name": n.name, "description": n.description, "body": n.body}
            for n in memory.all_notes()
        ]
    return _scan_notes()


def build_index(path: Path | None = None) -> list[Chunk]:
    """Embed every note chunk and persist. Documents get the DOCUMENT prefix."""
    notes = _corpus()
    chunks: list[Chunk] = []
    payload, meta = [], []
    for n in notes:
        for piece in chunk(n["body"]):
            payload.append(document_text(n["description"], piece))
            meta.append((n["name"], n["description"], piece))
    if payload:
        vectors = embed(payload)
        chunks = [Chunk(m[0], m[1], m[2], v) for m, v in zip(meta, vectors, strict=False)]

    target = path or INDEX_PATH
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(
        json.dumps(
            [
                {"note": c.note, "description": c.description, "text": c.text, "vector": c.vector}
                for c in chunks
            ]
        ),
        encoding="utf-8",
    )
    return chunks


def load_index(path: Path | None = None) -> list[Chunk]:
    target = path or INDEX_PATH
    if not target.exists():
        return []
    raw = json.loads(target.read_text(encoding="utf-8"))
    return [Chunk(r["note"], r["description"], r["text"], r["vector"]) for r in raw]


def _scan_notes() -> list[dict]:
    """Fallback reader for ./Memory/*.md when memory.py exposes no bulk API."""
    from . import frontmatter

    mem_dir = Path(os.environ.get("NANOLOOP_MEMORY_DIR", "Memory"))
    index_name = getattr(memory, "INDEX_NAME", "MEMORY.md")
    out = []
    for p in sorted(mem_dir.glob("*.md")):
        # Skip the generated table of contents for the reason in _corpus().
        if p.name.startswith(".") or p.name == index_name:
            continue
        meta, body = frontmatter.parse(p.read_text(encoding="utf-8"))
        out.append(
            {
                "name": meta.get("name", p.stem),
                "description": meta.get("description", ""),
                "body": body,
            }
        )
    return out


# --- retrieval ---------------------------------------------------------------

LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")


def search(
    query: str, limit: int = 5, *, expand_links: bool = True, index: list[Chunk] | None = None
) -> list[dict]:
    """Semantic top-k, then expand along the [[links]] knowledge graph.

    Graph expansion is what makes this beat a plain vector store on this corpus:
    the note that matches semantically often points at the note that actually
    answers the question.
    """
    idx = index if index is not None else load_index()
    if not idx:
        return []
    qvec = embed([query_text(query)])[0]

    # Annotated because the row mixes str and float: inferred, every value is
    # `object` and both the sort key and the link expansion below stop
    # type-checking (three errors that `nanoloop harvest` surfaced on this repo).
    rows: list[dict[str, Any]] = [
        {
            "note": c.note,
            "description": c.description,
            "text": c.text,
            "score": cosine(qvec, c.vector),
        }
        for c in idx
    ]
    scored = sorted(rows, key=lambda r: -r["score"])

    seen: set[str] = set()
    top: list[dict[str, Any]] = []
    for r in scored:  # one hit per note, best chunk wins
        if r["note"] in seen:
            continue
        seen.add(r["note"])
        top.append(r)
        if len(top) >= limit:
            break

    if expand_links:
        for r in list(top):
            for link in LINK_RE.findall(r["text"]):
                slug = memory.slugify(link)
                if slug in seen:
                    continue
                for c in idx:
                    if c.note == slug:
                        seen.add(slug)
                        top.append(
                            {
                                "note": c.note,
                                "description": c.description,
                                "text": c.text,
                                "score": r["score"] * 0.5,
                                "via": r["note"],
                            }
                        )
                        break
    return top
