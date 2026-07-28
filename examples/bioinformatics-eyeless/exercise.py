"""Break the example on purpose, so the crew has something real to fix.

    python exercise.py break     # reintroduce the classic off-by-one
    python exercise.py restore   # put it back
    python exercise.py status    # which state am I in?

`conserved.py` ships CORRECT, so `discover.py` works the moment you clone it.
That is the right default for a reader and the wrong one for a demonstration:
the crew needs a repo that is red.

This used to be a diff in exercise.md that you applied by hand. Doing it in code
is not just convenience — a hand-applied diff is a step that can go wrong
silently, and then you are debugging your own typo instead of watching the crew
work. This edits one known anchor, verifies the result, and refuses to guess.

WHAT IT BREAKS. The bug is the canonical bioinformatics off-by-one: returning
0-based coordinates from behind a docstring that promises 1-based, inclusive,
the way BLAST reports them. It is a good demonstration bug because it is
invisible to every gate except the test — the code still runs, still returns
plausible numbers, and is wrong by exactly one.
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

TARGET = Path(__file__).parent / "conserved.py"

# (correct, buggy). Anchors, not line numbers: this file must keep working when
# the code around it moves.
SWAPS = [
    ('"query_start": qs + 1,', '"query_start": qs,'),
    ('"subject_start": ss + 1,', '"subject_start": ss,'),
]


def state(text: str) -> str:
    """correct | broken | unrecognised.

    The two forms are not substrings of one another (`qs + 1,` vs `qs,`), so
    plain containment answers this without any counting games.
    """
    if all(good in text for good, _ in SWAPS):
        return "correct"
    if all(bad in text for _, bad in SWAPS):
        return "broken"
    return "unrecognised"


def apply(direction: str) -> int:
    text = TARGET.read_text(encoding="utf-8")
    now = state(text)

    if now == "unrecognised":
        print(
            f"{TARGET.name} does not look like either the fixed or the broken "
            f"version. Refusing to edit it — `git checkout conserved.py` first.",
            file=sys.stderr,
        )
        return 2

    want = "broken" if direction == "break" else "correct"
    if now == want:
        print(f"already {want}; nothing to do")
        return 0

    for good, bad in SWAPS:
        frm, to = (good, bad) if direction == "break" else (bad, good)
        if text.count(frm) != 1:
            print(f"expected exactly one {frm!r}, found {text.count(frm)}", file=sys.stderr)
            return 2
        text = text.replace(frm, to)

    TARGET.write_text(text, encoding="utf-8")
    print(f"{TARGET.name} is now {want}")
    if want == "broken":
        print("\ntests/test_conserved.py should now fail. Hand it to the crew:\n")
        print("    python -m nanoloop.main harvest --workspace . --run")
    return 0


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    p.add_argument("action", choices=["break", "restore", "status"])
    action = p.parse_args().action
    if action == "status":
        print(state(TARGET.read_text(encoding="utf-8")))
        return 0
    return apply(action)


if __name__ == "__main__":
    raise SystemExit(main())
