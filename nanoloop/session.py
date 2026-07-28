"""Session + task memory.

A Session persists across runs to ./.nanoloop/sessions/<id>.json. It tracks:
  - the original goal,
  - a task log (the crew's todo items + status as they progress),
  - a compact transcript (so a resumed run gets prior context),
  - human-in-the-loop decisions (audit of approvals/rejections).

This is deliberately file-backed and dependency-free.

WHAT IS ACTUALLY WIRED UP TODAY: `goal`, and `decisions` via the human gates in
`tools.human_review`. The task log and the transcript are carried over from the
nanoLoop fork and nothing in the current graph writes them — there is no resume
path (GAPS.md G8), and the crew never accumulates a transcript by design (D6).
The docstring used to describe them as backed by LangGraph's checkpointer, which
left with the DeepAgents orchestrator (D1). Left in place rather than deleted
because resume is a named next step; do not read them as live state.
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
    transcript: list[str] = field(default_factory=list)  # compact role: text lines

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

    @classmethod
    def load(cls, sid: str) -> Session:
        p = SESSIONS_DIR / f"{sid}.json"
        if not p.exists():
            raise FileNotFoundError(f"no session {sid}")
        d = json.loads(p.read_text(encoding="utf-8"))
        d["tasks"] = [Task(**t) for t in d.get("tasks", [])]
        d["decisions"] = [Decision(**x) for x in d.get("decisions", [])]
        return cls(**d)

    @classmethod
    def list_all(cls) -> list[Session]:
        if not SESSIONS_DIR.exists():
            return []
        out = []
        for p in SESSIONS_DIR.glob("*.json"):
            try:
                out.append(cls.load(p.stem))
            except Exception:
                continue
        return sorted(out, key=lambda s: s.updated, reverse=True)

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

    def log(self, role: str, text: str) -> None:
        line = f"{role}: {text}".strip().replace("\n", " ")
        self.transcript.append(line[:500])
        # keep transcript bounded
        self.transcript = self.transcript[-200:]
        self.save()

    # ---- resume context --------------------------------------------------
    def context_brief(self) -> str:
        """Short text injected into a resumed run so the crew has prior state."""
        lines = [f"Resuming session {self.id}. Original goal: {self.goal}", ""]
        if self.tasks:
            lines.append("Task log so far:")
            for t in self.tasks:
                lines.append(f"  [{t.status}] {t.title}" + (f" — {t.note}" if t.note else ""))
        if self.decisions:
            lines.append("")
            lines.append("Prior human decisions:")
            for d in self.decisions[-8:]:
                lines.append(f"  {d.gate}: {d.verdict} ({d.action})")
        return "\n".join(lines)
