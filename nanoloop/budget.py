"""A ceiling on what one task may spend, and a clean way to stop at it.

Autonomy without a budget is just an unbounded loop with a nicer name. A crew
you leave alone needs to be able to decide *this is enough* and say so.

RUNNING OUT IS A RESULT, NOT A CRASH. "I spent 20 calls and did not get there,
here is the last error" is honest and useful. Failing over into more attempts,
or dying with a traceback, is neither — and on a fanless Air it is also a real
cost in wall clock and thermal headroom.

The check happens BEFORE a call, never after: starting work you cannot pay for
wastes the most expensive thing in the loop. A partially spent budget that
cannot cover another call is exhausted, not almost-exhausted.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field


class BudgetExhausted(Exception):
    """Raised in place of a model call the budget cannot cover.

    Deliberately an exception rather than a return value: every path that spends
    budget goes through `model_ollama.chat`, and an exception is the only way to
    stop all of them without threading a check through code that has no other
    reason to know about budgets.

    NOT a RuntimeError, on purpose. `chat()` raises RuntimeError for transient
    backend trouble, and callers retry on it — the planner retries three times.
    Subclassing RuntimeError made "stop spending" indistinguishable from "try
    again", so the planner burned three more calls and then reported a bogus
    "no valid plan in 3 attempts". Keep it off that hierarchy: an exception that
    means STOP must not be catchable by a handler that means RETRY.
    """

    def __init__(self, budget: Budget, limit: str):
        super().__init__(f"budget exhausted ({limit}): {budget.summary()}")
        self.budget = budget
        self.limit = limit


@dataclass
class Budget:
    """What one task is allowed to spend. Zero or None means no limit."""

    max_calls: int = 0
    max_seconds: float = 0.0
    max_tokens: int = 0

    calls: int = 0
    tokens: int = 0
    started: float = field(default_factory=time.monotonic)
    exhausted_by: str = ""

    def reset(self) -> Budget:
        """Start a fresh task. Limits stay, spending goes back to zero."""
        self.calls = 0
        self.tokens = 0
        self.started = time.monotonic()
        self.exhausted_by = ""
        return self

    @property
    def elapsed(self) -> float:
        return time.monotonic() - self.started

    def remaining(self) -> dict[str, float]:
        out: dict[str, float] = {}
        if self.max_calls:
            out["calls"] = self.max_calls - self.calls
        if self.max_seconds:
            out["seconds"] = round(self.max_seconds - self.elapsed, 1)
        if self.max_tokens:
            out["tokens"] = self.max_tokens - self.tokens
        return out

    def check(self) -> None:
        """Raise if another call cannot be afforded. Called before spending."""
        if self.max_calls and self.calls >= self.max_calls:
            self.exhausted_by = f"max_calls={self.max_calls}"
        elif self.max_seconds and self.elapsed >= self.max_seconds:
            self.exhausted_by = f"max_seconds={self.max_seconds:g}"
        elif self.max_tokens and self.tokens >= self.max_tokens:
            self.exhausted_by = f"max_tokens={self.max_tokens}"
        else:
            return
        raise BudgetExhausted(self, self.exhausted_by)

    def spend(self, tokens: int = 0) -> None:
        self.calls += 1
        self.tokens += max(0, tokens)

    def summary(self) -> str:
        parts = [f"{self.calls} call(s)"]
        if self.tokens:
            parts.append(f"{self.tokens} tokens")
        parts.append(f"{self.elapsed:.0f}s")
        limits = [
            f"{k}={v}"
            for k, v in (
                ("max_calls", self.max_calls),
                ("max_seconds", self.max_seconds),
                ("max_tokens", self.max_tokens),
            )
            if v
        ]
        return ", ".join(parts) + (f" (limits: {', '.join(limits)})" if limits else "")


# The active budget. A module global because `model_ollama.chat` is the single
# chokepoint every spend goes through, and threading a Budget down to it would
# mean adding the parameter to every layer in between for no other reason.
_ACTIVE: Budget | None = None


def set_active(budget: Budget | None) -> None:
    global _ACTIVE
    _ACTIVE = budget


def active() -> Budget | None:
    return _ACTIVE


def check() -> None:
    if _ACTIVE is not None:
        _ACTIVE.check()


def spend(tokens: int = 0) -> None:
    if _ACTIVE is not None:
        _ACTIVE.spend(tokens)
