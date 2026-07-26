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


def propose_plan(goal: str, repo_map: str, *, num_ctx: int | None = None) -> Plan:
    """Returns a schema-valid Plan or raises."""
    user = f"# Goal\n{goal}\n\n# Repo map (path — first docstring)\n{repo_map}"
    raw = model_ollama.chat(
        SYSTEM,
        user,
        phase="plan",
        num_ctx=num_ctx or crew.PHASE_NUM_CTX["plan"],
        temperature=0.0,
        schema=schema_of(Plan),
        tools_offered=crew.PHASE_TOOLS["plan"],
    )
    plan = Plan.model_validate(_extract_json(raw))
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
