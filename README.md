# gemma4nanoloop

An autonomous engineering crew that runs entirely on a local **Gemma 4 12B**,
on a 16 GB fanless MacBook Air M4.

Fork of [nanoLoop](https://github.com/ismaelfaro/nanoLoop) (Apache-2.0). The
port is mostly **subtraction**: the DeepAgents orchestrator is gone, replaced by
a phase-scoped state machine that never asks the model to do the things a 12B
does badly.

- **`PLAN.md`** — what to build and why (architecture decisions D1–D8).
- **`IMPLEMENTATION.md`** — order of work, verified ground truth, measured findings.
- **`GAPS.md`** — what is still missing for a real task, measured and prioritised.
- **`NEXT-STEPS.md`** — where it was left, what to do next, and the traps that already cost hours.
- **`AUTONOMY.md`** — the thesis for getting from supervised executor to something you can leave alone.

## The core idea

A frontier-model harness offers the model 17 tools at ~5,548 tokens of schema per
call, four of which are semantic duplicates. Binding tools per phase instead:

| phase | tools | schema cost |
|---|---|---|
| plan | 0 | ~0 tok |
| build | 2 | ~374 tok |
| repair | 1 | ~34 tok |
| test | 0 | ~0 tok |
| ship | 1 | ~817 tok |

Peak per call: **~817 tok, down from ~5,548 (−85%)**.

Everything else follows from the same instinct — take load off the model:

- The **sequence** is a graph in code, not a model decision (D1).
- The **plan** is typed JSON that code iterates, turning long-horizon reasoning
  into horizon-1 reasoning done N times (D2).
- **Verification** is `ruff`/`pytest`, never a model judging a diff (D3).
- **Edits** are anchor-based and raise on ambiguity rather than guessing (D4).
- **Skills** are catalog entries (~23 tok) with deterministic executors (D5).
- **Context** is compiled fresh each turn — never the transcript (D6).

Three things were added after running it for real, each closing a way the loop
could report success while the work was not done:

- **Acceptance criteria are executable.** A criterion is Python that exercises
  the symbol and asserts the result, not a name that must exist — a `by_tag()`
  returning `[]` satisfied the old check. Write your own with `--accept`.
- **Unmet criteria trigger a bounded replan**, with a freshly built repo map so
  the second pass sees what already exists instead of redoing it.
- **Preflight refuses a repo that is already red**, because the repair loop
  cannot tell a bad edit from a broken repo and will burn its attempts trying.

## Setup

```bash
uv venv --python 3.12 && uv pip install -e ".[dev]"
source ./env.sh            # Ollama config; restart `ollama serve` after
ollama pull gemma4:12b
ollama pull embeddinggemma # for semantic recall (Phase 6)
```

## Use

```bash
# Phase 0 — runtime verification
python -m nanoloop.main probe --backend ollama,litert
python -m nanoloop.main verify-ctx --num-ctx 2048   # prove num_ctx is honored

# Phase 1 — plan only, no edits
python -m nanoloop.main plan "add a remove() method" --workspace eval/fixture-repo

# Full loop
python -m nanoloop.main run "add a remove() method and a test" \
    --workspace eval/fixture-repo --interactive

# Read work off the repo itself — no goal, no criteria, no human
python -m nanoloop.main harvest --workspace <repo>          # list what it found
python -m nanoloop.main harvest --workspace <repo> --run    # and work through it

# With acceptance criteria you wrote (recommended for anything real)
python -m nanoloop.main run "add a by_tag(tag) method to Store" \
    --workspace eval/fixture-repo --accept criteria.json
```

`criteria.json` — each `check` runs from the repo root and must exit 0:

```json
[{"symbol": "by_tag",
  "file": "todo/store.py",
  "check": "from todo.store import Store\ns = Store()\ns.add('a', ['x'])\nassert [i.title for i in s.by_tag('x')] == ['a']\n"}]
```

```bash
# Score every candidate and keep the BEST, instead of the first that passes
python -m nanoloop.main run "make it faster" --workspace repo \
    --optimize scorer.py --n-candidates 3
```

`scorer.py` defines `score(workspace) -> float | None`, lower is better. This
inverts the economics on purpose: a bug fix stops at the first correct
candidate, an optimisation has no such stopping point, so a scored run always
spends `--n-candidates` calls and keeps the best that beats the incumbent.

Useful flags: `--max-replans N`, `--skip-preflight`, `--n-candidates N`,
`--snapshot copy|git`, and a per-task budget: `--max-calls N`, `--max-seconds N`,
`--max-tokens N` (running out is reported as "stopped on budget", not as a
failure of the work). Env: `NANOLOOP_BACKEND=ollama|litert|aistudio`,
`NANOLOOP_REQUIRE_CHECKS=1` (a criterion with no check counts as unmet).

## Examples

Two worked examples live in `examples/`, both built around quantum circuits —
not because the crew is a quantum tool, but because quantum software has
unusually good **oracles**, and an oracle is what this project argues autonomy
is actually limited by.

### `examples/quantum-circuit-opt` — acceptance criteria with an exact oracle

The best acceptance criterion in the repo. Dual and mathematically decidable:

```python
assert Operator(prepare_state()).equiv(Operator(ref))   # same unitary
assert qc.count_ops().get("cx", 0) <= 1                 # and fewer gates
```

No stub can satisfy it. Reliability is **not** the same on both models, and the
difference is worth knowing before you trust it:

| model | result |
|---|---|
| `gemma-4-26b` (cloud) | solved, 3 model calls, 26 s |
| `gemma4:12b` (local) | **2 of 3 runs solved**; the third exhausted its budget with the circuit untouched |

### `examples/quantum-evolve` — an AlphaEvolve-shaped loop

`propose N → score all → keep the best → repeat`, with unitary equivalence as a
hard gate and gate count as the gradient. The selection strategy it demonstrates
is now available in the crew itself as `run --optimize`.

| model | result | optimum |
|---|---|---|
| `gemma-4-26b` (cloud) | **10 → 3 gates**, matching `transpile(optimization_level=3)` | 3 |
| `gemma4:12b` (local) | 9 → 7, then plateaus | 3 |

**This is the only place in the project where model size measurably mattered.**
Everywhere else the 12B and the 26B tied — anchor-hit 100% both. Searching a
space of rewrites is a different task from applying a named rule to a named
error.

And the honest caveat, in the example's own README: Qiskit's transpiler does the
same optimisation in **17 ms** with guarantees. The pattern is what transfers —
to problems that have no transpiler.

## Eval harness

Built in Phase 0, run on every change. "It works" otherwise means "it worked on
the three things I tried."

```bash
python -m eval.run_anchors --fixtures eval/anchors.jsonl   # Phase 2 viability gate
python -m eval.run_plans                                   # Phase 1
python -m eval.run_recall --reindex                        # Phase 6
python -m eval.report --log calls.jsonl                    # all runtime metrics
```

`eval.report` reads only `calls.jsonl`, the append-only log of every model call.
That log is the regression suite when the runtime changes.

## Layout

```
nanoloop/
  crew.py           state machine: run_goal/run_plan/build_step, gates, preflight,
                    apply_edit, acceptance verification, symbol-centred slicing
  anchors.py        exact + fuzzy anchor location — the Phase 2 viability mechanism
  planner.py        propose_plan(goal, repo_map, gaps) -> Plan  (+ replan prompt)
  proposer.py       propose() for edits, propose_new_file() for new modules
  model_ollama.py   client for Ollama (native), LiteRT-LM and AI Studio
  calllog.py        append-only JSONL call log
  snapshot.py       clean tree per candidate (D8)
  recall.py         EmbeddingGemma semantic recall over ./Memory
  repomap.py        file tree + docstring + defined symbols per file
  harvest.py        tasks read off failing pytest/mypy/ruff, oracle attached
  deliver.py        branch + commit per task + report generated from the log
  budget.py         per-task ceiling; running out is a result, not a crash
  failmem.py        what failed before, superseded by any later success
Skills/             scaffold-fastapi, add-endpoint, setup-pytest
examples/           quantum-circuit-opt (oracles), quantum-evolve (scored search)
  session.py memory.py skills.py frontmatter.py tools.py    (from nanoLoop)
eval/               fixtures, measurement harnesses, fixture-repo
```

## Status

**275 tests green**, `ruff check` and `ruff format --check` clean. Everything
below was measured against a live model, not reasoned about.

| | |
|---|---|
| anchor-hit rate | **100% exact (12/12)**, identical on 12B local and 26B cloud |
| model calls per completed step | median **1.0** — greedy succeeds |
| structured-output parse rate | 100% |
| full loop, multi-step | 3/3 steps, 4 calls, 1 repair |
| scaffold a FastAPI service from nothing | 3/3 steps, **0 model calls** (all skills) |
| edit a 22 KB file (symbol past the old window) | 1 step, 1 call, 0 repairs |
| replan after an unmet criterion | 2 rounds, criterion satisfied |
| **harvest: fix a failing test unsupervised** | **1/1 solved, 1 model call** — no goal or criteria written by hand |
| semantic recall@1 vs keyword | **0.850 vs 0.000** (recall@5 saturates 1.0/1.0) |
| quantum circuit optimisation | 10 → 3 gates (26B); 9 → 7 (12B) — see Examples |
| latency per call | ~30 s local (12B) / ~4 s cloud (26B) |
| reasoning tokens per call | **0** — see below |

**The biggest runtime finding:** Gemma 4 is a *reasoning* model and Ollama's
`/v1` cannot turn it off. Same prompt: `/v1` 222 s vs native `/api/chat` 27 s —
an **8× penalty**, with `content` arriving empty while the model spends
thousands of tokens thinking. The client uses the native transport with
`think:false`, and `calllog` records `thinking_chars` so a regression is
attributable at a glance.

**The most instructive bug:** `Step.defines` and `Plan.acceptance` were both
inert for a while. Pydantic omits any field with a `default=` from the JSON
Schema's `required` list, so constrained decoding treated them as optional and
the model never emitted them — two verification mechanisms that appeared to run
and could never fail. `schema_of()` now requires every field.

### What it can do today

Small, verifiable changes to a Python repo with tests: add a method, a
parameter, an endpoint. Scaffolding via skills. It runs unattended — gates and
snapshots mean nothing broken reaches disk.

### What it still cannot do

See `GAPS.md` for the measured list. The ones that bite first: whole-file
generation is fragile even on the 26B (anchored edits are ~100%, new files are
not); the planner emits 1–5 steps for the same goal across runs; each step sees
one file, so a cross-file break is only caught if tests already cover it; and
the crew cannot install dependencies. The Phase 4 thermal soak on the fanless
Air has still not been run.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
