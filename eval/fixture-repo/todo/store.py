"""In-memory todo store."""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass
class Item:
    title: str
    done: bool = False
    tags: list[str] = field(default_factory=list)


class Store:
    """Holds todo items in insertion order."""

    def __init__(self) -> None:
        self._items: list[Item] = []

    def add(self, title: str) -> Item:
        item = Item(title=title)
        self._items.append(item)
        return item

    def complete(self, title: str) -> bool:
        for item in self._items:
            if item.title == title:
                item.done = True
                return True
        return False

    def pending(self) -> list[Item]:
        return [i for i in self._items if not i.done]

    def all(self) -> list[Item]:
        return list(self._items)
