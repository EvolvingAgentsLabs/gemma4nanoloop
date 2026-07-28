# The fly's eye experiment

![Two protein ribbons with two conserved blocks aligned](../../docs/img/eyeless.png)

```bash
python discover.py
```

A fly gene called `eyeless` and a human disease called `aniridia`. The names
share **nothing**. The sequences share **133 residues at 93% identity**:

![59 of 60 residues identical between fly and human](../../docs/img/alignment.png)

```
    fly    HSGVNQLGGVFVGGRPLPDSTRQKIVELAHSGARPCDISRILQVSNGCVSKILGRYYETG
           |||||||||||| |||||||||||||||||||||||||||||||||||||||||||||||
    human  HSGVNQLGGVFVNGRPLPDSTRQKIVELAHSGARPCDISRILQVSNGCVSKILGRYYETG
```

*(rendered by `tools/render_alignment.py` from the vendored sequences — every
character comes from the data)*

One difference in sixty positions, between two lineages separated by roughly
600 million years.

This is the exercise that opens *Developing Bioinformatics Computer Skills*
(Gibas & Jambeck, O'Reilly 2001), the book that taught a generation of
biologists to turn a question into a computational experiment.

## What it finds

```
       eyeless           PAX6    length   identity   what it is
    57-189         5-137       133         93%   paired domain — grips regulatory DNA
   402-547       182-327       146         60%   homeodomain — the second DNA grip
   598-629       371-402        32         19%   linker, far freer to mutate
```

The revealing part is not *that* they match: it is **where**. What survives
intact is precisely the piece that touches DNA, because changing it breaks the
protein. Everything in between has drifted freely — nothing was watching it.

## Could it be chance? Don't assert it — measure it

Shuffle PAX6: same amino acids, same frequencies, order destroyed. That is the
null hypothesis made concrete, and any two sequences of this composition will
align to *something*. A hundred shuffles show you what that something is.

```
    35 │██████████████ 6
    38 │████████████████████████████████ 14
    41 │██████████████████████████████████████████████ 20
    44 │██████████████████████████████████████████████ 20
    47 │█████████████████████████ 11
    50 │██████████████████████████████████ 15
    53 │██████████████ 6
    56 │█████████ 4
    59 │██ 1
    68 │███████ 3
       │
   952 │▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓▓  <- the real alignment
```

**133 standard deviations out, 13.4x the best of 100 shuffles**, in 0.7 seconds.
This is the idea BLAST turns into E-values; done here by brute force, which is
slower and much easier to believe.

`significance.py` is honest about what that number does and does not license:
the z-score assumes a normal null, while real local-alignment scores follow an
extreme-value distribution with a fatter right tail (you can see it in the bin
at 68). At 133 sigma the distinction changes nothing; at 3 it would change
everything.

That licensed the proposal that `eyeless` and the aniridia gene descend from a
common ancestral gene: the same switch turns on a fly's eye and yours. It was
later confirmed experimentally — mouse PAX6, placed in a fly, induces eyes.

**And a warning the book stresses:** sequence similarity produces a hypothesis,
not a proof. Confirming it takes real experiments.

## Why this is within anyone's reach

This was front-page science in 1995. Today: two public sequences, thirty lines
of Python, a few seconds on a laptop. No network, no BLAST binary, no account —
the sequences are vendored in `sequences.py`.

**The barrier is no longer the data or the compute. It is knowing what to ask.**

Which is exactly where an autonomous crew can help, and where it cannot: it can
write and repair the analysis code for you. The question is yours.

## The book's numbers do NOT reproduce, and that teaches something

The book reported the paired domain at eyeless 24–169 against a **447 aa** human
PAX6 from the PIR database. UniProt today gives **422 aa**, and the coordinates
come out at 57–189 / 5–137.

The biology is unchanged; the database entries moved in 25 years. That is why
the sequences are **vendored** into the repo rather than downloaded: an example
that depends on a live database stops meaning the same thing without telling
you. This is computational reproducibility — the thing chapter 2 of the book
insisted on teaching.

## Two exercises for the crew

See [`exercise.md`](exercise.md). They are deliberately different shapes:

1. **Repair.** `python exercise.py break` reintroduces the off-by-one, and
   `harvest` finds it, writes its own goal and fixes it — the failing test is
   the oracle, so you write nothing at all.
2. **Build.** Delete `significance.py` and make the crew write it, with an
   acceptance criterion **you** wrote (`--accept`) that exercises the biology
   rather than checking a name exists.

## Files

```
discover.py     the runnable narration — start here
conserved.py    the analysis: local alignment and conserved blocks
significance.py is the alignment better than chance? measured, not asserted
sequences.py    PAX6_HUMAN and EYELESS_DROME, vendored from UniProt
tests/          the oracles: the paired domain, and the null that must say no
exercise.py     break / restore, to hand the repo to the crew in one command
exercise.md     both exercises, with what the local 12B actually did
```

Requires `biopython`.
