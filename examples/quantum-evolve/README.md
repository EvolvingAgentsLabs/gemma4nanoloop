# An AlphaEvolve-shaped loop

`propose N → score all → keep the best → repeat`, with a deterministic
evaluator. It is not what the crew does, and that is the point.

| | |
|---|---|
| **crew** | proposes → the first candidate that **passes** wins → stop. Optimises for *correct*. |
| **this loop** | proposes N → **scores** all → keeps the best → iterates. Optimises for *best subject to correct*. |

The crew already has best-of-N, but it takes the first sample that clears the
gate: for a bug, "correct" **is** the whole requirement. Optimisation has no
such stopping point — every correct candidate is still comparable to the next,
and taking the first throws the search away.

The evaluator is the same idea as `Acceptance.check`, split in two:

```python
valid = Operator(candidate).equiv(Operator(reference))  # a hard gate
score = cost(qc)  # a gradient: 1 per gate, 10 per two-qubit gate
```

An invalid candidate scores zero however short it is. Otherwise the loop learns
that deleting the circuit is an excellent optimisation — and the empty circuit
really is this function's global optimum, which `tests/` now pins as the
counter-example rather than leaving to trust.

**Cost counts by arity, not by gate name.** Plain gate count cannot say what the
example claims matters: a two-qubit gate is roughly an order of magnitude worse
on real hardware, and three gates with one CX are not three gates with two. It
also closes a hole — nothing escapes the count by calling itself `cz`.

## Result

```
original     10 gates, cost 37, depth 8
transpiler    3 gates, cost 12, depth 3   <- the bar
evolved       3 gates, cost 12   in 3 model calls and 9 s   -> MATCHES the transpiler
```

It found the reduction that requires **commutation**, not merely adjacent
cancellation: the two `rz` were separated by a `cx`, and they only merge into
`rz(0.7)` if you know an `rz` on the control commutes through the `cx`.

```python
qc.h(0)
qc.rz(0.7, 0)
qc.cx(0, 1)  # 0.3 + 0.4 = 0.7
```

Unitary identical, verified separately.

## The most instructive failure

The first run produced **0/9 valid candidates**. The model emitted gibberish:

```python
qc.h(qubit_0_index_placeholder_for_logic_only_to_be_replaced_by__real_indices_0_and_1)
qc.cx(0, 0_placeholder_for_logic_only_to_be_redistributed-0_and_1)
```

That was **my prompt**, not the model. It said *"return the complete new body of
build() as a Python module"* — ambiguous between the body and the module.
Rewritten to *"output one complete Python file… every qubit index is a literal
integer: 0 or 1. Never write a placeholder name where a number belongs"*, it
worked first try.

**0/9 → 2/3 valid candidates on wording alone.** Before concluding that a small
model cannot do a task, rule out that the prompt cannot.

## 12B local vs 26B cloud: the first time size mattered

Run end to end with `run --optimize` against both backends:

| model | metric | result |
|---|---|---|
| `gemma-4-26b` (cloud) | gate count | **10 → 3** gates, matched the transpiler |
| `gemma4:12b` (local) | gate count | **10 → 7** gates, then plateaus |
| `gemma4:12b` (local) | **cost, re-measured** | **cost 37 → 12, matched the transpiler** — 6 model calls, 111 s |

The last row is the current metric and the documented command
(`--generations 3 --candidates 3`). It found the optimum on the sixth candidate:
five came back `unitary changed`, then one landed exactly on `rz(0.7)`.

The metric changed underneath the first two rows (gate count → arity-weighted
cost), so those numbers are not directly comparable to the third — trap 9 in
`NEXT-STEPS.md`. The verdict is: **matched**.

### And a smaller correction, worth keeping

The first re-measurement reported **0 of 4 candidates valid** and was written up
as the 12B doing worse than before. It had been run at
`--generations 2 --candidates 2` — a smaller search than the command this README
documents — and then compared against numbers produced by the larger one. The
model was not worse; it was given four samples instead of nine on a task whose
whole point is that finding the commutation takes more than one try.

Read `--candidates` as part of the measurement, not as a convenience knob.

The 12B removed the redundant `h` gates and left `cx x3` and `x x2` untouched.
Correct — the unitary is preserved — but incomplete. Run twice more, no
candidate beat 7 and the step failed, which is the incumbent baseline doing its
job instead of reporting a flat result as success.

**This matters beyond the example.** Everywhere else in the project the 12B and
the 26B tied: 100% anchor-hit both, and the A/B concluded a bigger model bought
no quality. Optimisation is **the first place model size measurably shows up**.
That makes sense: searching a space of rewrites is a different task from
applying a named rule to a named error.

## Brought into the crew: `--optimize`

The pattern no longer lives only in this script. `nanoloop run --optimize FILE`
takes a file defining `score(workspace) -> float | None` (**lower is better**):

```
without a scorer   first candidate that passes -> stop        (1 call typical)
with a scorer      score all N, keep the best                 (always N calls)
```

Two things the implementation had to learn, both found by running it:

1. **It requires a snapshot.** Without a clean tree per candidate, candidate 2
   sees candidate 1's edit, its anchor no longer matches, and the population
   collapses into one accumulating chain. It now refuses with a message saying
   so rather than misbehaving quietly.
2. **It needs the incumbent.** The first version picked the best *candidate* and
   declared victory even when none beat the starting point — a run reported
   `1/1 steps solved` having gone from 10 gates to 10. An optimisation that does
   not optimise is a failure, not a success with a flat result.

## A note on the backend

Runs against AI Studio degraded after a day of use: ~180 s per call and empty
completions, where the morning saw 4 s. `probe` still answered, so this was
throttling rather than an outage. The local 12B has no such problem and is the
project's actual target.

## Running it

```bash
python examples/quantum-evolve/evolve.py --generations 3 --candidates 3
```

Requires `qiskit`. Writes `best.py` **only when a candidate actually beats the
starting circuit** — writing unconditionally meant a run that improved nothing
overwrote the committed 3-gate result with the 10-gate original, and there was
no test to notice.

Candidates are evaluated in a **subprocess with a 30 s timeout**. They used to be
`exec`'d in this process, so a generated `while True:` hung the run forever,
indistinguishable from a slow model. `crew.run_check` already had this right:
model-written code gets a boundary and a clock.
