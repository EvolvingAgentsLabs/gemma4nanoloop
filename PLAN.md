# PLAN — Autonomous engineering crew on local Gemma 4 12B

**Target machine:** MacBook Air M4, 16 GB unified memory, **no fan**
**Model:** `gemma4:12b` (Q4, ~7.6 GB weights)
**Embeddings:** `embeddinggemma` (308M, ~300 MB)
**Runtime:** Ollama for dev loop → LiteRT-LM `serve` for the real path
**Base:** fork of `github.com/ismaelfaro/nanoLoop` (Apache-2.0)

---

## 0. Read this before writing any code

This is a port of an agent harness that was designed for frontier models onto a
12B model running on a thermally-constrained laptop. **Most of the work is
subtraction, not addition.** The original harness fails here for measurable
reasons, listed below with numbers. Do not "improve" the design by adding
capability back — every decision in §2 exists to remove load from the model.

### Measured baseline (already verified, do not re-derive)

Running `create_deep_agent` with nanoLoop's tools and subagents:

```
tools the model sees:          17
tool-schema cost per call:     ~5,548 tokens
orchestrator system prompt:    ~376 tokens
exact name collisions:         read_file, write_file  (nanoLoop vs DeepAgents)
semantic duplicate pairs:      execute↔run_shell, write_todos↔track_task,
                               grep/glob↔recall
```

Tool-choice ambiguity is not cosmetic: queries where a model is torn between two
tools fail roughly 21× more often than queries where it is not. Four duplicate
pairs is a dominant failure mode, not noise.

After phase-scoped binding (already implemented in `crew.py`):

```
plan     0 tools  ~  0 tok
build    2 tools  ~374 tok
repair   1 tool   ~ 34 tok
test     0 tools  ~  0 tok
ship     1 tool   ~817 tok
peak per call: ~817 tok  (was ~5,548)  →  −85%
```

### Hardware constraints that drive everything

| Constraint | Consequence |
|---|---|
| 16 GB unified, ~7.6 GB is weights | Only **one** LLM loaded. No E4B router model. Budget ≤3 GB for KV cache. |
| No fan (Air M4) | Sustained loops throttle. Wall-clock at step 30 ≠ benchmark tok/s. Must be measured, see §5. |
| LiteRT-LM context ceiling: 32K | Never design a phase that needs the whole repo in context. |
| Decode ~15–25 tok/s | A 300-token edit ≈ 15–20 s. Best-of-N is **expensive**. Default `n_candidates=2`, not 3. |

---

## 1. What already exists

Two files are written and verified. Start from them; do not rewrite.

### `nanoloop/crew.py`
Phase-scoped state machine replacing the DeepAgents orchestrator. Contains:
- `Step`, `Plan`, `Edit` — Pydantic models for structured output
- `PHASE_TOOLS`, `PHASE_NUM_CTX` — per-phase binding and context budget
- `run_gate()` — deterministic quality gate, truncates output **from the front**
  (tracebacks carry their payload at the tail)
- `apply_edit()` — anchor-based edit, raises on 0 matches or >1 match
- `build_step()` — greedy attempt → bounded repair loop with exact-error
  feedback → best-of-N only after the greedy sample fails
- `Ctx.render()` — context compiler; renders fresh each turn, never accumulates

Verified end-to-end with a mock model: greedy fails → stderr injected → second
attempt passes. **2 model calls, not 7.**

Known trap already fixed: `gates or DEFAULT_GATES` made `gates=[]` fall through
to defaults. It is `is None` now. Do not reintroduce.

### `nanoloop/model_ollama.py`
`ChatOpenAI` factory pointed at Ollama. The load-bearing detail is `num_ctx`
passed via top-level `extra_body` — inside `model_kwargs` LangChain warns and
**silently drops it**, and Ollama then truncates history without telling you.
In an agent loop that means tool results fall out of the window and the model
re-calls tools it already called.

