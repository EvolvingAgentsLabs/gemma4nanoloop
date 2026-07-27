# Getting to an autonomous crew that does something real

Not a feature roadmap. A thesis, drawn from what actually broke in this project,
and what follows from it.

---

## The observation that changes everything

Count what failed across the whole build:

| cause | cases |
|---|---|
| **runtime / harness** | reasoning on `/v1` (8×), gates without the venv on PATH, a token cap starving the plan, a repo map with no symbols, broken planner paths |
| **badly designed verification** | optional schema fields leaving two mechanisms inert; green gates ≠ goal done; a saturated recall@5; criteria that only checked existence |
| **model capability** | generating whole files. And little else. |

And the A/B confirmed it: **the 12B and the 26B tie at 100%** anchor-hit. A model
twice the size fixed nothing — and would have *masked* the repo-map bug.

**Thesis: autonomy is limited by the density of verifiable signal around the
model, not by the model's intelligence.** Every time we turned an opinion into a
deterministic check, the 12B became competent. Every time we left a gap
unverified, the system lied in green.

Uncomfortable corollary: **investing in prompts or bigger models is the worst
return available here.** What pays is building oracles.

---

## The real bottleneck: where tasks come from

The crew needed a human to write (a) the goal and (b) the acceptance criteria.
That is not an autonomous crew; it is a supervised executor.

And there is a reason (b) cannot be delegated to the model: **we measured it** —
it invents criteria (`text_item`) and forgets others. The definition of "done" is
exactly what delegates worst.

Here is the turn:

> **A real repo is already full of tasks that come with their acceptance
> criterion attached. Nobody has to write them.**

A failing test **is** a complete specification:

| what the crew needs | what a failing test gives |
|---|---|
| a goal | "make this test pass" |
| an executable acceptance criterion | **the test itself** |
| a location | the traceback names the file |
| a verdict | `pytest`, which has no opinion |

That removes both weak links at once. And it is not only tests. All of these
carry their own oracle:

| source | oracle | note |
|---|---|---|
| failing test | the test | the perfect case |
| `mypy` error | `mypy` | located, verifiable, plentiful |
| `ruff` not auto-fixable | `ruff` | autofix already handles the rest |
| `TODO`/`FIXME` | none ⚠️ | needs a human criterion; the worst candidate |
| coverage gap | the test you write | inverts the problem: the task *is* writing the test |
| stale dependency | the whole suite | high risk, very clear signal |

**DONE.** `nanoloop harvest` runs the gates, parses the failures and emits tasks
with their criterion attached. `--run` works through them.

Tested end to end: a repo whose `summarize()` returned `"TODO"` against a test
specifying it. With no goal and no criteria written by hand:

```
[harvest] 1 task(s) from the repo
  1. [pytest] Make the failing test ...::test_summarize_counts pass
     fix in:   todo/store.py          <- the CODE, not the test
     oracle:   1 executable criterion
=== task 1: SOLVED ===   1/1 steps, 1 model call
```

Two details that decided whether this was worth anything:

- **The task points at the code under test, not the test file.** It is inferred
  from the test's imports. Pointing at the test invites editing it until it
  passes — the one outcome that would make the whole exercise worthless. The
  goal says so explicitly: *"Fix the code under test, not the test itself."*
  Verified: the test was left byte-identical.
- **Preflight is skipped on purpose** under `--run`. The repo IS red, and that
  red is the work; refusing to start would make harvest useless by construction.

`TODO`/`FIXME` are deliberately not harvested: no oracle means "done" would be
the model's opinion — exactly what this module exists to avoid.

---

## The second piece: the deliverable is a PR, not a directory

The crew used to mutate a working tree, which forces a human to stand over it.

If the deliverable is **a branch, commits, and an account of what it did and what
it could not**, the human enters asynchronously — the only thing that makes
autonomy both useful and safe. Reviewing a PR is cheap; supervising a process is
not.

It also forces something healthy: the crew has to **explain its work**, and it
already has the material (`calls.jsonl`, criteria met and unmet, steps, plan
repairs). Nobody needs to ask the model to write it — it is generated from the
log.

**DONE.** `--deliver` creates a branch, one commit per solved task, and a
`NANOLOOP-REPORT.md` generated from the data. `--pr` pushes and opens the pull
request (opt-in: publishing is outward-facing, not something to do by default).
Unsolved work goes **first** in the report and is **never committed**.

Tested: a git repo with two unimplemented specs, no goal and no criteria written
by hand → **2/2 solved, 4 tests green, a one-file diff**, two commits on
`nanoloop/harvest-pytest`, `main` untouched.

Three bugs that only appeared by doing it for real:

1. **`git add -A` swept `__pycache__`** into the commits; the diff a human would
   review was mostly bytecode.
2. **Without gates there is no net between tasks.** I passed `no_gates=True`
   because the repo is red — and task 2 undid task 1 while both reported
   success. The right bar for a red repo is not "no gates" but a **baseline**:
   you may leave the failures that were already there, you may not add new ones.
   `harvest.regressions()` checks and reverts the offending task.
