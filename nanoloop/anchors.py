"""Anchor location — the mechanism PLAN.md's viability hinges on (D4, §7 Q1).

The model never regenerates a file. It emits (path, anchor, replacement), where
`anchor` is literal text copied out of a file it just read. This module answers
one question: does that anchor identify exactly one span?

Four outcomes, and the distinction between them is the Phase 2 metric:

    EXACT      anchor appears verbatim exactly once      -> replace
    FUZZY      no verbatim hit, exactly one line-similar span above threshold
    NOT_FOUND  zero candidates                            -> raise, feed repair loop
    AMBIGUOUS  more than one candidate                    -> raise, feed repair loop

Ambiguity is a failure, not a coin flip. Picking the first of two matches is how
you silently corrupt a repo; raising is how you get a repair attempt with an
exact error message (D4).

Fuzzy matching is deliberately gated behind a flag. PLAN.md §4 Phase 2 is
explicit: measure the exact-hit rate FIRST, because that raw number is the
diagnostic for where the model actually is. Turning fuzzy on by default would
destroy the measurement.
"""

from __future__ import annotations

import difflib
import os
from dataclasses import dataclass
from enum import StrEnum

# Enabled only after the exact-hit rate has been measured and reported.
FUZZY_ENABLED = os.environ.get("NANOLOOP_FUZZY", "0").lower() in ("1", "true", "yes")
FUZZY_THRESHOLD = float(os.environ.get("NANOLOOP_FUZZY_THRESHOLD", "0.90"))


class Match(StrEnum):
    EXACT = "exact"
    FUZZY = "fuzzy"
    NOT_FOUND = "not_found"
    AMBIGUOUS = "ambiguous"


class AnchorError(Exception):
    """Raised on NOT_FOUND / AMBIGUOUS. The message is fed to the repair loop
    verbatim, so it must name the problem precisely enough to act on."""

    def __init__(self, kind: Match, message: str, candidates: int = 0):
        super().__init__(message)
        self.kind = kind
        self.candidates = candidates


@dataclass
class AnchorResult:
    kind: Match
    start: int = -1
    end: int = -1
    score: float = 1.0
    candidates: int = 0


def _norm(s: str) -> str:
    """Normalize for similarity only — never for slicing.

    Collapses whitespace runs and strips per-line padding, so a model that gets
    indentation slightly wrong still matches. The replacement always uses the
    real span offsets, so the file's actual bytes are what get edited.
    """
    return "\n".join(" ".join(line.split()) for line in s.strip().splitlines())


def find_exact(text: str, anchor: str) -> list[tuple[int, int]]:
    """Every verbatim occurrence, as (start, end) offsets. Non-overlapping."""
    if not anchor:
        return []
    spans, i = [], text.find(anchor)
    while i != -1:
        spans.append((i, i + len(anchor)))
        i = text.find(anchor, i + len(anchor))
    return spans


def find_fuzzy(
    text: str, anchor: str, threshold: float = FUZZY_THRESHOLD
) -> list[tuple[int, int, float]]:
    """Line-window similarity search. Returns (start, end, score) per candidate.

    Slides a window the same height as the anchor over the file and scores each
    with difflib on normalized text. Only windows at or above `threshold` come
    back; the caller still requires exactly one.
    """
    anchor_lines = anchor.strip().splitlines()
    if not anchor_lines:
        return []
    n = len(anchor_lines)
    target = _norm(anchor)

    # Offset of the start of each line, so a window maps back to real offsets.
    lines = text.splitlines(keepends=True)
    offsets, pos = [], 0
    for ln in lines:
        offsets.append(pos)
        pos += len(ln)
    offsets.append(pos)

    out: list[tuple[int, int, float]] = []
    for i in range(0, max(0, len(lines) - n + 1)):
        window = "".join(lines[i : i + n])
        score = difflib.SequenceMatcher(None, target, _norm(window)).ratio()
        if score >= threshold:
            start = offsets[i]
            end = offsets[i + n]
            # Trim the trailing newline so replacement doesn't eat the line break.
            if window.endswith("\n"):
                end -= 1
            out.append((start, end, score))

    # Collapse overlapping windows to their best-scoring representative, so one
    # real match spanning slightly different windows isn't reported as ambiguous.
    out.sort(key=lambda t: -t[2])
    kept: list[tuple[int, int, float]] = []
    for cand in out:
        if not any(cand[0] < k[1] and k[0] < cand[1] for k in kept):
            kept.append(cand)
    return kept


def locate(
    text: str, anchor: str, *, fuzzy: bool | None = None, threshold: float = FUZZY_THRESHOLD
) -> AnchorResult:
    """Resolve an anchor to exactly one span, or raise AnchorError."""
    use_fuzzy = FUZZY_ENABLED if fuzzy is None else fuzzy

    exact = find_exact(text, anchor)
    if len(exact) == 1:
        return AnchorResult(Match.EXACT, exact[0][0], exact[0][1], 1.0, 1)
    if len(exact) > 1:
        raise AnchorError(
            Match.AMBIGUOUS,
            f"anchor matches {len(exact)} times; it must match exactly once. "
            f"Extend the anchor with surrounding lines to make it unique.",
            len(exact),
        )

    if not use_fuzzy:
        raise AnchorError(
            Match.NOT_FOUND,
            "anchor not found in file. Copy the target text verbatim from the "
            "file contents shown above, including indentation.",
            0,
        )

    cands = find_fuzzy(text, anchor, threshold)
    if len(cands) == 1:
        s, e, score = cands[0]
        return AnchorResult(Match.FUZZY, s, e, score, 1)
    if len(cands) > 1:
        raise AnchorError(
            Match.AMBIGUOUS,
            f"anchor is similar to {len(cands)} different places in the file "
            f"(threshold {threshold}). Extend it until it is unique.",
            len(cands),
        )
    raise AnchorError(
        Match.NOT_FOUND,
        "anchor not found in file, even approximately. Copy the target text "
        "verbatim from the file contents shown above.",
        0,
    )


def classify(text: str, anchor: str, *, threshold: float = FUZZY_THRESHOLD) -> Match:
    """Non-raising variant for the Phase 2 measurement harness.

    Reports what WOULD happen, so eval can tabulate exact / fuzzy / not_found /
    ambiguous without try/except around every fixture.
    """
    exact = find_exact(text, anchor)
    if len(exact) == 1:
        return Match.EXACT
    if len(exact) > 1:
        return Match.AMBIGUOUS
    cands = find_fuzzy(text, anchor, threshold)
    if len(cands) == 1:
        return Match.FUZZY
    if len(cands) > 1:
        return Match.AMBIGUOUS
    return Match.NOT_FOUND