### nanoLoop upstream
23 tests pass on the fork. `session.py`, `memory.py`, `skills.py`,
`frontmatter.py` and the HITL gates are model-agnostic and well covered — keep
them. `agents.py`, `roles.py` and most of `tools.py` are what gets replaced.

---

## 2. Architecture decisions (with rationale — do not silently revert)

**D1. The orchestrator is a graph, not an LLM.**
Plan→Build→Review→Test→Ship is a fixed sequence. Making it a model decision
costs the `task` tool (meta-tool-use, the hardest thing for a small model) and
forces every tool into one binding. The graph decides the sequence; the model
only decides *within* a step.

**D2. The plan is typed JSON, executed by code.**
The planner emits `Plan(steps=[Step(...)])`. The graph iterates. This converts
long-horizon reasoning into horizon-1 reasoning performed N times, which is the
only kind a 12B does reliably.

**D3. Verification leaves the model.**
`ruff` + `mypy` + `pytest` replace the `reviewer` subagent. A 12B judging a diff
is theater; a 12B repairing a named error is competent. The model sees failures,
never opinions.

**D4. Edits are anchor-based and fail loudly.**
The model never regenerates a whole file — that is where a 12B corrupts. It
emits `(path, anchor, replacement)`. Ambiguous or missing anchor raises, and the
exception text feeds the repair loop. A hard failure you can see beats a silent
corruption you cannot.

**D5. Skills follow the Google AI Edge Gallery model, not nanoLoop's.**
One generic invoker; skills are *data*, not tool schemas. Measured on Google's
11 shipped skills: catalog in the system prompt costs **~23 tokens per skill**
(257 total), full bodies load only on trigger (median ~100 tok, max ~1196).
Preloading every body would cost ~3,079 tokens. Adding a capability costs 23
tokens instead of 300–800.

Corollary: **delete `list_skills`.** nanoLoop injects the catalog into the
system prompt *and* exposes `list_skills` as a tool. The model already has the
catalog; the tool is a wasted slot and a wasted round trip. Google has no such
tool.

Primitives (`read_file`, `execute`, `Edit`) stay tools. Procedures
(`scaffold-fastapi`, `add-endpoint`, `write-migration`, `setup-pytest`) become
skills.

**D6. Context is compiled, not accumulated.**
Each call gets a freshly rendered context: goal, completed steps (titles only),
current step, relevant file slice, last error. Never the transcript.

**D7. Greedy first, diversity second.**
Best-of-N only activates after the greedy sample fails a gate. Typical cost: 1
call. On this hardware `n_candidates=2` — make it configurable and default low.

**D8. Every candidate starts from a clean tree.**
`snapshot`/`restore` = `git stash` or a workspace copy. Without it, edits from
rejected candidates stack.

---

## 3. Scope boundary — what Google's Skills does NOT give us

Google's Agent Skills is evidence that a small model can **route to and
parameterize a capability**. Their published depth metric is 4,000 input tokens
across **2 skills** in under 3 seconds. Their skills are single-shot and
deterministic (compute a hash, query Wikipedia, render a map) — correct by
construction, so the format has no place for "that was wrong, retry."

An engineering crew is 20–50 steps whose output can be wrong in ways only tests
reveal. Google solves **breadth** (many capabilities, constant schema cost).
`crew.py` solves **depth** (long loop with verification). They compose. Do not
mistake one for the other.

Their JS-in-webview executor exists because on-device sandboxes cannot exec.
We have a shell. Copy the *pattern* (declarative skill + deterministic
executor), not the executor.

---

## 4. Phases

Each phase has a hard acceptance criterion. Do not start phase N+1 until N
passes. Report the numbers, not "it works."

### Phase 0 — Runtime and instrumentation (no agent yet)

1. Fork nanoLoop. Keep `session.py`, `memory.py`, `skills.py`,
   `frontmatter.py`, `tests/`. Drop `agents.py`, `roles.py`.