3. **Merging criteria across rounds dropped the `check`.** It rebuilt
   `Acceptance(symbol, file)` and lost the executable part, so verification fell
   back to "does this name exist" — and a task that committed a `summarize()`
   returning a dict was reported solved because the test function still existed.
   **Same shape as the schema bug: a check that appears to run and cannot fail.**
   It is the error that has recurred most in this project.

And the cascade works: with the tests fixed, harvest immediately found a **mypy**
error in the freshly written code (`list[str]` where `list[Item]` belonged) that
the tests cannot catch because at runtime it makes no difference.

---

## The third: knowing when to stop, and how to give up

An autonomous crew needs a budget and needs to **give up well**.

- **Per-task budget** ✅ `--max-calls`, `--max-seconds`, `--max-tokens`. Checked
  **before** each call, never after: starting work you cannot pay for wastes the
  most expensive thing in the loop.
- **Giving up is a valid result** ✅. The report marks it **"stopped on budget"**,
  distinct from an unmet criterion: one tells the reviewer *raise the limit*, the
  other *the task may be wrong or too hard*.

Tested with `--max-calls 1` (impossible to satisfy): it gives up with no
traceback, **zero commits**, and a report accounting for the spend. With
`--max-calls 10`: 1/1 solved.

A bug worth remembering: `BudgetExhausted` derived from `RuntimeError`, and the
planner's retry catches `RuntimeError` for transient backend trouble. **"Stop
spending" was indistinguishable from "try again"** — the planner burned three
more calls and reported a bogus *"no valid plan in 3 attempts"*. It now derives
from `Exception`: something that means STOP must not be catchable by a handler
that means RETRY.

- **Failure memory** ✅ `failmem.py`. Every attempt is recorded (`solved` /
  `unmet` / `gave_up` plus the exact reason) and relevant failures are injected
  into the planner's prompt on the first pass.

  **The dangerous part is staleness, not storage.** A remembered failure that has
  since been fixed is *worse* than no memory: it steers the planner away from
  something that now works, and unlike a missing memory, a wrong one actively
  misleads. So any later success **supersedes** the failures for the same work.

  Verified live: run 1 with `--max-calls 1` → `gave_up` recorded; run 2 with a
  real budget → solved, 3 tests green; afterwards the lesson is gone, superseded.

  A bug on the way: the goal fingerprint was compared by **exact set equality**,
  so *"add by_tag to Store"* did not recognise its own failure recorded as
  *"implement by_tag(tag) on Store"* — one extra word and the memory was blind.
  Overlap is what makes a lossy key actually lossy.

  Stored as JSONL rather than knowledge-graph notes: an attempt is a structured
  record queried by exact file, not prose to search semantically. `memory.py`
  remains the home for durable project facts; this is a flight recorder.

---

## What I would NOT do

Anti-patterns that sound like autonomy and are regressions:

- **Handing control back to the model** (an LLM orchestrator deciding what to
  do). That is exactly what PLAN.md D1 removed, and we measured why.
- **Bigger models** to paper over verification gaps. The A/B says it buys no
  quality, and it masks bugs, which is worse.
- **More context** so it "sees more". PLAN.md §6 calls this an anti-pattern: if
  a step needs more, the step is too big.
- **Letting the crew write its own criteria unanchored.** It invents. Criteria
  come from the repo (a test) or from a human.
- **Autonomy with no way back.** Everything must fit in a revocable PR.

---

## The order I proposed, and where it stands

| # | what | why |
|---|---|---|
| ~~1~~ | ~~`harvest`~~ ✅ tasks from pytest/mypy/ruff | removes both weak links at once |
| ~~2~~ | ~~branch + PR with a report generated from the log~~ ✅ | makes supervision asynchronous |
| ~~3~~ | ~~per-task budget + giving up as a result~~ ✅ | without it, autonomous means uncontrolled |
| ~~4~~ | ~~failure memory~~ ✅ | stops repeating the same mistake |
| ~~5~~ | ~~G4: measure whole-file generation~~ ✅ **93.8%** | turned out to be far less of a limit than it looked |

All five are done. Not because the model got smarter — it is the same 12B — but
because every step now has an oracle behind it.

## The honest test that it works

Not "it solved a task". This:

> Point the crew at a repo with a red suite, come back in an hour, and find a PR
> fixing a subset of the failures, with the tests as proof, and a report
> explaining the ones it could not and why.

That is the bar. Everything above exists to get there, and the pieces are now in
place. What has **not** been done is running it against a large real repo, or the
thermal soak on the fanless Air. Those two numbers would say whether the thesis
holds outside the laboratory.

---

*Written 2026-07-27. Context in `GAPS.md` and `NEXT-STEPS.md`; the measured
findings in `IMPLEMENTATION.md` §0a.*
