# The fly's eye experiment

![Two protein ribbons with two conserved blocks aligned](../../docs/img/eyeless.png)

```bash
python discover.py
```

A fly gene called `eyeless` and a human disease called `aniridia`. The names
share **nothing**. The sequences share **133 residues at 93% identity**:

```
    fly    HSGVNQLGGVFVGGRPLPDSTRQKIVELAHSGARPCDISRILQVSNGCVSKILGRYYETG
           |||||||||||| |||||||||||||||||||||||||||||||||||||||||||||||
    human  HSGVNQLGGVFVNGRPLPDSTRQKIVELAHSGARPCDISRILQVSNGCVSKILGRYYETG
```

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

## The exercise for the crew

See [`exercise.md`](exercise.md): reintroduce the classic off-by-one and let
`harvest` find and fix it on its own. Solved by the **local `gemma4:12b`** in
3 steps and 3 model calls.

## Files

```
discover.py     the runnable narration — start here
conserved.py    the analysis: local alignment and conserved blocks
sequences.py    PAX6_HUMAN and EYELESS_DROME, vendored from UniProt
tests/          the oracle: the paired domain where biology says it is
exercise.md     how to turn this into a task for the crew
```

Requires `biopython`.
