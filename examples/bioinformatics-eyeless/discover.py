"""The fly's eye experiment, runnable on your laptop.

    python discover.py

Reproduces the exercise that opens *Developing Bioinformatics Computer Skills*
(Gibas & Jambeck, O'Reilly 2001): discovering, without knowing any biology, that
a fly gene and a human eye disease are the same evolutionary story.

No network, no BLAST installed, no account anywhere. Two public sequences and an
algorithm from 1981.
"""

from __future__ import annotations

from conserved import align, conserved_blocks
from sequences import EYELESS_DROME, PAX6_HUMAN
from significance import DEFAULT_TRIALS, shuffled_scores, significance, verdict

# NCBI places these domains in human PAX6. They are used only to LABEL what the
# alignment finds on its own — never to find it.
DOMAINS = [
    (4, 136, "paired domain", "grips regulatory DNA"),
    (208, 267, "homeodomain", "the second DNA grip"),
]


def label(subject_start: int, subject_end: int) -> str:
    for lo, hi, name, what in DOMAINS:
        if subject_start <= hi and lo <= subject_end:
            return f"{name} — {what}"
    return "linker, far freer to mutate"


def rule(char: str = "─") -> None:
    print(char * 72)


def histogram(values: list[float], real: float, width: int = 46, bins: int = 12) -> None:
    """Draw the null distribution and where the real score falls.

    The point of showing it rather than only reporting a z-score: you can see
    that the two are not on the same scale at all, which is more convincing than
    any number and impossible to misread.
    """
    lo, hi = min(values), max(values)
    span = (hi - lo) or 1.0
    counts = [0] * bins
    for v in values:
        counts[min(int((v - lo) / span * bins), bins - 1)] += 1
    tallest = max(counts) or 1
    for i, count in enumerate(counts):
        edge = lo + span * i / bins
        bar = "█" * round(width * count / tallest)
        print(f"    {edge:>6.0f} │{bar} {count or ''}".rstrip())
    print(f"    {'':>6} │")
    print(f"    {real:>6.0f} │{'▓' * width}  <- the real alignment, off the chart")


def main() -> None:
    rule("═")
    print("THE FLY'S EYE EXPERIMENT")
    rule("═")

    print("""
Two facts, known separately for decades:

  · The fruit fly has a gene called `eyeless`. Break it and you get flies
    with no eyes.
  · Some people are born with `aniridia`: no iris. It was known to be
    inherited.

Nothing in those two names suggests they are related. No text search, no
literature index, no gene catalogue would ever put them together:
""")
    fly, human = "eyeless", "aniridia"
    print(f"    does '{fly}' contain '{human}'? {human in fly}")
    print(f"    does '{human}' contain '{fly}'? {fly in human}")
    print("    words in common: none\n")

    print("But proteins are not names. They are sequences:\n")
    print(f"    eyeless (Drosophila)  {len(EYELESS_DROME):>4} amino acids")
    print(f"      {EYELESS_DROME[:58]}...")
    print(f"    PAX6 (human)          {len(PAX6_HUMAN):>4} amino acids")
    print(f"      {PAX6_HUMAN[:58]}...\n")

    print("They say nothing to the naked eye either. Let the computer compare them.\n")
    rule()

    alignment = align(EYELESS_DROME, PAX6_HUMAN)
    blocks = conserved_blocks(EYELESS_DROME, PAX6_HUMAN)
    total = sum(b["length"] for b in blocks)
    matched = sum(b["identities"] for b in blocks)

    print(f"LOCAL ALIGNMENT (Smith–Waterman, BLOSUM62)   score = {alignment.score:.0f}\n")
    print(f"{'eyeless':>14}   {'PAX6':>12}   {'length':>6} {'identity':>10}   what it is")
    for b in blocks:
        print(
            f"{b['query_start']:>6}-{b['query_end']:<7} "
            f"{b['subject_start']:>5}-{b['subject_end']:<6} "
            f"{b['length']:>6} {b['percent_identity']:>9.0f}%   "
            f"{label(b['subject_start'], b['subject_end'])}"
        )

    best = max(blocks, key=lambda b: b["percent_identity"])
    print(f"\n{matched} of {total} aligned residues are IDENTICAL.")
    print(
        f"Best block: {best['length']} consecutive residues at "
        f"{best['percent_identity']:.0f}% identity.\n"
    )

    print("The first 60 residues of that block, one above the other:\n")
    q = EYELESS_DROME[best["query_start"] - 1 : best["query_end"]][:60]
    s = PAX6_HUMAN[best["subject_start"] - 1 : best["subject_end"]][:60]
    bar = "".join("|" if a == b else " " for a, b in zip(q, s))
    print(f"    fly    {q}")
    print(f"           {bar}")
    print(f"    human  {s}\n")

    rule()
    print("""
BUT COULD THIS BE CHANCE?

That is the question, and it has an answer you can compute rather than assert.
Take PAX6 and SHUFFLE it: same amino acids, same frequencies, order destroyed.
Any two sequences of this length and composition will align to *something*. A
hundred shuffles show you what that something looks like when there is no shared
ancestry — the null hypothesis, built in front of you.
""")
    sig = significance(EYELESS_DROME, PAX6_HUMAN)
    null = shuffled_scores(EYELESS_DROME, PAX6_HUMAN, DEFAULT_TRIALS)
    print(f"    {DEFAULT_TRIALS} shuffled PAX6 sequences, aligned against the real eyeless:\n")
    histogram(null, sig["score"])
    print()
    for line in verdict(sig).splitlines():
        print(f"    {line}")
    print()
    print(
        "    (This is what BLAST's E-value estimates analytically. Here it is done\n"
        "     by brute force, which is slower and much easier to believe.)\n"
    )

    rule()
    print("""
WHAT IT MEANS

So it is not chance — that is now measured, not assumed. Between
a fly and a human, separated by some 600 million years, what survives intact is
exactly the piece that grips DNA — because changing it breaks the protein. What
lies between has drifted freely: nothing was watching it.

So `eyeless` and the aniridia gene descend from the same ancestral gene. The
same switch that turns on a fly's eye turns on yours.

And a warning the book stresses, worth repeating: this is a strong HYPOTHESIS,
not a proof. Sequence similarity suggests shared function; confirming it takes
experiments. (In this case they were done: mouse PAX6, placed in a fly, induces
eyes.)

WHAT IS GENUINELY STRIKING

This was front-page science in 1995. Today it is two public downloads, thirty
lines of Python and a few seconds on a laptop. The barrier to this kind of
question is no longer access to the data or the computing power: it is knowing
what to ask.
""")
    rule("═")


if __name__ == "__main__":
    main()
