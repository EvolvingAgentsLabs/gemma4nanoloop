"""Minimal frontmatter parser — no PyYAML dependency.

Handles the subset we use: a leading `---` fenced block of `key: value` pairs,
with at most one level of nesting under an indented block (e.g. `metadata:` ->
`  type: ...`). Nested keys are flattened to dotted form: `metadata.type`.
"""

from __future__ import annotations


def parse(text: str) -> tuple[dict[str, str], str]:
    """Return (meta, body). If no frontmatter fence, meta is empty."""
    if not text.startswith("---"):
        return {}, text
    lines = text.splitlines()
    # lines[0] == "---"; find closing fence.
    end = None
    for i in range(1, len(lines)):
        if lines[i].strip() == "---":
            end = i
            break
    if end is None:
        return {}, text

    meta: dict[str, str] = {}
    parent: str | None = None
    for raw in lines[1:end]:
        if not raw.strip():
            continue
        indented = raw[:1] in (" ", "\t")
        key, _, val = raw.strip().partition(":")
        key, val = key.strip(), val.strip()
        if not val:  # opens a nested block, e.g. "metadata:"
            parent = key
            continue
        if indented and parent:
            meta[f"{parent}.{key}"] = val
        else:
            parent = None
            meta[key] = val

    body = "\n".join(lines[end + 1 :]).lstrip("\n")
    return meta, body


def dump(meta: dict[str, str], body: str) -> str:
    """Serialize flat/dotted meta back to a frontmatter block + body."""
    lines = ["---"]
    nested: dict[str, list[tuple[str, str]]] = {}
    for k, v in meta.items():
        if "." in k:
            parent, child = k.split(".", 1)
            nested.setdefault(parent, []).append((child, v))
        else:
            lines.append(f"{k}: {v}")
    for parent, kids in nested.items():
        lines.append(f"{parent}:")
        for child, v in kids:
            lines.append(f"  {child}: {v}")
    lines.append("---")
    return "\n".join(lines) + "\n\n" + body.strip() + "\n"
