# IMPLEMENTATION PLAN — executing PLAN.md

Companion to `PLAN.md`. That document says *what* to build and *why*. This one
says *in what order*, *which files*, and *what is not true yet*.

Ground truth below was verified on this machine on 2026-07-26. Everything marked
**[verified]** was checked, not assumed.

---

## 0a. Phase 0 findings — measured 2026-07-26, Ollama 0.31.2, gemma4:12b

Three things were verified against the live model. Two of them change the code.

### F1. Gemma 4 is a REASONING model, and `/v1` cannot turn it off. **8× wall clock.**

Same prompt, same model, only the transport differs:

| transport | wall clock | content | reasoning |
|---|---|---|---|
| `/v1/chat/completions` + `think:false` | **222.3 s** | 139 tok | 6,249 chars |
| `/api/chat` + `think:false` | **26.8 s** | 164 tok | 0 |

Ollama returns chain-of-thought in a *separate field* (`message.thinking`
natively, `message.reasoning` on `/v1`) and leaves `content` **empty** until
thinking finishes. Reading only `.content` therefore yields `""` while the model
burns thousands of tokens. With a token cap you get `finish_reason=length` and
nothing at all — it presents as a broken model, not as unrequested reasoning.
The first anchor-eval attempt hit exactly this: one call, **392 seconds, 3,562
completion tokens, zero output**.

`/v1` ignores `think: false`. Only the native endpoint honours it.

**Consequence: PLAN.md's cost model ("a 300-token edit ≈ 15–20 s") holds only
with reasoning OFF.** Left on, it adds thousands of tokens to *every* call —
fatal on a fanless Air, and it would have been misread as thermal throttling in
Phase 4. `nanoloop/model_ollama.py` now defaults to the native transport with
`think:false`, and `calllog` records `thinking_chars` so a latency regression
can be attributed immediately.

### F2. Structured output — PLAN.md was right, but only on the right endpoint

PLAN.md §4 specifies `format = schema_of(...)`. That is Ollama's **native** field
and it works correctly on `/api/chat`. Sent through `/v1` it is **silently
ignored** — the model free-generates and invents its own field names:

```
/v1 + format:           [{"intent": "...", "action": {"type": "edit_file", ...}}]   ✗
/v1 + response_format:  {"steps": [{"title": "...", "target_file": "...", ...}]}    ✓
/api/chat + format:     {"path": "...", "anchor": "...", "replacement": "..."}      ✓
```

Both surfaces are implemented; the transport selects. This resolves
IMPLEMENTATION §4 verification #2 and PLAN.md §7 Q2 for Ollama.

### F3. Schema costs match PLAN.md's estimates

`Plan` ≈ 204 tok (PLAN.md said ~198), `Edit` ≈ 124 tok (said ~104). No action.

### F4. Phase 2 spike — anchor-hit is **100% (12/12)**

The viability gate (PLAN.md §7 Q1), run per IMPLEMENTATION §1 as a spike on
hand-written fixtures before the planner existed:

```
fixtures        12
exact           12  100.0%      not_found 0   ambiguous 0
EXACT-HIT RATE  100.0%          VERDICT: >=90% — proceed
```

Fixtures deliberately included repeated-text traps (`return value`, `self._items`
appear multiple times in the fixture repo), multi-line anchors, and append-at-end
cases. Fuzzy anchoring recovered nothing because nothing needed recovering —
`NANOLOOP_FUZZY` stays `0`.

**Caveat, stated plainly: PLAN.md asks for ≥50 steps and this is 12.** The result
is a strong green light, not the full measurement. Grow `eval/anchors.jsonl`
toward 50 against a second, larger repo before treating 100% as durable — a
12-file corpus is exactly where anchors are easiest.

Runtime, same run (`python -m eval.report`):

```
model calls per step    median 1.0   max 1     <- greedy succeeds; D7 holds
first-attempt success   100.0%
repair depth            median 0     max 0
structured-output parse 100.0% (12/12)
latency p50             17.5 s/call  (p90 28.4 s)
wall clock              231 s for 12 steps
```

No throttling signal yet (early 16.8 s → late 11.6 s = 0.69×), but 12 steps over
4 minutes is far too short to show it. The Phase 4 soak test at 30+ steps is
still required and `eval/report.py` already plots the curve.

### F5. Phase 3 — the full loop closes end to end

`nanoloop.main run` on a copy of the fixture repo, live model, real gates:

```
plan          1 step   "Define remove method in Store class" (todo/store.py)
plan-approval gate     AUTO-APPROVED (non-interactive)
step 1        ok — 1 model call, 0 repairs, anchors=['exact']
pre-ship gate          AUTO-APPROVED
done          1/1 steps, 1 model call
```

