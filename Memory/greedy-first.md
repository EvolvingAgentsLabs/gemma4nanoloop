---
name: greedy-first
description: One deterministic attempt, then repair with feedback; extra sampling only as a last resort.
metadata:
  type: project
---

The first attempt is made at zero temperature. If it passes the checks, the work
is done — one request, nothing more.

If it fails, the exact failure text is fed back and another attempt is made. Only
after that repair loop is exhausted does the system draw additional varied
samples, and by default it draws just two rather than three.

The reason is cost: on this machine generation is slow and the chassis has no
fan, so each additional sample is paid for in both waiting and heat. Raising the
sample count to paper over poor results is the wrong fix — correct the prompt or
the checks instead.

Every additional attempt begins from a clean copy of the files, otherwise
rejected attempts pile on top of one another.

Related: [[hardware-budget]], [[thermal-throttling]], [[gates-not-judges]].
