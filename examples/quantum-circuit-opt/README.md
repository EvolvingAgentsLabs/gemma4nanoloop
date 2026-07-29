# Acceptance criteria with an exact oracle

![A dense circuit thinning out to a few gates, with a verification mark](../../docs/img/quantum.png)

This example exists for **the criterion**, not for the task.

## What it demonstrates

`criteria.json` holds the best acceptance criterion in the project:

```python
assert Operator(prepare_state()).equiv(Operator(ref))  # same unitary
assert sum(1 for i in qc.data if len(i.qubits) == 2) <= 1  # and cheaper
assert qc.size() <= 3
```

It is **dual** and **exact**: correctness (unitary equivalence, mathematically
decidable) plus improvement (cost). Neither half admits an opinion, and no stub
can satisfy it. That is precisely the shape `AUTONOMY.md` argues autonomy needs.

### Its improvement half used to be a name check, and that was a hole

The check was `count_ops()["cx"] <= 1` and `count_ops()["x"] == 0` — two gate
**names**. A circuit could stay equivalent, get bigger, and pass anyway by
renaming its way out:

| circuit | gates | old criterion |
|---|---|---|
| the intended answer | 3 | passes |
| `cz` + hadamards instead of `cx` | 5 | **passed** |
| the answer plus ten cancelling `y` pairs | 23 | **passed** |

That is G1 from `GAPS.md` inverted: not a stub that does too little, but bloat
that does too much, waved through by a check measuring the wrong thing. Counting
by **arity** and by **total size** closes both, and `tests/test_criterion.py`
now runs the shipped criterion against each of those circuits — an oracle nobody
tests is a claim, not an oracle.

## Reliability, per model

| model | when | result |
|---|---|---|
| `gemma-4-26b-a4b-it` (cloud) | old criterion | solved: 2/2 steps, 3 model calls, 26 s |
| `gemma4:12b` (local) | old criterion | **2 of 3 runs** solved |
| `gemma4:12b` (local) | **current criterion, re-measured** | **0 of 3 runs** solved |

The re-measurement is the honest part, and it does not say what it looks like it
says.

All three failures are identical: the budget ran out at `max_calls=12` after
~320 s with the **circuit untouched** — still three `cx`, still seven gates.
That failure mode fails the *old* criterion too (`cx <= 1` rejects three CNOTs
just as firmly), so **the stricter check is not what caused it**. Whatever
changed, it is not the oracle.

What did change is not established here. Candidates, none of them isolated:
run-to-run variance at n=3 on both sides; the machine's thermal state, which
this project has already measured moving p50 from 17.5 s to 29.8 s after a day
of sustained load; or the conditions of the original measurement, which are no
longer reproducible.

Two things are worth taking away regardless. **The 12B is unreliable on this
task** — that was the original claim and three more failures do not weaken it.
And a table of pass rates is a measurement, not a property: this one sat in the
README for months and was re-run once, at which point it stopped agreeing with
itself. See trap 9 in `NEXT-STEPS.md`.

When it does land, the result is exactly the 26B's, and it satisfies the current
criterion as well as the old one:

```
cx: 3 -> 1     x: 2 -> 0     depth: 6 -> 3     unitary identical     3 gates
```

When it does not, it spends the budget without touching anything and reports
failure, which is the correct behaviour — every run above ended that way. If you
are going to depend on this, raise `--n-candidates` or run the larger model.

A bug surfaced while measuring precisely this: one run **achieved the goal** —
criterion met, tests green, circuit reduced — and still exited 1, because a
later step could not find anything else to remove. Under `harvest --deliver`
that discards finished work instead of committing it. Fixed: a met criterion
outranks a failed step, because the criteria **are** the definition of done.

## What it does NOT demonstrate, and this needs saying

**Qiskit's own transpiler does exactly the same thing in 17 ms:**

```python
transpile(qc, optimization_level=3)  # cx 3->1, x 2->0, 17 ms, provable
```

The crew took **26 seconds and 3 model calls** to arrive where a mature,
deterministic tool gets a thousand times faster, with guarantees a language
model does not offer.

So this is **not** an argument for optimising circuits with an agent. If the
problem has an algorithm, use the algorithm.

## The lesson that does hold

What makes quantum software interesting to this project is not that it needs
agents — it is that it has **unusually good oracles**: unitary equivalence,
stabiliser simulation, known-answer tests. `AUTONOMY.md` argues that autonomy is
limited by the density of verifiable signal, not by the model's intelligence. An
oracle-rich domain is where that claim can be tested seriously.

The value is in **borrowing the oracle**, not in replacing the transpiler.

## Running it

```bash
cp -r examples/quantum-circuit-opt /tmp/qopt
cd /tmp/qopt && git init -q && git add -A && git commit -qm base
python -m nanoloop.main run "Remove the redundant gates from prepare_state" \
    --workspace /tmp/qopt --accept /tmp/qopt/criteria.json --max-calls 12
```

Requires `qiskit` in the environment that runs the gates.