The model wrote a correct `remove()` — enumerate, pop the first title match,
return True, else False — and `ruff check`, `ruff format --check` and `pytest`
all pass when re-run independently. One model call for a completed step is D7
behaving exactly as designed.

**A bug this run found (now fixed, `crew._gate_env`).** The first attempt failed
with `ruff: command not found`: gates run through `sh`, which does not inherit
an activated virtualenv. All four anchors that run were `exact` — the model was
never at fault, but the repair loop dutifully fed an environment error back to
it and burned 4 calls on something no edit could fix. `run_gate` now prepends
`Path(sys.executable).parent` to `PATH`. Worth noting as a general shape: the
repair loop cannot distinguish "the edit was wrong" from "the harness is
broken", so harness errors are expensive.

### F6. Phase 6 — semantic recall wins decisively, but **PLAN.md's metric is saturated**

`ollama pull embeddinggemma` → 621 MB (PLAN.md estimated ~300 MB), 768 dims,
unit-normalized, ~0.5 s/embedding. Corpus: 8 notes, 8 chunks, 10 labeled queries.

```
                    @1            @2            @3            @5
                 kw    sem     kw    sem     kw    sem     kw    sem
MEAN           0.00   0.85   0.30   1.00   0.55   1.00   1.00   1.00
```

**recall@5 — the figure PLAN.md names — is 1.000 for BOTH methods.** That is not
a tie between equals; k=5 over 8 notes retrieves 62% of the corpus, so the metric
cannot discriminate. Reported alone it reads as "semantic failed to beat
keyword", which is the opposite of what the data says. At discriminating k the
gap is enormous: **keyword never once ranks the right note first (0.000 @1)**
while semantic gets 0.850.

`eval/run_recall.py` now sweeps k=1,2,3,5, flags saturated values explicitly, and
takes its verdict from the smallest k that still separates the two. A single
saturated number was exactly the "it works" failure PLAN.md §5 warns about.

Two sub-1.0 cells at @1, both understood:
- *"what goes into the prompt each turn"* — the correct note `context-is-compiled`
  ranks **2nd, losing by 0.016** to `skills-are-data`, whose body literally says
  a catalog entry "lives in the prompt". A genuine near-miss, resolved at k=2.
- *"the laptop gets slow after a long run"* — 2 notes labeled relevant, so
  recall@1 caps at 0.5 by construction. A labeling artifact, not a retrieval
  failure; 1.00 at k=2.

**Caveat: 10 queries against 8 notes, where PLAN.md asks for 30.** The direction
is unambiguous but the corpus is far too small to call this settled. Both
retrievers read the same corpus via `recall._corpus()`, which excludes the
generated `MEMORY.md` index — that file lists every note's description and would
have matched every query, silently beating the real notes.

---

## 0. Delta between PLAN.md and reality

`PLAN.md` §1 opens with "Two files are written and verified. Start from them; do
not rewrite." **They do not exist on this machine.** `/Users/agustinazwiener/gemma4nanoloop`
is empty — no git repo, no fork, no `crew.py`, no `model_ollama.py`. [verified]

This is the single most schedule-relevant fact in this document. Either those
files exist somewhere not on this disk and must be located, or Phase 0 is
preceded by a reconstruction phase (§2 below). Resolve this before anything else
— reconstructing `crew.py` from the §1 description is a day of work that is
wasted if the file is sitting in another checkout.

### What *is* true [all verified]

| Claim in PLAN.md | Status |
|---|---|
| nanoLoop upstream, Apache-2.0 | ✅ `LICENSE` is Apache 2.0 |
| 23 tests pass | ✅ 23 `test_` functions across 4 files |
| `session/memory/skills/frontmatter` are model-agnostic | ✅ zero deepagents imports |
| `agents.py`, `roles.py` are what gets replaced | ✅ they are the *only* deepagents consumers |
| One skill ships today (`scaffold-fastapi`) | ✅ `Skills/scaffold-fastapi` |
| `list_skills` is a wasted slot | ✅ exists in `tools.py`, and **no test covers it** |
| `gemma4:12b` local | ✅ 7.6 GB |
| LiteRT-LM installed | ✅ `~/.local/bin/litert-lm` |
| M4 / 16 GB / no fan | ✅ |

### What is not true or not yet true

1. **`crew.py` and `model_ollama.py` are absent.** See above.
2. **`embeddinggemma` is not pulled.** Phase 6 has an unmet prerequisite.
3. **`gemma4:e4b` (9.6 GB) is on disk.** PLAN.md §2/§6 forbids a second LLM for
   memory reasons. With `OLLAMA_MAX_LOADED_MODELS=2`, an accidental e4b request
   loads 9.6 GB *alongside* the 7.6 GB 12B and blows the 16 GB budget into swap.
   The env var does not protect you; only not asking for e4b does.
