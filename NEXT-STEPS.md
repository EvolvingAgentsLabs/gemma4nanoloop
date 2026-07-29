# Next steps

State at the close of **2026-07-27**. Written so that someone — including me —
can pick this up cold without rereading the whole history.

Reading order: `README.md` → `GAPS.md` (what is missing, measured) →
`IMPLEMENTATION.md` §0a (findings F1–F10) → `PLAN.md` (decisions D1–D8) →
`AUTONOMY.md` (the thesis).

---

## Where it stands

**305 tests green**, `ruff check .` and `ruff format --check .` clean at the
repo root — it now passes its own preflight. Published at
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

## Fixed on 2026-07-28 — a code review of the harness itself

None of these came from GAPS.md. They came from reading the code that runs the
loop rather than the loop's own output, which is where they had all been hiding.

**`--snapshot git` destroyed work.** `GitSnapshot.save()` was `git stash push`,
which reverts the tree to HEAD — a different operation from `CopySnapshot`,
which copies aside and leaves the tree alone. Since the crew commits nothing
until delivery, the save() at the start of step 2 threw step 1's edit into the
stash and out of the working tree. A three-step plan finished with only the last
step applied, and nothing reported a problem, because every gate had passed at
the time it ran. save() now stashes and immediately re-applies; success paths
discard instead of leaking a stash entry per step. Both backends are now
parametrized over the same tests.

**Anchor edits were never syntax-checked.** `_check_syntax` ran only on the
create path, so a `replacement` with an unbalanced paren spliced straight into a
file and only `ruff` noticed, a gate later, as a lint summary instead of a line
and a column. That is exactly the failure the function was written for.

**HTTP refusals were invisible.** `_post` raises `RuntimeError` for 400/401/429;
`chat()` did not catch it, so the failures that carry a reason from the server
were the only ones with no line in `calls.jsonl` and no charge against
`--max-calls`. A misconfigured backend let the planner's three retries run free
and left nothing behind to explain the run.

**`step_index` was always null** — 28/28 records in the shipped `calls.jsonl`.
`build_step` accepted a `step_index` it never forwarded, and `eval/report.py`
groups by it to report repair depth and first-attempt success, so that section
of every report has been silently empty. This is the sixth occurrence of the
pattern named at the bottom of this file, and the telemetry the thermal soak
needs.

**The budget leaked between harvest tasks.** `cmd_run` cleared the process-global
budget only on the happy path, so a rejected plan gate or any raise left the
finished task's spending active for the next one.

**A nested `def` satisfied a step.** `defines_symbol` walked the whole AST, so a
`def by_tag` buried inside another function — unimportable, uncallable — counted
as the step's work. Module level and class bodies now; methods still count.

**`repomap` walked what it was about to throw away.** `rglob("*")` enumerated
and sorted the entire tree, `.venv` included, before applying `SKIP_DIRS`, and
the map is rebuilt every planning round. Pruning during the walk plus one
read+parse per file instead of two: 16,931 entries walked → 165, 0.211s →
0.051s on this repo, byte-identical output.

**One model family, enforced.** `tools/gen_image.py` called `gemini-3-pro-image`
and was the only non-Gemma model in the repo; it is gone. `check_model()` now
refuses anything outside Gemma 4 at `_endpoint()`, the chokepoint every call
path resolves through, including a model set via `NANOLOOP_MODEL`. Embeddings
are the one exception and are checked against the Gemma family, since there is
no Gemma 4 embedder. The `aistudio` backend stays: it is a Google endpoint
serving `gemma-4-26b-a4b-it`, not a Gemini model.

### Then it was pointed at this repo, which found two more

Not a real repo in the sense of item 1 below — but the first time the crew was
aimed at anything other than a fixture, and it paid for itself immediately.

**`harvest` called this repo green while mypy had checked nothing.** `mypy .`
exited **2** with `Duplicate module named "execute"` (two skills, one
`execute.py` each, loaded by path and never imported as modules). A
configuration error is reported without a line number, so the per-error regex
matched nothing, `from_mypy` returned `[]`, and the CLI printed *"nothing to do
— the repo's signals are all green"* over a type checker that had refused to
start. Exit codes are now read properly — 0 clean, 1 work, anything else
`SourceUnavailable` — and a source that could not run is reported before the
verdict, with exit 5 instead of 0. Same for pytest exit 5, which is what a
mis-scoped `--tests` looks like from the outside.

With mypy excluded from `Skills/` and actually running, it found **7 real type
errors in the package**, three of them in code written earlier the same day.
All fixed; `mypy nanoloop/` is clean and is now a source harvest can use.

**The map fed the planner 57 of the crew's own session files.** `.nanoloop/`
was not in `SKIP_DIRS`, so 30% of the map's rows were the runtime's own
bookkeeping, each rendering as `— {`, costing ~664 tokens of the 16,384-token
plan budget and growing with every run. Skipped now, along with a first line
that is only punctuation. 226 rows → 168, ~5,712 → ~5,139 tokens. (The 300-file
truncation limit was NOT being hit: 165 mappable files. G5 is still ahead, not
here.)

