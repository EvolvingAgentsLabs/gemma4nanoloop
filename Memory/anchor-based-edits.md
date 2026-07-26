---
name: anchor-based-edits
description: How the model changes a file without ever regenerating it.
metadata:
  type: project
---

The model never rewrites a whole file. It returns three things: which file, a
snippet of existing text copied verbatim, and what that snippet should become.

The snippet must appear exactly once. If it appears zero times, or more than
once, the operation stops and raises instead of guessing. Choosing the first of
two candidates is precisely how a small model quietly destroys a codebase.

The raised message is fed straight back as feedback, so a failure becomes a
repair attempt with a precise description of what went wrong. A loud failure you
can see beats a silent corruption you cannot.

Regenerating whole files is tempting because copying text exactly is hard for a
small model, but it is the fastest known route to a corrupted repository.

See also [[gates-not-judges]] and [[greedy-first]].