4. **`pyproject.toml` declares MIT in its classifiers** while `LICENSE` is
   Apache-2.0. Upstream bug, inherited by the fork. Fix in the first commit.
5. **Python here is 3.14.6**; upstream declares `>=3.11`. The langchain/pydantic
   stack on 3.14 is a wheel-availability risk. Pin the venv to 3.12 via
   `uv venv --python 3.12` rather than discovering this mid-Phase-0.
6. **`use_skill` today takes `(name)` only.** PLAN.md §4 Phase 5 specifies
   `use_skill(name, data)`. Signature change, not a new tool.

### A dependency win PLAN.md does not claim

`deepagents` is imported *only* by `agents.py` and `roles.py`. [verified]
Dropping those two files drops the `deepagents` dependency outright. What
remains needs `langchain_core.tools.tool` (in `tools.py`) and
`langchain_openai.ChatOpenAI` (in `model.py`) — and since `crew.py` binds tools
per-phase itself, even those are removable later. `langgraph` survives only as a
`MemorySaver` import in `main.py:40`, which goes away with the orchestrator.

Target after the first commit: `langchain-openai`, `python-dotenv`, `rich`,
`pydantic`. That is the whole runtime.

---

## 1. Recommended deviation from PLAN.md's phase order

PLAN.md §4 says "Do not start phase N+1 until N passes." I want to break that
once, and only once.

**Run the Phase 2 anchor-hit measurement as a spike, before Phase 1.**

Rationale, drawn from PLAN.md's own text: §4 calls Phase 2 "the phase that
decides whether the project is viable" and §7 lists anchor-hit rate as open
question #1. The planner (Phase 1) is a substantial build whose value is
conditional on anchor-hit being acceptable. Anchor-hit does not depend on the
planner — it needs `(target_file, instruction)` pairs, which can be hand-written
into a fixture file in an hour.

So: hand-author ~50 fixture steps, measure exact anchor-hit, *then* decide
whether to build the planner, add fuzzy anchoring, or stop. This gets to the
kill-signal days earlier without weakening any acceptance criterion. Every other
phase boundary stays hard.

If you'd rather keep the order literal, say so and I'll sequence it as written —
the cost is building Phase 1 before knowing whether Phase 2 clears.

---

## 2. Phase −1 — Reconstruction (only if the two files are truly lost)

**First action: search for the existing files before writing anything.**

```
mdfind -name crew.py; mdfind -name model_ollama.py
```

If found, copy them in and skip to Phase 0.

If not found, rebuild from PLAN.md §1, which specifies them tightly enough:

**`nanoloop/model_ollama.py`** — small. `ChatOpenAI` against
`http://localhost:11434/v1`. The load-bearing detail is `num_ctx` in top-level
`extra_body`, *not* `model_kwargs` (LangChain warns and silently drops it there;
Ollama then truncates history silently). Ship with a test that asserts the
kwarg lands in the request body.

**`nanoloop/crew.py`** — the real work. Per §1 it contains:
`Step` / `Plan` / `Edit` (pydantic), `PHASE_TOOLS`, `PHASE_NUM_CTX`,
`run_gate()` (truncates output **from the front** — tracebacks carry payload at
the tail), `apply_edit()` (raises on 0 or >1 anchor matches), `build_step()`
(greedy → bounded repair with exact-error feedback → best-of-N only after greedy
fails), `Ctx.render()` (fresh each turn, never accumulates).

Two traps named in PLAN.md to honor on reconstruction:
- `gates or DEFAULT_GATES` makes `gates=[]` fall through to defaults. Use
  `if gates is None`. Write the test that pins this.
- `n_candidates` defaults to **2**, not 3.

Acceptance: mock-model run reproduces §1's verified behavior — greedy fails,
stderr is injected, second attempt passes, **2 model calls total**.

---

## 3. First commit (PLAN.md §8)

Single commit, mechanical, all verifiable:

1. `git init`; vendor nanoLoop preserving Apache-2.0 `LICENSE` + `NOTICE`.
2. `rm nanoloop/agents.py nanoloop/roles.py`.
3. Delete `list_skills` from `tools.py` and from `HARNESS_TOOLS`.
   **No test references it** [verified] — 23 tests stay green.
4. Add `crew.py`, `model_ollama.py`.
5. Add `nanoloop/calllog.py` — the JSONL logger (§4 below).
6. `pyproject.toml`: drop `deepagents`/`langgraph`, fix the MIT classifier to
   Apache-2.0, `requires-python = ">=3.12"`.
