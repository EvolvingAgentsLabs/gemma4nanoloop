"""Rendering helpers for todo items."""

from __future__ import annotations

from .store import Item


def render_item(item: Item) -> str:
    mark = "x" if item.done else " "
    return f"[{mark}] {item.title}"


def render_list(items: list[Item]) -> str:
    return "\n".join(render_item(i) for i in items)
