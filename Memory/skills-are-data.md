---
name: skills-are-data
description: Capabilities are declarative entries with a deterministic runner, not individual tool schemas.
metadata:
  type: project
---

Each capability is described by a short catalog entry — a name and a one-line
statement of when it applies — that lives in the prompt. The full body is only
loaded when that capability is actually selected.

A catalog entry costs roughly 23 tokens. A full tool schema costs 300 to 800.
Adding a new capability therefore costs almost nothing, and a dozen of them cost
less than two tools would.

Each one is carried out by fixed, deterministic code rather than by prose the
model is expected to imitate, because imitation is unreliable at this size.

There is deliberately no separate lookup capability for browsing the catalog:
the catalog is already in the prompt, so such a thing would be a wasted slot and
a wasted round trip.

Choosing between two similarly-worded entries is the same failure mode as
choosing between two similar tools, so each entry carries example phrasings that
act as routing anchors. Related: [[orchestrator-is-a-graph]].
