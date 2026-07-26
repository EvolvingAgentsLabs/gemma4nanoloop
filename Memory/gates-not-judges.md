---
name: gates-not-judges
description: Correctness is decided by running real checkers, never by asking the model's opinion.
metadata:
  type: project
---

Whether the work is acceptable is determined by actually running the linter, the
type checker and the test suite. There is no reviewer persona asking the model
whether the change looks good.

A small model asked to judge a diff produces confident, largely meaningless
prose. The same model given a specific named error and asked to correct it is
genuinely capable. So it is shown concrete failures and never opinions.

When a check fails, its output is trimmed from the beginning rather than the end,
because the meaningful part of a stack trace — the assertion, the exception, the
failing line — sits at the very bottom.

Related: [[anchor-based-edits]], [[greedy-first]].
