# What is missing for a real task

Measured analysis, not speculation. Every gap carries the evidence that
demonstrates it and what closing it would cost. Ordered by what will hurt first.

Context: the loop **works** — plan → steps → gates → verification → replan,
305 tests, real tasks solved end to end. What follows is what separates
"reliably solves toy tasks" from "I can hand it a real one".

---

## ~~G1~~. Acceptance checked that a name EXISTS, not that it WORKS — ✅ CLOSED

The largest gap, and the easiest to miss, because everything came out green.

```python
class Store:
    def by_tag(self, tag):
        return []  # stub: always empty
```
```
criterion `by_tag` against that stub  ->  SATISFIED
```

`defines_symbol()` asked *"does this name exist?"*. A stub, a `pass`, or a
backwards implementation all passed. The gates did not save it either: `ruff` has
no opinion on semantics and `pytest` only runs tests that ALREADY exist — if the
function is new, nothing covers it.

Chained with replan it was worse, not better: replan considered a criterion
satisfied the moment the symbol appeared, so it stopped insisting exactly when
the code was empty.

**DONE.** `Acceptance.check` is now executable Python, run by the graph from the
repo root, time-bounded, with the probe file deleted afterwards. The same stub:

```
name only : SATISFIED            <- the gap
with check: `by_tag` exists but its check failed: AssertionError
```

And `--accept criteria.json` lets **you** write them, ignoring the planner's —
verified end to end: my two criteria survived a replan and forced a second round
until both passed (5/5 steps, 2 rounds, 6 model calls).

`NANOLOOP_REQUIRE_CHECKS=1` treats any criterion without a check as unmet, so a
run cannot look stronger than it is.

---

## ~~G2~~. Large files: the anchor was unreachable — ✅ CLOSED

```
nanoloop/crew.py   29,735 chars -> slice of 12,018 (truncated from the head)
last quarter of the file visible for anchoring?  NO
```

`_read_slice` cut at 12,000 chars keeping the HEAD. Any anchor living in the tail
was literally unreachable: the model cannot copy text it was never shown, and the
failure surfaced as a repeated `not_found` — indistinguishable from "the model
cannot copy".

On a real repo this is not a rare case:

```
pydantic sample (105 files)
  42% exceed half the build budget
  _generate_schema.py  ~34,087 tok   (4x the ENTIRE 8,192 window)
  json_schema.py       ~31,488 tok
  types.py             ~26,490 tok
```

**DONE.** `_read_slice` no longer truncates from the head. It locates the
definition the step is about (hints: `defines`, then `title`/`intent`) with `ast`
and sends a window centred on it, growing outward to fill the budget. If no
symbol matches it sends **head AND tail** — appending is the most common step and
the tail is where you anchor for it.

On `crew.py` itself (36,041 chars, 937 lines):

```
symbol             line    before          after
run_goal            868    UNREACHABLE     visible
verify_plan         785    UNREACHABLE     visible
run_check           751    UNREACHABLE     visible
```

Verified end to end against a 22,229-char module whose `class Registry` falls
outside the first 12,000 chars: **1 step, 1 model call, 0 repairs, `exact`
anchor**, executable criterion green and gates green.

Every shown region is byte-for-byte identical to the file (there is a test
pinning it) and the gaps are announced — an anchor spanning a gap would match
nothing, and the model must be able to see something is missing.

Note: I did not number the lines. It would fight the verbatim anchor copying that
everything else depends on.

---

## ~~G3~~. The planner was unstable across runs — ✅ CLOSED (and the premise was false)

**MEASURED, and I was wrong.** `eval/run_variance.py`, 8 runs of one goal:

```
steps (raw)      median 3.0   range 3-3   sd 0.00   {3: 8}
criteria with a check                     16/16 (100%)
VERDICT: stable
```

The planner is **deterministic** at temperature 0. What I took for variance was
different inputs: slightly different goals against repos in different states. The
lesson: without measuring, "it is unstable" was a story I told myself.

**But the measurement exposed a real and consistent bug**, which was what
actually caused the replans:

```
step 3  target_file='todo wrong/store.py'    <- 8 runs out of 8
```

A directory that does not exist. The step did not edit `todo/store.py`: it
**created a phantom file**, the symbol landed where no criterion looked, and a
replan round was spent rediscovering it.

`resolve_target()` repairs this deterministically: if the path does not exist and
**exactly one** file bears that name, snap to it; anything ambiguous is left to
fail loudly, because a wrong snap edits the wrong file.

Measured effect live, same goal: **2 plan rounds → 1**, 3/3 steps, 3 calls.

Also added `normalize_plan()`, which drops redundant steps conservatively — only
on a repeated `defines` or an identical title. Two steps on one file with no
`defines` are NOT merged: a false merge silently loses work.

---

## ~~G4~~. Whole-file generation — ✅ MEASURED (and far less serious than it looked)

**MEASURED.** `eval/run_newfiles.py`, 16 fixtures, a funnel rather than a rate:

```
              raw     real pipeline
parsed      100.0%       100.0%
syntax       93.8%        93.8%
lint         41.7%        93.8%   <- autofix
imports      41.7%        93.8%
defines      41.7%        93.8%
FULLY VALID  41.7%        93.8%
```

