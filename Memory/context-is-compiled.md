---
name: context-is-compiled
description: Each request is assembled fresh from what the model needs, never from the conversation history.
metadata:
  type: project
---

Every request is built from scratch: the overall objective, the titles of
finished work, the current unit of work, the relevant slice of the file being
changed, and the most recent failure if there was one.

The running conversation is never replayed. History accumulates irrelevant
material, pushes the useful parts out of the window, and grows without bound.

If the model genuinely seems to need more than this, the unit of work is too
large and should be split rather than the assembly being expanded.

Related: [[orchestrator-is-a-graph]], [[hardware-budget]].