7. Gut `main.py`'s orchestrator wiring (it imports `MemorySaver` and the
   DeepAgents graph); point the CLI at `crew.py`.

**Acceptance: `pytest -q` → 23 passed.** Not 22, not "mostly".

---

## 4. Phase 0 — Runtime + instrumentation

Deliverables:

- `nanoloop/calllog.py` — one append-only JSONL writer. Every model call:
  `phase, prompt_tokens, tools_offered, raw_output, parsed_output, parse_ok,
  latency_ms, wall_clock_since_start`. This lands **before** the first real
  request, per PLAN.md §4.4 — it is the regression suite for runtime changes.
- `env.sh` / documented Ollama config: `OLLAMA_KEEP_ALIVE=-1`,
  `OLLAMA_MAX_LOADED_MODELS=2`, `OLLAMA_FLASH_ATTENTION=1`,
  `OLLAMA_KV_CACHE_TYPE=q8_0`.
- `eval/` package skeleton (§7 below).

Three verifications that are easy to hand-wave and must not be:

1. **`num_ctx` provably honored.** Send a prompt exceeding `num_ctx`; confirm
   the *server* reports truncation. A response that merely looks fine proves
   nothing — that is the exact silent-drop failure §1 warns about.
2. **Which structured-output surface actually works.** PLAN.md §4 Phase 1/2 say
   `format = schema_of(Plan)` — that is Ollama's *native* API field. We are
   talking to the *OpenAI-compatible* `/v1` endpoint via `ChatOpenAI`, where the
   equivalent is `response_format: {type: "json_schema", ...}`. These are
   different surfaces with different coverage. Determine which one Ollama 0.31.2
   honors for `gemma4:12b`, and pin it. Getting this wrong looks like degraded
   model quality rather than a config error.
3. **KV-cache quantization actually engages.** `q8_0` requires flash attention,
   and Gemma's sliding-window attention has historically had uneven support.
   Confirm from server logs; if it silently no-ops, the ≤3 GB KV budget in
   PLAN.md's constraint table is wrong and context ceilings need revisiting.

Also stand up LiteRT-LM (`import` → `serve` on `:9379`, body
`"model": "gemma4-12b,gpu"`) and confirm both endpoints answer.

**Accept when:** both endpoints answer, `num_ctx` truncation is *observed*, and
JSONL entries carry real token counts.

---

## 5. Phase 1 — Planner

`propose_plan(goal, repo_map) -> Plan`. Repo map = file tree + first docstring
per file, never contents; must fit `PHASE_NUM_CTX["plan"] = 16384` with slack.

**Accept when:** 10 real goals → schema-valid plans, ≥8/10 with `target_file`
paths that exist.

## 6. Phase 2 — `propose()` and anchor-hit

`propose(step, feedback, temperature) -> Edit`. Context = rendered `Ctx` +
current contents of `step.target_file`.

Metric: does the emitted `anchor` match **exactly once** in the target file.
Report the three-way split: exact-hit / not-found / ambiguous, over ≥50 steps.

- ≥90% → proceed.
- 85–90% → add fuzzy anchoring (line-similarity threshold, accept only if
  exactly one candidate clears it), re-measure.
- **<85% → stop and report.** This is the kill signal. Do not paper over it by
  relaxing to `write_file` (PLAN.md §6 names that as the fastest way to corrupt
  a repo with a 12B).

Measure exact before fuzzy. The raw number is the diagnostic.

## 7. Phase 3 — Full loop, one step

Wire `build_step()` to real `propose`. Gates: `ruff check .`,
`ruff format --check .`, `python -m pytest -q`.

**Accept when:** 20 single-step tasks close the loop; report **medians** for
model calls/step, repair attempts, wall-clock.

## 8. Phase 4 — Multi-step + thermal soak

Iterate the plan; HITL gates at plan-approval and pre-ship (reuse nanoLoop's
`human_review` — it is already covered by 2 tests).

**Snapshot/restore (D8) needs a decision.** PLAN.md offers "`git stash` or a
workspace copy". `git stash` is fragile here: it is global repo state, it
interacts badly with anything concurrent, and a failed pop leaves the tree
dirty in a way the loop will not notice. Recommend a workspace copy (or
`git worktree`) so each candidate is genuinely isolated. Flagging rather than
deciding — see §10.

Run a 30+ step task; plot latency against step index. **Report the throttling
curve.** If step 30 > 2× step 1, add inter-step cooldowns or drop
`n_candidates` to 1 after step N.