2. Ollama config for a 16 GB Air:
   ```
   OLLAMA_KEEP_ALIVE=-1
   OLLAMA_MAX_LOADED_MODELS=2      # 12B + embeddinggemma only
   OLLAMA_FLASH_ATTENTION=1
   OLLAMA_KV_CACHE_TYPE=q8_0
   ```
3. Wire `model_ollama.py`. Verify `num_ctx` actually reaches the server —
   send a >num_ctx prompt and confirm the server reports truncation rather than
   swallowing it.
4. **JSONL call log from the first request.** Every model call records:
   `phase, prompt_tokens, tools_offered, raw_output, parsed_output,
   parse_ok, latency_ms, wall_clock_since_start`. This log is the regression
   suite when the runtime changes.
5. Also stand up LiteRT-LM in parallel and confirm both endpoints answer:
   ```
   litert-lm import --from-huggingface-repo=litert-community/gemma-4-12B-it-litert-lm \
     gemma-4-12B-it.litertlm gemma4-12b
   litert-lm serve                      # localhost:9379/v1/chat/completions
   ```
   Request body uses `"model": "gemma4-12b,gpu"`. Note: current LiteRT-LM
   supports text and audio; image and multi-token prediction are not yet
   shipped for the 12B, and context tops out at 32K.

**Accept when:** both endpoints answer, `num_ctx` is provably honored, and the
JSONL log has entries with real token counts.

### Phase 1 — Planner only

Implement `propose_plan(goal, repo_map) -> Plan` using structured output
(`format` = `schema_of(Plan)`, ~198 tokens of schema).

Repo map: file tree + first docstring per file. Not file contents. Must fit in
`PHASE_NUM_CTX["plan"]` = 16384 with room to spare.

**Accept when:** 10 real goals against a real repo produce schema-valid plans,
and ≥8/10 have `target_file` paths that actually exist.

### Phase 2 — `propose()` and the anchor-hit measurement

This is the phase that decides whether the project is viable. Implement:

```python
def propose(step: Step, feedback: str, temperature: float) -> Edit
```

Context: rendered `Ctx` + the current contents of `step.target_file`.
Output: `format` = `schema_of(Edit)` (~104 tokens of schema).

**The metric that matters is anchor-hit rate** — does the model emit an `anchor`
that matches exactly once in the target file? It is copying literal text from a
file it just read. I expect this, not code quality, to be the dominant failure
mode.

Measure over ≥50 steps and report the breakdown: exact-hit / not-found /
ambiguous.

**If anchor-hit < ~85%**, add fuzzy anchoring before continuing: match the
anchor by line-similarity with a threshold, accept only if exactly one candidate
clears it. This converts a hard failure into a soft one without asking more of
the model. Do not skip straight to fuzzy — measure exact first, the number tells
us where the model actually is.

**Accept when:** anchor-hit rate is measured and reported, and (with fuzzy
fallback if needed) exceeds 90%.

### Phase 3 — Full loop on one step

Wire `build_step()` with the real `propose`. Gates: `ruff check .`,
`ruff format --check .`, `python -m pytest -q`.

**Accept when:** 20 single-step tasks on a real repo close the loop, with
reported medians for: model calls per step, repair attempts, wall-clock.

### Phase 4 — Multi-step and the thermal soak test

Iterate the plan. Add HITL gates at plan-approval and pre-ship (nanoLoop's
`human_review` already does this — keep it).

**Run a 30+ step task and plot latency per step against step index.** On a
fanless Air this will degrade. Report the throttling curve. If step 30 is >2×
step 1, add cooldown pauses between steps or cut `n_candidates` to 1 after step
N. This is a real engineering constraint on this machine, not a footnote.

**Accept when:** a 30-step task completes and the throttling curve is documented.

### Phase 5 — Skills, Google-style

- Catalog (name + description only) injected into the `build` system prompt.
- One `use_skill(name, data)` invoker; body loads on trigger.
- Executor is deterministic Python — a scaffold or template run, not prose the
  model imitates.
