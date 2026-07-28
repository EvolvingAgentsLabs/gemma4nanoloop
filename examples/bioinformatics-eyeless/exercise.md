# Two exercises: hand this repo to the crew

The example ships **working**, which is right for a reader and wrong for a
demonstration — the crew needs something to do. These two exercises create that,
and they are deliberately different shapes, because they exercise different
halves of the loop.

|  | exercise 1 | exercise 2 |
|---|---|---|
| what is wrong | code exists and is subtly wrong | code does not exist |
| who writes the goal | nobody — `harvest` reads it | you |
| who writes the "done" | nobody — the test is the oracle | you, with `--accept` |
| what it exercises | anchor repair | whole-file generation |

```bash
cp -r examples/bioinformatics-eyeless /tmp/bio
cd /tmp/bio && git init -q && git add -A && git commit -qm base
```

---

## Exercise 1 — the repo already knows what is broken

Reintroduce the canonical bioinformatics off-by-one: 0-based coordinates
returned from behind a docstring that promises 1-based, inclusive, the way BLAST
reports them.

```bash
python exercise.py break     # `restore` puts it back, `status` tells you which
```

It is a good demonstration bug because it is invisible to every gate except the
test: the code still runs and still returns plausible numbers, wrong by exactly
one.

Now the repo contains a task carrying its own oracle, and **you write neither
the goal nor the definition of done**:

```bash
python -m nanoloop.main harvest --workspace /tmp/bio --run --deliver
```

Real result with the local `gemma4:12b`:

```
[harvest] 1 task from the repo
  1. [pytest] Make the failing test ...::test_paired_domain_is_found pass
     fix in:   conserved.py        <- the code, not the test
     oracle:   1 executable criterion
=== task 1: SOLVED ===   3 steps, 3 model calls
```

### An honest note about that fix

The 12B corrected the off-by-one **and also bolted on a block-merging branch
nobody asked for**. The tests pass, but that branch mixes 1-based and 0-based
coordinates: it carries a latent bug on a path nothing exercises.

It is a useful reminder of something this project keeps rediscovering: **gates
prove what the tests cover and not one millimetre more.** An executable
criterion tells you the function does what you asked. It does not tell you the
code around it is any good. Read the diff.

---

## Exercise 2 — you decide what "done" means

Harder, and closer to real work: the file does not exist at all, so there is no
failing test to harvest and no anchor to copy. You supply the goal, and — the
part that matters — you supply the oracle.

Delete what the crew is supposed to build:

```bash
rm /tmp/bio/significance.py /tmp/bio/tests/test_significance.py
git -C /tmp/bio checkout HEAD -- discover.py   # the version that does not import it
```

Write the criterion yourself. This is the whole point of `--accept`: the
planner's own criteria are read off its own plan and pass by construction, so
for work you care about you write them. Note that this one **cannot be satisfied
by a stub** — it exercises the function and checks the biology:

```json
[
  {
    "symbol": "significance",
    "file": "significance.py",
    "check": "from sequences import EYELESS_DROME, PAX6_HUMAN\nfrom significance import significance\nr = significance(EYELESS_DROME, PAX6_HUMAN, trials=20)\nassert r['score'] > 500\nassert r['null_mean'] < 200\nassert r['score'] > r['null_max'] * 3"
  }
]
```

```bash
python -m nanoloop.main run \
  "Create significance.py with a function significance(query, subject, trials=100, seed=0) \
   that estimates whether an alignment score could be chance, by shuffling the \
   subject sequence trials times and aligning each shuffle. align() from \
   conserved.py returns an Alignment object, so use align(...).score to get the \
   number. Return a dict with keys score, null_mean, null_max." \
  --workspace /tmp/bio --accept criteria.json --max-calls 12
```

### What actually happened, including the run that failed

**First attempt — 3 rounds, 3 model calls, 243 s, and it gave up:**

```
1 criterion(s) NOT met after 3 round(s):
  - `significance` exists but its check failed:
    TypeError: significance() missing 1 required positional argument: 'seed'
```

The model was not wrong. **The specification was.** The goal asked for
`significance(query, subject, trials, seed)` — four required arguments — and the
criterion called it as `significance(query, subject, trials=20)`. Those two
cannot both be satisfied, so the loop replanned twice, faithfully rewrote the
signature it had been told to write, and stopped.

That is the most useful failure in this repo, for three reasons:

- **The criterion did its job.** A name-existence check would have gone green on
  round one. This one ran the function, and a function that cannot be called is
  not a function that works.
- **The bound did its job.** Two extra rounds, then it stopped and said what was
  wrong. A loop that retried until success would still be running.
- **The mistake was the human's.** The crew cannot notice that your goal and
  your oracle disagree; it can only report that nothing satisfies both. Writing
  the criterion is the part that is still yours, and this is what it costs to
  get it wrong.

**Second attempt**, with the contradiction removed (`trials=100, seed=0` as
defaults) and one sentence added — `align()` returns an Alignment object, so use
`align(...).score`, which is what it had got wrong the first time:

```
[memory] 1 past failure(s) inform this plan
  1. Create significance.py with the significance function  (significance.py)
 ok — 1 calls, 0 repairs, anchors=['created']
 1/1 steps, 1 plan round(s), 1 model calls | budget: 2 call(s), 2310 tokens, 74s
```

**One step, one model call, 74 seconds**, and the criterion passes for real:
`{'score': 952.0, 'null_mean': 45.45, 'null_max': 71.0}`.

Note `[memory] 1 past failure(s) inform this plan` — that is `failmem` feeding
the previous run's failure into this one's planning prompt. It is the only part
of this exercise that needed no human at all.

### And read the diff anyway

What it wrote is correct and passes. It also calls `random.seed()`, which mutates
the **global** random state: import this module, and anything else in the process
that uses `random` silently becomes deterministic too. The shipped
`significance.py` uses a local `random.Random(seed)` instead.

No gate in this repo would ever catch that, and no criterion you are likely to
write would either. Same lesson as exercise 1, from the other direction.

---

## What neither exercise can tell you

Both end in a green run, and green means exactly what the criteria say and
nothing else. Exercise 1's criterion proves the coordinates are right; it says
nothing about the branch the model invented next to them. Exercise 2's criterion
proves the function separates real signal from shuffled noise; it says nothing
about whether the statistics are *appropriate* — a z-score against a null that
is really extreme-value distributed is a judgement no assertion in that file can
make for you.

That judgement is the part that is still yours, and it is the same point the
book makes about sequence similarity itself: the computation produces a
hypothesis. Confirming it is a different job.
