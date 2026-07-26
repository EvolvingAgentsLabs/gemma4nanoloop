"""Append-only JSONL log of every model call.

PLAN.md §4 Phase 0.4: this ships before the first real request. When the runtime
changes (Ollama -> LiteRT-LM, num_ctx retune, prompt edit) this log is the
regression suite — it is the only place that knows what the model was actually
sent and what it actually returned.

One line per call, never rewritten. Cheap to append, trivial to diff, and
`eval/report.py` reads nothing else.
"""

from __future__ import annotations

import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any

LOG_PATH = Path(os.environ.get("NANOLOOP_CALLLOG", "./calls.jsonl"))

# Process start, so wall_clock_since_start is comparable across a whole run.
# This is what makes the Phase 4 throttling curve plottable.
_T0 = time.monotonic()


def reset_clock() -> None:
    """Restart the wall-clock origin (call at the top of a run)."""
    global _T0
    _T0 = time.monotonic()


@dataclass
class CallRecord:
    phase: str
    prompt_tokens: int | None
    tools_offered: list[str]
    raw_output: str
    parsed_output: Any
    parse_ok: bool
    latency_ms: int
    wall_clock_since_start: float
    # Context beyond PLAN.md's required set — free to record, expensive to
    # reconstruct later.
    model: str = ""
    num_ctx: int | None = None
    temperature: float | None = None
    completion_tokens: int | None = None
    step_index: int | None = None
    attempt: int | None = None
    error: str | None = None
    # Non-zero means the model spent tokens on chain-of-thought. On this
    # hardware that alone explains an 8x latency regression — see model_ollama.
    thinking_chars: int = 0
    ts: float = field(default_factory=time.time)


def record(rec: CallRecord, path: Path | None = None) -> CallRecord:
    """Append one record. Never raises into the caller's control flow."""
    target = path or LOG_PATH
    try:
        target.parent.mkdir(parents=True, exist_ok=True)
        with target.open("a", encoding="utf-8") as fh:
            fh.write(json.dumps(asdict(rec), default=str, ensure_ascii=False) + "\n")
    except OSError:
        # Losing telemetry must never take down a run.
        pass
    return rec


def now_offset() -> float:
    return round(time.monotonic() - _T0, 3)


def read(path: Path | None = None) -> list[dict]:
    """Load the log back. Tolerates a truncated final line."""
    target = path or LOG_PATH
    if not target.exists():
        return []
    out: list[dict] = []
    for line in target.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return out