**I measured it wrong twice, and both times too harshly.**

1. The first reading said **41.7%** — but it measured the *raw* output, without
   the `crew.autofix` the pipeline applies after every edit. The dominant
   failures were `F401 unused import` and `I001 unsorted imports`:
   **auto-fixable**. I was blaming the model for what a tool fixes every time.
2. The second said **68.8%**, and every remaining failure was a test module
   reported as *"does not define test_X"*. Looking at what it actually wrote:

   | asked for | wrote |
   |---|---|
   | `test_pending_empty` | `test_store_pending_is_empty_on_new_store` |
   | `test_all_returns_both` | `test_all_returns_two_items_after_adding_two` |

   Tests that are **valid, importable and better named than what I asked for**.
   The thing that was wrong was my verifier: in a test module the exact name is
   not the requirement, the presence of a test is. `defines_symbol` now accepts
   any `test_*` in a test module — and only there; elsewhere the name is still
   the contract (`by_tag` ≠ `by_label`).

**Real result: 15/16 = 93.8%.** One genuine failure in sixteen (an indentation
error). Against ~100% for anchored edits the gap is real but far smaller than it
appeared — and the harness's `--raw` flag shows how much of that the tool
contributes rather than the model.

Still true: cover anything template-shaped with **skills** (the FastAPI scaffold
came out 3/3 with 0 model calls). But "new files are the weak point" was
substantially an artefact of how I was measuring.

---

## G5. The repo map does not scale — 🟡 you will notice soon

```
this repo: 129 lines, ~3,260 tok  (plan budget: 16,384)
```

Comfortable here, but it grows linearly with no filter at all: `max_files=300`
then truncates. A 2,000-file repo neither fits nor would make sense — the planner
does not need to see the whole repo, it needs to see **what is relevant to the
goal**.

**What I would do:** filter the map by relevance to the goal before sending it
(lexical matching is enough to start; `recall.py` already has EmbeddingGemma if
something better is needed). Note that the symbol index we added is what makes
the map useful at all — without it the planner was sending edits to
`__init__.py`.

---

## G6. Nobody looks at two files at once — 🟡 structural

Each step sees ONE file (D6, and deliberately so). Consequence: a change in
`store.py` that breaks `format.py` is only detected if the tests already cover
it. In a real repo a signature change propagates and the crew does not see it
coming.

The gates are the net, and a good one — but only as good as the target repo's
test suite. **In a repo with thin coverage, the crew advances blind.**

I would not "fix" this by widening the context (that is the anti-pattern in
PLAN.md §6). What is tractable: require the target repo's tests to pass BEFORE
starting, and abort if not — which preflight now does.

---

## ~~G7~~. Environment assumptions — ✅ CLOSED (partially)

**DONE** for the main part. `crew.preflight()` runs before the first plan and
refuses to start if the repo is already broken, distinguishing two causes that
need different answers:

```
tool missing -> tooling not on PATH: eslint. Install it in the environment...
repo red     -> the repo does not pass its own gates before any change
```

And it deliberately does **not** block two legitimate cases: an empty workspace
(scaffolding from nothing — the FastAPI demo starts exactly there) and repos with
no Python.

Verified through the CLI:

```
repo with a failing test  -> exit 3, 0 model calls
empty workspace           -> skipped, proceeds and scaffolds (0 calls, skill)
```

The **zero calls** is the point: before this, that repo would have spent repairs
fighting a failure no edit of its own could fix.

`--skip-preflight` to override knowingly.

**Still open in G7:** the crew cannot install dependencies, and `DEFAULT_GATES`
is hardwired to Python.

---

## G8. Smaller things that still bite

- **No resume.** An interrupted run leaves the workspace half-done. The snapshot
  protects per candidate, not per session.
- **Local latency**: ~30 s/call on the 12B, and p50 rose from 17.5 s to 29.8 s
  after a day of sustained load. The 30-step thermal soak has still not been run.
- **`num_ctx` still not truly verified** against the server (Phase 0 #1 was left
  half-done: the command exists, the log check was never made).

---

## What I would do, in order

| # | gap | effort | unblocks |
|---|---|---|---|
| ~~1~~ | ~~**G1** executable criteria~~ ✅ | low | making "green" mean something |
| ~~2~~ | ~~**G2** symbol-centred slicing~~ ✅ | medium | editing real files |
| ~~3~~ | ~~**G7** gate preflight~~ ✅ | low | not fighting the environment |
| ~~4~~ | ~~**G3** step dedup + variance~~ ✅ | low | stable plans |
| 5 | **G5** repo map filtered by relevance | medium | large repos |

With 1 + 2 + 7 done I would hand it a scoped real task in a repo with decent
tests. What remains untested is scale, not capability.

## What I would give it TODAY

It works unattended if all of this holds:

- a Python repo with `ruff` + `pytest` configured and **green to start**
- target files under ~10,000 chars — or larger, now that slicing centres on the
  symbol
- extending existing code (add a method, a parameter, an endpoint) rather than
  designing new modules
- a goal that explicitly names what must exist (it feeds the acceptance criteria)
- **you review the diff** — the criteria tell you it is there, not that it is good
