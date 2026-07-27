# The exercise: hand it to the crew

`conserved.py` ships fixed, so `discover.py` works out of the box. To turn it
into a task, reintroduce the canonical bioinformatics bug — returning 0-based
coordinates from behind a docstring that promises 1-based:

```diff
-                "query_start": qs + 1,
+                "query_start": qs,
-                "subject_start": ss + 1,
+                "subject_start": ss,
```

Now `tests/test_conserved.py` fails and the repo contains a task carrying its
own oracle. You do not have to write the goal or the criterion:

```bash
cp -r examples/bioinformatics-eyeless /tmp/bio
cd /tmp/bio && git init -q && git add -A && git commit -qm base
python -m nanoloop.main harvest --workspace /tmp/bio --run --deliver
```

Real result with the **local** `gemma4:12b`:

```
[harvest] 1 task from the repo
  1. [pytest] Make the failing test ...::test_paired_domain_is_found pass
     fix in:   conserved.py        <- the code, not the test
     oracle:   1 executable criterion
=== task 1: SOLVED ===   3 steps, 3 model calls
```

## An honest note about that fix

The 12B corrected the off-by-one **and also bolted on a block-merging branch
nobody asked for**. The tests pass, but that branch mixes 1-based and 0-based
coordinates: it carries a latent bug on a path nothing exercises.

It is a useful reminder of something this project keeps rediscovering: **gates
prove what the tests cover and not one millimetre more.** An executable
criterion tells you the function does what you asked. It does not tell you the
code around it is any good. Read the diff.
