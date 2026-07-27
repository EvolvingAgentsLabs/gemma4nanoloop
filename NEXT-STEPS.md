# Next steps

State at the close of **2026-07-27**. Written so that someone — including me —
can pick this up cold without rereading the whole history.

Reading order: `README.md` → `GAPS.md` (what is missing, measured) →
`IMPLEMENTATION.md` §0a (findings F1–F10) → `PLAN.md` (decisions D1–D8) →
`AUTONOMY.md` (the thesis).

---

## Where it stands

**275 tests green**, `ruff` clean, published at
`EvolvingAgentsLabs/gemma4nanoloop`.

Closed: every blocker that stood between "supervised executor" and "something
you can leave alone".

| | |
|---|---|
| ~~G1~~ | acceptance criteria are **executable**, and you can write them (`--accept`) |
| ~~G2~~ | slicing **centred on the symbol** (large files are editable) |
| ~~G3~~ | planner is deterministic; its broken paths are repaired |
| ~~G4~~ | whole-file generation measured at **93.8%** |
| ~~G7~~ | **preflight**: refuses to start in an already-broken repo |
| ~~AUTONOMY 1–5~~ | harvest, deliver/PR, budget, failure memory |

---

## What is genuinely left

### 1. Run it against a large real repo 🔴 the honest gap

Everything is measured against a 5-file fixture and small examples. PennyLane
was the first real repo it saw, and it immediately exposed two harness gaps
(unscoped pytest over 52,740 tests; missing optional deps harvested as coding
tasks). Both are fixed — but the crew has still never *worked* a real repo.

Do this before anything else. It is the only thing that would tell you whether
any of the numbers generalise.

### 2. The thermal soak 🔴 never run

*The* open hardware question from PLAN.md Phase 4, still unanswered. Run 30+
steps **from cold** and plot latency against step index; `eval/report.py`
already draws the curve. Soft signal already seen: p50 went from 17.5 s to
29.8 s on identical fixtures after a day of load.

### 3. G5 — repo map filtered by relevance 🟡

~3,260 tokens on this repo, grows linearly, `max_files=300` then truncates. The
planner does not need the whole repo, it needs what is relevant to the goal.
Lexical matching is enough to start; `recall.py` already has EmbeddingGemma if
more is needed.

### 4. G6 — cross-file awareness 🟡 structural

Each step sees ONE file (D6, deliberately). A signature change that breaks
another module is only caught if tests already cover it. **Do not fix this by
widening the context** — PLAN.md §6 calls that an anti-pattern. The tractable
version: warn when a goal touches a symbol referenced elsewhere, using the
`repomap` symbol index.

### 5. Remaining PLAN.md debt

- **≥50 anchor fixtures**: today 12 (100%). A 5-file repo is where anchors are
  easiest.
- **LiteRT-LM**: installed, never served. PLAN.md §7 Q2 is answered for Ollama
  only.
- **`num_ctx` never truly verified** against the server logs; the `verify-ctx`
  command exists, the log check was never done.
- **30 recall queries** (today 10) against a larger corpus. The current one I
  wrote myself, so query and document share an author, which flatters it.
- **The crew cannot install dependencies**, and `DEFAULT_GATES` is hardwired to
  Python.

---

## Traps that already cost hours — do not repeat

1. **Gemma 4 reasons, and `/v1` cannot turn it off.** 222 s vs 27 s on the
   native endpoint, with `content` arriving empty. If strange latency ever
   reappears, look at `thinking_chars` in `calls.jsonl` **before** anything else.
2. **Pydantic drops any field with a `default=` from the schema's `required`**,
   and constrained decoding then treats it as optional: the model does not emit
   it. That left `Step.defines` and `Plan.acceptance` inert — they appeared to
   work and could never fail. `schema_of()` forces `required`; do not undo it.
3. **Reasoning shares the output budget.** A small cap spends itself thinking
   and returns empty with `completion_tokens: 0`. See `PHASE_MAX_TOKENS`.
4. **Green gates ≠ goal achieved.** Hence `Step.defines` and `Plan.acceptance`
   with an executable `check`. A symbol that exists proves nothing.
5. **A met criterion outranks a failed step.** The mirror image of trap 4, and
   just as wrong: under `harvest --deliver` it discarded finished work.
6. **A harness error is indistinguishable from a bad edit** to the repair loop.
   Hence preflight.
7. **An exception meaning STOP must not be catchable by a handler meaning
   RETRY.** `BudgetExhausted` deriving from `RuntimeError` made the planner burn
   three extra calls and report a false diagnosis.

The pattern behind most of these: **a mechanism that appears to run while being
incapable of doing its job.** It has recurred five times. Suspect it first.

---

## Before picking this up

```bash
source ./env.sh                 # Ollama config; restart `ollama serve` after
uv pip install -e ".[dev]"
python -m pytest -q             # expect 275
```

Backends: `NANOLOOP_BACKEND=ollama` (local 12B, ~30 s/call) or `aistudio`
(26B, ~4 s/call, key in `.env`). The A/B measured **the same anchor-hit quality**
on both, so the cloud is for fast iteration — **every acceptance measurement
should close against the local 12B**, which is the real target. Note that AI
Studio throttled hard after a day of use: ~180 s/call and empty completions.

⚠️ **The AI Studio key was exposed in this session's chat history.** It never
entered a commit (verified across the whole history), but rotate it:
https://aistudio.google.com/apikey
