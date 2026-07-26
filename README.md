# gemma4nanoloop

An autonomous engineering crew that runs entirely on a local **Gemma 4 12B**,
on a 16 GB fanless MacBook Air M4.

Fork of [nanoLoop](https://github.com/ismaelfaro/nanoLoop) (Apache-2.0). The
port is mostly **subtraction**: the DeepAgents orchestrator is gone, replaced by
a phase-scoped state machine that never asks the model to do the things a 12B
does badly.

- **`PLAN.md`** — what to build and why (architecture decisions D1–D8).
- **`IMPLEMENTATION.md`** — order of work, verified ground truth, open questions.

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
```

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
  crew.py           state machine: Step/Plan/Edit, gates, apply_edit, build_step, Ctx
  anchors.py        exact + fuzzy anchor location — the Phase 2 viability mechanism
  planner.py        propose_plan(goal, repo_map) -> Plan
  proposer.py       propose(step, ctx, feedback, temp) -> Edit
  model_ollama.py   OpenAI-compatible client for Ollama / LiteRT-LM
  calllog.py        append-only JSONL call log
  snapshot.py       clean tree per candidate (D8)
  recall.py         EmbeddingGemma semantic recall over ./Memory
  repomap.py        file tree + first docstring, never contents
  session.py memory.py skills.py frontmatter.py tools.py    (from nanoLoop)
Skills/             scaffold-fastapi, add-endpoint, setup-pytest
eval/               fixtures, measurement harnesses, fixture-repo
```

## Status

First commit complete: **103 tests green** (23 upstream + 80 new), `ruff check`
and `ruff format --check` clean.

Measured against the live model (see `IMPLEMENTATION.md` §0a):

| | |
|---|---|
| **anchor-hit rate (Phase 2 viability gate)** | **100% exact, 12/12** |
| model calls per completed step | median **1.0** — greedy succeeds |
| structured-output parse rate | 100% |
| latency per call | p50 **17.5 s**, p90 28.4 s |
| reasoning tokens per call | **0** (see below) |

**The single biggest runtime finding:** Gemma 4 is a *reasoning* model, and
Ollama's `/v1` endpoint cannot turn that off. Same prompt, `/v1` = 222 s vs
native `/api/chat` = 27 s — an **8× penalty**, with `content` arriving empty
while the model spends thousands of tokens thinking. The client uses the native
transport with `think:false`; `calllog` records `thinking_chars` so any
regression is attributable at a glance.

Still outstanding: the ≥50-fixture anchor measurement, the Phase 4 thermal soak
at 30+ steps, and LiteRT-LM (not yet serving). See `IMPLEMENTATION.md` §12.

## License

Apache-2.0. See `LICENSE` and `NOTICE`.