## 9. Phase 5 — Skills, Google-style

Catalog (name + description, ~23 tok/skill) into the `build` system prompt;
bodies load on trigger via one `use_skill(name, data)` invoker — a **signature
change** to the existing tool. Executor is deterministic Python, not prose.
Ship `scaffold-fastapi` (port), `add-endpoint`, `setup-pytest`. Give each an
`## Examples` section with trigger phrasings as routing anchors.

**Accept when:** a 4th skill costs <30 catalog tokens and does not regress
Phase 3 numbers.

## 10. Phase 6 — Semantic recall

`ollama pull embeddinggemma` first — **not currently present**.

Replace keyword `recall` over `./Memory/*.md` with EmbeddingGemma retrieval,
then expand along `[[links]]` on top-k.

Non-negotiable: **prefixes**. `"task: search result | query: "` for queries,
`"title: none | text: "` for documents. Ollama does not apply these. One
function, one place, used by both indexer and query path — asymmetry here
degrades silently. Chunk at 800–1000 tokens (2K context). Keep 768 dims;
Matryoshka-truncate to 256 with renormalization only if the index becomes a
problem.

**Accept when:** semantic recall@5 beats keyword baseline on 30 hand-labeled
queries.

---

## 11. Eval harness — the understated cost

PLAN.md §5 says build it in Phase 0 and run it on every change. Correct, and
this is the largest hidden line item in the whole plan: **20–30 hand-authored
tasks against a real repo, with labels**, plus 30 labeled recall queries for
Phase 6. That is not an afternoon.

Proposal: bootstrap at 8 tasks in Phase 0 so the harness is *real* from the
first commit, and grow toward 30 across Phases 2–4 as failures reveal which
tasks are worth encoding. A harness that exists and is small beats one that is
scheduled and absent — and PLAN.md §6 lists "skipping the eval harness" as an
anti-pattern precisely because it always slips.

Which repo is the fixture repo is an open input (§12).

`eval/` layout:

```
eval/tasks.jsonl        fixed task set
eval/anchors.jsonl      Phase-2 fixtures (hand-written, no planner needed)
eval/recall.jsonl       Phase-6 labeled queries
eval/report.py          reads calllog JSONL -> the §5 metrics table
```

---

## 12. Open inputs — needed from you

1. **Do `crew.py` / `model_ollama.py` exist elsewhere?** Determines whether
   Phase −1 happens at all. Highest-leverage question here.
2. **Which repo is the eval fixture repo?** Phases 1–4 all measure against it.
   nanoLoop itself is the obvious candidate (small, 23 tests, ruff-clean) —
   with the caveat that the crew editing its own harness is a footgun; a copy
   under `eval/fixture-repo/` avoids that.
3. **Snapshot primitive for D8:** workspace copy (my recommendation) vs
   `git stash` (PLAN.md's first suggestion).
4. **Delete `gemma4:e4b`?** Frees 9.6 GB and removes the OOM footgun. Keep it
   only if you have a use outside this project.
5. **Phase-order deviation in §1** — spike anchor-hit before the planner, or
   keep PLAN.md's literal order?

## 13. Risk register

| Risk | Trigger | Mitigation |
|---|---|---|
| Anchor-hit < 85% | Phase 2 | Kill signal. Fuzzy first; do **not** fall back to `write_file` |
| Thermal throttling makes 30 steps impractical | Phase 4 | `n_candidates=1`, cooldowns; report the curve either way |
| `num_ctx` silently dropped | Phase 0 | Verification #1; this is why `calllog` ships first |
| Structured output surface mismatch (`format` vs `response_format`) | Phase 0 | Verification #2 — presents as bad model quality, not as an error |
| e4b loaded alongside 12B → swap | any | Delete e4b, or never request it |
| Py3.14 wheel gaps in langchain/pydantic | first commit | Pin venv to 3.12 |
| Eval harness slips | always | Bootstrap 8 tasks in Phase 0 |

---

## 14. Sequence

```
[locate or rebuild crew.py + model_ollama.py]      ← blocks everything
        ↓
[first commit: 23 tests green, deps cut]
        ↓
[Phase 0: calllog + runtime verifications + eval skeleton]
        ↓
[Phase 2 SPIKE: anchor-hit on hand-written fixtures]   ← viability gate
        ↓                                    (if <85%: STOP, report)
[Phase 1: planner]  →  [Phase 3: one-step loop]  →  [Phase 4: multi-step + soak]
        ↓
[Phase 5: skills]   →  [Phase 6: semantic recall]
```

Phases 5 and 6 are independent of each other and of Phase 4's soak test; they
can proceed in either order once Phase 3 numbers are stable.
