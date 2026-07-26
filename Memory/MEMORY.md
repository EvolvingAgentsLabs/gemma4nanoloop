# Memory index

- [anchor-based-edits](anchor-based-edits.md) (project) — How the model changes a file without ever regenerating it.
- [context-is-compiled](context-is-compiled.md) (project) — Each request is assembled fresh from what the model needs, never from the conversation history.
- [gates-not-judges](gates-not-judges.md) (project) — Correctness is decided by running real checkers, never by asking the model's opinion.
- [greedy-first](greedy-first.md) (project) — One deterministic attempt, then repair with feedback; extra sampling only as a last resort.
- [hardware-budget](hardware-budget.md) (project) — Memory and thermal limits of the 16 GB fanless M4 Air that drive every design decision.
- [orchestrator-is-a-graph](orchestrator-is-a-graph.md) (project) — Why the sequence of phases is fixed in code rather than chosen by the model.
- [skills-are-data](skills-are-data.md) (project) — Capabilities are declarative entries with a deterministic runner, not individual tool schemas.
- [thermal-throttling](thermal-throttling.md) (reference) — The fanless chassis slows down under sustained load, so late work is slower than early work.