- Ship 3 skills to start: `scaffold-fastapi` (port nanoLoop's), `add-endpoint`,
  `setup-pytest`.
- **Watch skill-selection ambiguity.** The same 21× penalty applies to choosing
  between two similar skill descriptions. Google's skills carry an `## Examples`
  section with trigger phrasings — use it as routing anchors.

**Accept when:** adding a 4th skill costs <30 tokens of catalog and does not
regress the Phase 3 numbers.

### Phase 6 — Semantic recall with EmbeddingGemma

Replace nanoLoop's keyword `recall` over `./Memory/*.md` with retrieval over
EmbeddingGemma, then expand along the `[[links]]` knowledge graph on the top-k.

Non-negotiable details:
- **Prefixes.** `"task: search result | query: "` for queries,
  `"title: none | text: "` for documents. Ollama does **not** apply these. One
  function, one place. Index and query with the same convention or you get
  asymmetric silent degradation.
- 2K context window → chunk notes at 800–1000 tokens.
- 768 dims is fine at this corpus size; Matryoshka truncation to 256 (with
  renormalization) only when the index becomes a problem.

**Accept when:** on 30 hand-labeled recall queries, semantic recall@5 beats the
keyword baseline.

---

## 5. Eval harness — build in Phase 0, run on every change

Not optional and not last. Metrics:

| Metric | Where measured |
|---|---|
| plan validity + target-file existence | Phase 1 |
| **anchor-hit rate** (exact / fuzzy / miss) | Phase 2 |
| gate-pass rate on first greedy attempt | Phase 3 |
| model calls per completed step | Phase 3 |
| repair-loop depth distribution | Phase 3 |
| latency vs. step index (throttling curve) | Phase 4 |
| skill-selection accuracy | Phase 5 |
| recall@5 vs. keyword baseline | Phase 6 |

Fix a set of 20–30 real tasks against a real repo and re-run on every change.
Without this, "it works" means "it worked on the three things I tried."

---

## 6. Anti-patterns — things that will be tempting and are wrong here

- **Re-adding an LLM orchestrator** because the graph feels rigid. The rigidity
  is the feature (D1).
- **`write_file(path, full_content)`** because anchors are annoying. This is the
  single fastest way to corrupt a repo with a 12B (D4).
- **Raising `n_candidates`** to fix quality. On a fanless 16 GB Air you are
  paying wall-clock and thermal headroom. Fix the prompt or the gate first (D7).
- **Loading a second LLM** for routing. There is no memory for it. The router
  job is small enough for the 12B, or belongs in code.
- **Passing the full transcript** because the model "lacks context." Render what
  it needs (D6). If it truly needs more, the step is too big — split it.
- **Trusting Gemma 4's native tool calling as a guarantee.** ~86% on τ2-bench is
  good, not sufficient. Close the remainder with constrained decoding.
- **Skipping the eval harness** to get to a demo faster.

---

## 7. Open questions to resolve empirically

1. **Anchor-hit rate.** The project's viability hinges on it. Phase 2.
2. **Does LiteRT-LM expose arbitrary grammars or only JSON Schema?** If
   arbitrary, it becomes the production runtime outright and there is no reason
   to move to `llama-server` later. If schema-only, it matches Ollama on that
   axis and the choice is decided by prefix caching and throughput instead.
3. **Throttling curve on the Air.** Determines whether best-of-N is affordable
   at all, and whether a 30-step task is a realistic unit of work on this
   machine.
4. **Skill-selection accuracy past ~10 skills.** Prose ambiguity is the same
   failure mode as tool ambiguity; find where it starts.

---

## 8. First commit

Fork, drop `agents.py` and `roles.py`, add `crew.py` and `model_ollama.py`,
delete `list_skills` from the tool list, keep the 23 upstream tests green, and
land the JSONL call logger. Then Phase 0.
