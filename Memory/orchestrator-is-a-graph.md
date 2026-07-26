---
name: orchestrator-is-a-graph
description: Why the sequence of phases is fixed in code rather than chosen by the model.
metadata:
  type: project
---

The order of work — plan, build, review, test, ship — is hard-coded as a state
machine rather than left to the language model.

Letting the model choose what to do next requires a delegation tool, and
delegating is the single hardest capability for a small model to use reliably.
It also forces every capability into one binding, which inflates the schema cost
paid on every single request.

With a fixed sequence, each request offers only the handful of capabilities that
the current stage can actually use, cutting peak schema cost by about 85%. The
code decides the order; the model only decides what happens inside one stage.

The rigidity is the point. Related: [[context-is-compiled]], [[skills-are-data]].
