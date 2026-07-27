"""What went wrong last time, so the planner does not walk into it again.

The loop currently starts every task with no idea that it has already tried this
and failed. It will re-plan the same doomed shape, spend the same budget, and
fail the same way — which on a fanless Air is minutes of wall clock per repeat.

THE DANGEROUS PART IS STALENESS, NOT STORAGE. A remembered failure that has
since been fixed is worse than no memory at all: it tells the planner to avoid
something that now works, and unlike a missing memory, a wrong one actively
steers. So every success SUPERSEDES the failures recorded for the same target,
and nothing is recalled that a later success has already contradicted.

Kept as JSONL rather than as knowledge-graph notes: an attempt is a structured
record queried by exact file, not prose to be searched semantically. `memory.py`
remains the right home for durable facts about a project; this is a flight
recorder.
"""

from __future__ import annotations

import json
import os
import re
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

MEM_PATH = Path(os.environ.get("NANOLOOP_FAILMEM", "./Memory/attempts.jsonl"))

# How many past failures to surface. More than a couple stops being advice and
# starts being noise that crowds out the repo map.
MAX_LESSONS = 3


@dataclass
class Attempt:
    goal: str
    target_file: str
    outcome: str  # solved | unmet | gave_up
    detail: str = ""
    ts: float = field(default_factory=time.time)

    @property
    def failed(self) -> bool:
        return self.outcome != "solved"


STOP = {
    "the",
    "and",
    "that",
    "with",
    "for",
    "make",
    "add",
    "this",
    "into",
    "from",
    "pass",
    "test",
    "code",
    "under",
    "not",
    "itself",
    "fix",
    "failing",
}

# How much two goals must overlap to count as the same work. Tuned by the case
# it exists for: "add by_tag to Store" vs "implement by_tag(tag) on Store" share
# {by_tag, store} out of {by_tag, store, implement} — 0.66.
SAME_WORK = 0.5


def _words(goal: str) -> set[str]:
    """A coarse fingerprint of what the goal is about.

    Deliberately lossy: the same intent is worded differently every run. An
    earlier version compared these sets for EQUALITY and therefore matched
    almost nothing — one extra word made a goal unrecognisable to its own past
    failure. Overlap is what makes a lossy key actually lossy.
    """
    return {w for w in re.findall(r"[a-z_][a-z0-9_]{2,}", goal.lower()) if w not in STOP}


def _key(goal: str) -> str:
    return " ".join(sorted(_words(goal))[:12])


def _same_work(a: str, b: str) -> bool:
    wa, wb = _words(a), _words(b)
    if not wa or not wb:
        return False
    return len(wa & wb) / len(wa | wb) >= SAME_WORK


def record(attempt: Attempt, path: Path | None = None) -> None:
    target = path or MEM_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps({**asdict(attempt), "key": _key(attempt.goal)}) + "\n")
    except OSError:
        pass  # a flight recorder must never take down the flight


def read(path: Path | None = None) -> list[dict]:
    target = path or MEM_PATH
    if not target.exists():
        return []
    out = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out


def lessons(goal: str, target_file: str = "", path: Path | None = None) -> list[str]:
    """Past failures worth warning the planner about, newest first.

    A record counts only if BOTH:
      - it is about the same thing (same coarse key, or the same file), and
      - no later success has superseded it.

    The supersede rule is the whole safety mechanism. Without it the memory
    would keep insisting a fixed problem is still broken.
    """
    rows = read(path)
    if not rows:
        return []

    # Latest success per (key, file) — anything older than it is settled.
    solved = [r for r in rows if r.get("outcome") == "solved"]

    def superseded(rec: dict) -> bool:
        """Has a later success settled this failure?"""
        return any(
            s.get("ts", 0.0) > rec.get("ts", 0.0)
            and (
                _same_work(rec.get("goal", ""), s.get("goal", ""))
                or rec.get("target_file") == s.get("target_file")
            )
            for s in solved
        )

    picked = []
    for r in reversed(rows):
        if r.get("outcome") == "solved":
            continue
        same = _same_work(goal, r.get("goal", "")) or (
            bool(target_file) and r.get("target_file") == target_file
        )
        if not same:
            continue
        if superseded(r):
            continue  # a later success settled this
        detail = (r.get("detail") or "").strip().splitlines()
        first = detail[0][:200] if detail else r.get("outcome", "failed")
        picked.append(f"{r.get('target_file', '?')}: {r.get('outcome')} — {first}")
        if len(picked) >= MAX_LESSONS:
            break
    return picked


def render(goal: str, target_file: str = "", path: Path | None = None) -> str:
    """The block injected into the planner prompt, or empty."""
    found = lessons(goal, target_file, path)
    if not found:
        return ""
    body = "\n".join(f"- {line}" for line in found)
    return (
        "\n\n# Previous attempts at this failed\n"
        f"{body}\n"
        "Plan differently: break the work into smaller steps, or target a "
        "different file. Do not repeat the shape that already failed."
    )
