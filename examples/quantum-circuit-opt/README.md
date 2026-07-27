# Acceptance criteria with an exact oracle

![A dense circuit thinning out to a few gates, with a verification mark](../../docs/img/quantum.png)

This example exists for **the criterion**, not for the task.

## What it demonstrates

`criteria.json` holds the best acceptance criterion in the project:

```python
assert Operator(prepare_state()).equiv(Operator(ref))  # still the same unitary
assert qc.count_ops().get("cx", 0) <= 1  # and uses fewer gates
```

It is **dual** and **exact**: correctness (unitary equivalence, mathematically
decidable) plus improvement (gate count). Neither half admits an opinion, and no
stub can satisfy it. That is precisely the shape `AUTONOMY.md` argues autonomy
needs.

## Reliability, per model

| model | result |
|---|---|
| `gemma-4-26b-a4b-it` (cloud) | solved: 2/2 steps, 3 model calls, 26 s |
| `gemma4:12b` (local) | **2 of 3 runs** solved; the third exhausted its budget with the circuit untouched |

```
cx: 3 -> 1     x: 2 -> 0     depth: 6 -> 3     unitary identical
```

The 12B is **inconsistent** on this task. When it lands, the result is exactly
the 26B's; when it does not, it spends the budget without touching anything and
reports failure, which is the correct behaviour. If you are going to depend on
this, raise `--n-candidates` or run the larger model.

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
