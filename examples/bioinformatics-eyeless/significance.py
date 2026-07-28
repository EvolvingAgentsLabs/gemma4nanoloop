"""Is the alignment better than chance? Measure it, do not assert it.

The claim this whole example rests on is that 133 residues at 93% identity
"cannot be chance". That is the one sentence a reader has to take on faith —
and it does not need to be. The test is older than BLAST and takes under a
second:

    SHUFFLE THE SUBJECT AND ALIGN AGAIN, MANY TIMES.

Shuffling preserves the amino-acid composition exactly and destroys the order.
So the shuffled sequences are the null hypothesis made concrete: same letters,
same frequencies, no shared ancestry. Whatever score they reach is what "chance"
looks like for sequences of this length and composition. If the real score sits
far outside that distribution, similarity by coincidence is not a live option.

This is the idea BLAST turned into E-values. Doing it by brute force here is
slower than the analytical version and much easier to believe, because you can
watch the null distribution being built.

HONEST LIMITS, because a number with a hidden assumption is worse than no
number:

  - The z-score below assumes the null is roughly normal. Real local-alignment
    scores follow an extreme-value (Gumbel) distribution, which has a fatter
    right tail — that is exactly why BLAST fits a Gumbel rather than a normal.
    At 100+ standard deviations the distinction changes nothing about the
    conclusion; at 2 or 3 it would change everything. Do not carry this z-score
    into a borderline case.
  - `p_value` is bounded by the number of shuffles: with n=100 the smallest
    thing observable is "better than all 100", i.e. p < 0.01. It is reported as
    an upper bound, never as a precise small number.
  - Shuffling breaks local composition bias (low-complexity regions), which is a
    real source of spurious alignment scores it therefore cannot warn you about.
"""

from __future__ import annotations

import random
import statistics

from conserved import align

# Fixed so the example gives the same numbers on every machine and in five
# years. The finding is 113 standard deviations wide; it does not depend on the
# seed, and you should change it and re-run to see that for yourself.
DEFAULT_SEED = 0
DEFAULT_TRIALS = 100


def shuffled_scores(
    query: str, subject: str, trials: int = DEFAULT_TRIALS, seed: int = DEFAULT_SEED
) -> list[float]:
    """Alignment scores against `trials` shuffles of `subject`.

    Only the subject is shuffled, and the query is left alone: the null being
    tested is "this particular protein against something with the same
    composition as PAX6", which is the comparison a database search actually
    makes.
    """
    rng = random.Random(seed)
    letters = list(subject)
    scores = []
    for _ in range(trials):
        rng.shuffle(letters)
        scores.append(float(align(query, "".join(letters)).score))
    return scores


def significance(
    query: str, subject: str, trials: int = DEFAULT_TRIALS, seed: int = DEFAULT_SEED
) -> dict:
    """Compare the real alignment score against the shuffled null.

    Returns the real score, the null distribution's shape, how far outside it
    the real score falls, and an upper bound on the p-value.
    """
    real = float(align(query, subject).score)
    null = shuffled_scores(query, subject, trials, seed)
    mean = statistics.mean(null)
    # Population sd, and guarded: a degenerate null (every score identical)
    # would otherwise divide by zero and report `inf` as if it were a finding.
    sd = statistics.pstdev(null)
    at_least_as_good = sum(1 for s in null if s >= real)
    return {
        "score": real,
        "trials": trials,
        "null_mean": round(mean, 1),
        "null_sd": round(sd, 1),
        "null_max": max(null),
        "z_score": round((real - mean) / sd, 1) if sd else None,
        "times_best_shuffle": round(real / max(null), 1) if max(null) else None,
        # An upper bound, not an estimate: with 100 trials and zero hits, the
        # honest statement is "below 1 in 100", not "0.0".
        "p_value_upper_bound": max(at_least_as_good, 1) / trials,
        "beat_every_shuffle": at_least_as_good == 0,
    }


def verdict(result: dict) -> str:
    """Two lines a human can act on, including when the answer is no."""
    if not result["beat_every_shuffle"]:
        return (
            f"NOT significant: {result['p_value_upper_bound']:.0%} of shuffles "
            f"scored as well.\nComposition alone explains this score."
        )
    return (
        f"score {result['score']:.0f} against a null of "
        f"{result['null_mean']:.0f} ± {result['null_sd']:.0f}\n"
        f"{result['z_score']:.0f} standard deviations out, "
        f"{result['times_best_shuffle']:.1f}x the best of "
        f"{result['trials']} shuffles (p < {1 / result['trials']:.2f})"
    )
