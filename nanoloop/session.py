"""The audit trail for a run: its goal, and every human decision on it.

Persisted to ./.nanoloop/sessions/<id>.json, file-backed and dependency-free.

WHAT IS HERE IS WHAT IS WRITTEN. `goal` and `decisions` (via the gates in
`tools.human_review`) are the live state; `tasks` is written by the `track_task`
tool. The transcript, `load()`, `list_all()` and `context_brief()` are gone —
they were carried over from the nanoLoop fork for a resume path that does not
exist (GAPS.md G8), nothing wrote them, and a resumed-session API that has never
resumed a session is a claim rather than a feature. When resume is built, build
its state then, against how the graph actually works.
"""

from __future__ import annotations

import json
import time
import uuid
from dataclasses import asdict, dataclass, field
from pathlib import Path

SESSIONS_DIR = Path(".nanoloop/sessions")


def _now() -> float:
    return time.time()


@dataclass
class Task:
    id: str
    title: str
    status: str = "pending"  # pending | active | done | blocked
    note: str = ""
    updated: float = field(default_factory=_now)


@dataclass
class Decision:
    ts: float
    gate: str
    action: str
    verdict: str  # approved | rejected | auto
    note: str = ""


@dataclass
class Session:
    id: str
    goal: str
    created: float = field(default_factory=_now)
    updated: float = field(default_factory=_now)
    tasks: list[Task] = field(default_factory=list)
    decisions: list[Decision] = field(default_factory=list)

    # ---- persistence ----------------------------------------------------
    @property
    def path(self) -> Path:
        return SESSIONS_DIR / f"{self.id}.json"

    def save(self) -> None:
        self.updated = _now()
        SESSIONS_DIR.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps(asdict(self), indent=2), encoding="utf-8")

    @classmethod
    def create(cls, goal: str) -> Session:
        s = cls(id=uuid.uuid4().hex[:8], goal=goal)
        s.save()
        return s

    # ---- task tracking ---------------------------------------------------
    def upsert_task(self, title: str, status: str = "pending", note: str = "") -> Task:
        for t in self.tasks:
            if t.title == title:
                t.status = status or t.status
                t.note = note or t.note
                t.updated = _now()
                self.save()
                return t
        t = Task(id=uuid.uuid4().hex[:6], title=title, status=status, note=note)
        self.tasks.append(t)
        self.save()
        return t

    def record_decision(self, gate: str, action: str, verdict: str, note: str = "") -> None:
        self.decisions.append(
            Decision(ts=_now(), gate=gate, action=action, verdict=verdict, note=note)
        )
        self.save()
