---
name: thermal-throttling
description: The fanless chassis slows down under sustained load, so late work is slower than early work.
metadata:
  type: reference
---

Because the machine has no active cooling, a long run heats the chassis and the
processor reduces its clock. Benchmark throughput measured on a fresh machine
does not describe what happens thirty steps into a job.

This must be measured rather than assumed: record how long each step takes and
plot it against the step number. If the thirtieth step takes more than twice as
long as the first, either insert pauses between steps or stop drawing extra
samples partway through.

This is a real constraint on this machine, not a footnote. It directly limits
how affordable extra sampling is; see [[greedy-first]] and [[hardware-budget]].
