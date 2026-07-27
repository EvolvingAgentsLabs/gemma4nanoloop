# Examples

Three worked examples. They are not demos of the crew so much as demos of the
thing the crew depends on: **an oracle** — some way to decide, without asking a
model's opinion, whether the work is right.

`AUTONOMY.md` argues that autonomy is limited by the density of verifiable
signal around the model, not by the model's intelligence. These are the places
where that claim can actually be tested, because the signal is exact.

| example | the oracle | what it shows |
|---|---|---|
| [`bioinformatics-eyeless`](bioinformatics-eyeless/) | a conserved protein domain, documented and stable | the discovery itself, runnable offline in seconds |
| [`quantum-circuit-opt`](quantum-circuit-opt/) | unitary equivalence, mathematically exact | acceptance criteria a stub cannot satisfy |
| [`quantum-evolve`](quantum-evolve/) | equivalence as a gate, gate count as a gradient | scored search — now in the crew as `run --optimize` |

---

## Start here: the fly's eye

![Two protein sequences with two conserved blocks](../docs/img/eyeless.png)

```bash
python examples/bioinformatics-eyeless/discover.py
```

A fly gene called `eyeless`. A human disease called `aniridia`. The names share
nothing. The sequences share **133 residues at 93% identity**.

It is the exercise that opens *Developing Bioinformatics Computer Skills*
(O'Reilly, 2001) — front-page science in 1995, now two public sequences and a
few seconds on a laptop. No network, no BLAST binary, no account.

---

## What these examples are honest about

Each README states plainly where the approach does **not** win:

- **quantum-circuit-opt** — Qiskit's own transpiler does the same optimisation
  in 17 ms with guarantees a language model cannot offer. The example is worth
  reading for the criterion, not as a recommendation to optimise circuits with
  an agent.
- **quantum-evolve** — the only place in the whole project where model size
  measurably mattered. Everywhere else the local 12B and the cloud 26B tied at
  100% anchor-hit; searching a space of rewrites is a different task.
- **bioinformatics-eyeless** — the book's own coordinates no longer reproduce.
  The database entries changed underneath it in 25 years, which is exactly why
  the sequences are vendored into the repo.

That last point generalises: an example that depends on a live service stops
meaning the same thing without telling you.

## Running any of them

```bash
uv pip install -e ".[dev]"
uv pip install qiskit biopython      # only what the examples need
```

Each directory carries its own README with the measured numbers per model.
