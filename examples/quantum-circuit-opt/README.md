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

| model | criterion | result |
|---|---|---|
| `gemma-4-26b-a4b-it` (cloud) | old (gate names) | solved: 2/2 steps, 3 model calls, 26 s |
| `gemma4:12b` (local) | old (gate names) | **2 of 3** runs solved |
| `gemma4:12b` (local) | **current (cost)** | **3 of 3** runs solved — 1 step, 2 model calls, ~134 s each |

The last row is the honest one to cite: it is today's code against today's
criterion, and the tighter check did not cost the 12B anything. Five of six runs
across both measurements. That is a small sample and it is not a reliability
claim — but "the 12B is inconsistent on this task" now rests on a single old
failure whose conditions are no longer reproducible, and should be read that way.

### The re-measurement that measured a bug in its own harness

Worth recording, because it very nearly went into this table as a fact about the
model. Tightening the criterion above meant re-running these numbers, and the
first attempt came back **0 of 3**, every run exhausting its budget with the
circuit untouched.

The tempting explanations were all wrong, and all of them were checked:

| hypothesis | verdict |
|---|---|
| thermal drift under sustained load | **no** — p50 31 s the day before, 35–38 s now |
| stale processes contending for the model | **no** — one process |
| the stricter criterion rejecting partial answers | **no** — the failures leave three `cx`, which the old check rejects too |
| **the harness changed** | **yes** |

The decisive experiment was the cheap one, and it should have come first:
**check out the previous day's code and run the same task with the same model.**
It solved it 2 out of 2, in 3 calls and ~104 s.

The culprit was a test added the same day, in this directory:

```python
def test_the_original_redundant_circuit_fails():
    with pytest.raises(AssertionError):
        run_criterion(circuits.prepare_state())  # the LIVE function
```

It asserts that the circuit under optimisation is still bad. True while the file
is unoptimised — and false the instant the task is done. So the gate went red on
the correct answer, `build_step` reverted the improvement it had just verified,
and the run spent its budget re-solving a problem it had already solved. It
reproduces with no model at all: feed the optimal edit in by hand and the
anchors read `['exact', 'not_found', 'not_found', 'not_found']`.

**A test that asserts "the current state is bad" stops being a test the moment
someone fixes the current state.** Both quantum examples had one; both now build
their inputs explicitly. And both grew the check that would have caught it:
`test_the_gates_stay_green_once_the_task_is_solved` copies the workspace, writes
the optimal answer, and runs the suite there — because an example is only an
example if solving it leaves the gate green.

Re-run after the fix, the 12B solved it **3 times out of 3**. The model was never
the problem being measured.

And a smaller surprise from re-measuring, worth knowing before it costs an
afternoon: **editing this README broke the workspace.** `DEFAULT_GATES` runs
`ruff format --check .`, and ruff formats Python inside Markdown fences — so two
spaces before a comment in the snippet above turned the example red and
`preflight` refused to start. Prose is part of the gate here.

The result is the same one the 26B reaches, and it satisfies the current
criterion as well as the old one:

```
cx: 3 -> 1     x: 2 -> 0     depth: 6 -> 3     unitary identical     3 gates
```

When a run does not land, it spends its budget without touching the circuit and
reports failure, which is the correct behaviour — the historical 1-in-3 failure
ended that way, and so did all three runs against the broken gate. If you are
going to depend on this, raise `--n-candidates` or run the larger model.

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
