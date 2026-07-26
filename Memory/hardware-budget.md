---
name: hardware-budget
description: Memory and thermal limits of the 16 GB fanless M4 Air that drive every design decision.
metadata:
  type: project
---

The target machine has 16 GB of unified memory with no fan. Gemma 4 12B at Q4
occupies roughly 7.6 GB of that, leaving very little headroom.

Consequences:
- Only ONE large language model is ever resident. There is no room for a second
  routing model such as E4B; see [[orchestrator-is-a-graph]] for how routing is
  handled instead.
- At most about 3 GB is available for the attention cache, which is why flash
  attention and q8_0 cache quantization are both enabled.
- Sustained generation heats the chassis and the machine slows down. That effect
  is tracked separately in [[thermal-throttling]].
- Decoding runs at roughly 15-25 tokens per second, so a 300-token edit takes
  15-20 seconds. Drawing extra samples is therefore costly; see [[greedy-first]].