Verified against the local 12B afterwards: `probe` ok at 17.6 s, and `plan` on
the real 165-file map returned a schema-valid typed plan.

Smaller: `PHASE_TOOLS` is read through `tools_for()` and documented as the
per-phase ceiling it actually is rather than a binding the loop does not
perform; `skills.parse_params()` replaces two copies of skill-argument parsing
that disagreed about invalid JSON; `tools.WORKDIR` follows `--workspace` instead
of a stale import-time env read; `_read_slice` grows its window in linear time;
`.env.example` is no longer swallowed by `.gitignore`.

Deliberately NOT done: `recall.py` and `memory.py` (~400 lines) are reachable
only from `eval/run_recall.py` and from tools nothing binds, and most of
`session.py` has no live writer. That is a product decision about Phase 6 and
resume, not a code fix — flagged, left alone.

### Then the three examples were audited, and all three oracles were wrong

Not wrong by carelessness. **All three measured something adjacent to what they
claimed to measure**, which is why every one of them had looked fine for months.

- **bioinformatics** reported the homeodomain at **60%** identity. It is 90%.
  `conserved_blocks` returns the ungapped segments of one Smith–Waterman
  alignment; BLAST reports HSPs, which are separate local alignments. Treating
  them as the same glued the domain to flanks at 46% and 35% and printed the
  average. The book's own figure (80 aa at 85%) agrees with 90%, not 60%. A
  third row labelled "linker, far freer to mutate" at 19% turned out to be
  *below the noise floor* — 68 of 74 blocks from shuffled PAX6 beat it.
- **quantum-circuit-opt** called `criteria.json` the project's best criterion.
  Its improvement half counted two gate **names**, so a 23-gate circuit padded
  with cancelling `y` pairs passed it. Now counted by arity and total size, with
  `tests/test_criterion.py` executing the shipped criterion against the circuits
  that used to cheat it.
- **quantum-evolve**'s scorer justified not checking correctness because "the
  gates already refuse anything that changes the unitary". That directory had no
  tests and no `pyproject.toml`. Its optimum, unopposed, is an empty circuit —
  cost 0, measured. What prevented disaster was preflight refusing to start, by
  accident rather than design.

Plus two things that damage state rather than report it: `evolve.py` wrote
`best.py` unconditionally from `target.py`'s contents, so a run that improved
nothing replaced the committed 3-gate result with the 10-gate original; and it
`exec`'d candidates in-process with no timeout, so a generated `while True:`
hung the run forever.

Example tests: 2 → 16 (bio), 2 → 7 (circuit-opt), 0 → 7 (evolve). All three
directories now pass preflight; `quantum-evolve` did not.

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

8. **Two implementations of one concept must be tested against the same
   tests.** `CopySnapshot` and `GitSnapshot` both claimed to be D8 and only one
   was: `save()` meant "copy aside" in one and "revert the tree" in the other.
   Six tests covered the first, one covered `make()` returning the second's
   type, and the difference cost committed-nowhere work. Parametrize.

9. **An oracle is not only something to test — it is something whose change
   expires every measurement made with it.** The quantum criterion counted gate
   *names* (`cx <= 1`, `x == 0`), so a 23-gate circuit padded with cancelling
   `y` pairs passed the check that was supposed to prove improvement. Fixing it
   to count by arity and total size was the easy half. The half that is easy to
   forget: the "2 of 3 runs solved" table two sections below in that README had
   been measured against the *old* check, and nothing in the repo marked it as
   stale. A stricter oracle cannot make old numbers better, only worse — so an
   unmarked table silently becomes optimistic. When you tighten a criterion,
   find everything it ever certified and either re-measure it or label it.

The pattern behind most of these: **a mechanism that appears to run while being
incapable of doing its job.** It has now recurred seven times — `step_index`, a
field written on every call record and never once populated; and `from_mypy`,
which reported a repo green over a type checker that had exited 2 without
checking anything. Suspect it first.

And its mirror image, which trap 9 is about: **a mechanism that did its job
once, under conditions that have since changed.** The first kind is caught by
asking "can this ever fail?". The second only by asking "what did this certify,
and is that still true?".

---

## Before picking this up

```bash
source ./env.sh                 # Ollama config; restart `ollama serve` after
uv pip install -e ".[dev]"
python -m pytest -q             # expect 305
```

Backends: `NANOLOOP_BACKEND=ollama` (local 12B, ~30 s/call) or `aistudio`
(26B, ~4 s/call, key in `.env`). The A/B measured **the same anchor-hit quality**
on both, so the cloud is for fast iteration — **every acceptance measurement
should close against the local 12B**, which is the real target. Note that AI
Studio throttled hard after a day of use: ~180 s/call and empty completions.

⚠️ **The AI Studio key was exposed in this session's chat history.** It never
entered a commit (verified across the whole history), but rotate it:
https://aistudio.google.com/apikey
