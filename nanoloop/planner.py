"""Phase 1: propose_plan(goal, repo_map) -> Plan.

Structured output only, zero tools (PHASE_TOOLS["plan"] == []). The planner's
whole job is to convert one long-horizon goal into N horizon-1 steps (D2); it
never edits anything, so offering it a tool would only add schema cost and a
chance to go wrong.
"""

from __future__ import annotations

import json

from . import calllog, crew, model_ollama
from .crew import Plan, schema_of

SYSTEM = """You are the planner for a small engineering crew.

Break the goal into the SMALLEST number of ordered steps that achieves it.

Rules:
- Each step edits EXACTLY ONE file. If a change touches two files, that is two steps.
- `target_file` must be a path that appears in the repo map, or a new file in an
  existing directory. Never invent a directory.
- Each step must be small enough to do without seeing any other file.
- `intent` states what must be TRUE when the step is done, not how to do it.
- No step for running tests or linters. Those run automatically after every step.
- To CREATE a new file, still make it a step; `target_file` is the new path.
- Set `defines` to the function or class name the step must add (e.g. "by_tag").
  Leave it empty only when the step changes behaviour without adding a name.

SKILLS. If a listed skill matches a step, set `skill` to its name and `skill_data`
to a JSON object of its parameters. A skill step runs deterministic code instead
of generating source, so prefer one whenever it fits. Leave `skill` empty ("")
for ordinary code edits. Never invent a skill name that is not listed.

ACCEPTANCE. After the steps, fill `acceptance` with what must be true when the
WHOLE GOAL is finished: each function or class the goal asks for, and the file
it belongs in. Read these off the GOAL, not off your steps — if the goal names
two things and your steps only cover one, `acceptance` must still list both.

Output JSON matching the schema. Nothing else."""


def _extract_json(raw: str) -> dict:
    """Pull a JSON object out of the reply.

    Constrained decoding should make this a no-op, but PLAN.md §6 warns against
    trusting native tool calling as a guarantee (~86% on tau2-bench is good, not
    sufficient). Fenced blocks and prose preambles are the two observed failures.
    """
    s = raw.strip()
    if s.startswith("```"):
        s = s.split("```")[1] if "```" in s[3:] else s[3:]
        if s.startswith("json"):
            s = s[4:]
        s = s.strip()
    try:
        return json.loads(s)
    except json.JSONDecodeError:
        start, end = s.find("{"), s.rfind("}")
        if start != -1 and end > start:
            return json.loads(s[start : end + 1])
        raise


def propose_plan(
    goal: str, repo_map: str, *, num_ctx: int | None = None, skills_catalog: str | None = None
) -> Plan:
    """Returns a schema-valid Plan or raises.

    The skills catalog is injected HERE, not in the build phase: routing to a
    capability is a planning decision (D5), and a step that names a skill costs
    zero model calls to execute.
    """
    if skills_catalog is None:
        from . import skills as skills_mod

        skills_catalog = skills_mod.catalog_text()
    user = f"# Goal\n{goal}\n\n# Repo map (path — first docstring)\n{repo_map}"
    if skills_catalog:
        user += f"\n\n# Available skills (name: when to use)\n{skills_catalog}"
    # Greedy first (D7), then retry WITH TEMPERATURE.
    #
    # A greedy sample can fall into degenerate repetition and never escape:
    # observed "items carrying the tags are items carrying the tags are ..." run
    # to the 4096-token cap, producing unterminated JSON. Re-running at
    # temperature 0 would reproduce it exactly — sampling is what breaks the
    # loop. The build phase already survives a bad sample via its repair loop;
    # planning had no such path and simply crashed with a traceback.
    last: Exception | None = None
    for attempt, temperature in enumerate((0.0, 0.3, 0.6)):
        try:
            raw = model_ollama.chat(
                SYSTEM,
                user,
                phase="plan",
                num_ctx=num_ctx or crew.PHASE_NUM_CTX["plan"],
                temperature=temperature,
                schema=schema_of(Plan),
                tools_offered=crew.PHASE_TOOLS["plan"],
                attempt=attempt,
            )
        except RuntimeError as e:
            # Transient backend failure — an empty completion, a rate limit.
            # Retrying is precisely the right response, and not catching it here
            # turned a recoverable hiccup into a traceback that killed the run.
            last = e
            continue
        try:
            plan = Plan.model_validate(_extract_json(raw))
            break
        except (json.JSONDecodeError, ValueError) as e:
            last = e
    else:
        raise RuntimeError(
            f"the planner returned no valid plan in 3 attempts. Last error: {last}. "
            f"A truncated reply usually means a repetition loop hit the output cap."
        ) from last
    calllog.record(
        calllog.CallRecord(
            phase="plan.parsed",
            prompt_tokens=None,
            tools_offered=[],
            raw_output="",
            parsed_output=plan.model_dump(),
            parse_ok=True,
            latency_ms=0,
            wall_clock_since_start=calllog.now_offset(),
        )
    )
    return plan
