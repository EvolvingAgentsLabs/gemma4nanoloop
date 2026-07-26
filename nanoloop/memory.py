"""Markdown knowledge-graph memory.

Each fact is one Markdown file in ./Memory/<name>.md with frontmatter:

    ---
    name: <kebab-slug>
    description: <one-line summary used for recall>
    metadata:
      type: user | feedback | project | reference
    ---

    <fact body; link related notes with [[other-name]]>

Links form a knowledge graph: `[[name]]` references another note by its slug.
An index file Memory/MEMORY.md lists one line per note for quick scanning.
"""

from __future__ import annotations

import os
import re
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter

MEMORY_DIR = Path(os.environ.get("NANOLOOP_MEMORY_DIR", "Memory"))
INDEX_NAME = "MEMORY.md"
_LINK_RE = re.compile(r"\[\[([^\]]+)\]\]")
_SLUG_RE = re.compile(r"[^a-z0-9]+")


def slugify(name: str) -> str:
    return _SLUG_RE.sub("-", name.strip().lower()).strip("-")


@dataclass
class Note:
    name: str
    description: str
    type: str
    body: str

    @property
    def links(self) -> list[str]:
        """Outbound [[wikilink]] slugs found in the body."""
        return [slugify(m) for m in _LINK_RE.findall(self.body)]

    def render(self) -> str:
        meta = {
            "name": self.name,
            "description": self.description,
            "metadata.type": self.type,
        }
        return frontmatter.dump(meta, self.body)


def _dir() -> Path:
    MEMORY_DIR.mkdir(parents=True, exist_ok=True)
    return MEMORY_DIR


def _path(name: str) -> Path:
    return _dir() / f"{slugify(name)}.md"


def write(name: str, description: str, content: str, type: str = "reference") -> Note:
    """Create or overwrite a note, then refresh the index."""
    note = Note(
        name=slugify(name),
        description=description.strip(),
        type=type.strip() or "reference",
        body=content.strip(),
    )
    _path(note.name).write_text(note.render(), encoding="utf-8")
    reindex()
    return note


def read(name: str) -> Note | None:
    p = _path(name)
    if not p.exists():
        return None
    meta, body = frontmatter.parse(p.read_text(encoding="utf-8"))
    return Note(
        name=meta.get("name", slugify(name)),
        description=meta.get("description", ""),
        type=meta.get("metadata.type", meta.get("type", "reference")),
        body=body,
    )


def all_notes() -> list[Note]:
    out = []
    for p in sorted(_dir().glob("*.md")):
        if p.name == INDEX_NAME:
            continue
        n = read(p.stem)
        if n:
            out.append(n)
    return out


def search(query: str, limit: int = 5) -> list[Note]:
    """Rank notes by term overlap against description + body."""
    terms = [t for t in re.split(r"\W+", query.lower()) if t]
    scored = []
    for n in all_notes():
        hay = f"{n.name} {n.description} {n.body}".lower()
        score = sum(hay.count(t) for t in terms)
        if score:
            scored.append((score, n))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [n for _, n in scored[:limit]]


def graph() -> dict[str, list[str]]:
    """Adjacency map name -> outbound link slugs (knowledge graph)."""
    return {n.name: n.links for n in all_notes()}


def neighbors(name: str) -> dict[str, list[str]]:
    """Outbound and inbound links for one note."""
    slug = slugify(name)
    g = graph()
    inbound = [src for src, links in g.items() if slug in links]
    return {"outbound": g.get(slug, []), "inbound": inbound}


def reindex() -> Path:
    """Rewrite Memory/MEMORY.md — one pointer line per note."""
    lines = ["# Memory index", ""]
    for n in all_notes():
        lines.append(f"- [{n.name}]({n.name}.md) ({n.type}) — {n.description}")
    idx = _dir() / INDEX_NAME
    idx.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return idx


def index_text() -> str:
    """The index content (for injecting into agent context)."""
    notes = all_notes()
    if not notes:
        return ""
    return "\n".join(f"- {n.name} ({n.type}): {n.description}" for n in notes)
