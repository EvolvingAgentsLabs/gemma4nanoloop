"""Phase 2: propose(step, ctx_text, feedback, temperature) -> Edit.

The measurement that decides the project (PLAN.md §7 Q1) happens here: does the
model emit an `anchor` that matches its target file exactly once?

It is copying literal text out of a file it was just shown. The system prompt
therefore spends most of its budget on that one instruction, because that — not
code quality — is the expected dominant failure mode.
"""

from __future__ import annotations

from . import calllog, crew, model_ollama
from .crew import Edit, schema_of
from .planner import _extract_json

SYSTEM = """You edit source files by replacing an exact anchor.

Return three fields:
  path         the file to edit (use the current step's file)
  anchor       text COPIED VERBATIM from the file contents shown to you
  replacement  what that text becomes

THE ANCHOR IS THE HARD PART. It must:
- be copied character-for-character from the file contents above, including
  indentation and punctuation. Do not retype it from memory. Do not reformat it.
- appear EXACTLY ONCE in that file. If the line you want appears more than once,
  include the lines above and below it until the whole anchor is unique.
- be small: a few lines, not the whole function, and never the whole file.

To append to a file, anchor on its last few lines and include them at the start
of your replacement.

Output JSON matching the schema. Nothing else."""


CREATE_SYSTEM = """You write ONE complete new source file.

Return two fields:
  path     the file to create (use the current step's file)
  content  the ENTIRE contents of that file

Rules:
- The file does not exist yet. There is nothing to copy and no anchor to match.
- Write the WHOLE file, top to bottom: imports first, then the code.
- It must PARSE. Close every parenthesis, bracket and quote you open. Before you
  return, re-read your output and check the brackets balance.
- Only call functions with the parameters the context shows they actually take.
  Do not invent arguments for a method you were shown.
- Import ONLY what you actually use. An unused import fails the lint gate.
- Import ONLY from modules listed in the context. Never guess a package name.
- Keep it short: one focused file, no extras.
- Style: module docstring, then a BLANK LINE, then imports.

Output JSON matching the schema. Nothing else."""


def propose_new_file(
    step: crew.Step,
    ctx_text: str,
    feedback: str = "",
    temperature: float = 0.0,
    *,
    num_ctx: int | None = None,
    step_index: int | None = None,
    attempt: int | None = None,
) -> Edit:
    """Whole-file generation, for a file that does not exist yet.

    Kept apart from propose() deliberately. Sharing the anchor prompt for this
    produced 0/4 valid files, every one with unbalanced brackets: the model was
    being told to copy an anchor that cannot exist, while also writing a file
    from nothing. The returned Edit carries an empty anchor, which apply_edit
    accepts only when the file is genuinely missing.
    """
    phase = "repair" if feedback else "build"
    raw = model_ollama.chat(
        CREATE_SYSTEM,
        ctx_text,
        phase=phase,
        num_ctx=num_ctx or crew.PHASE_NUM_CTX[phase],
        temperature=temperature,
        schema=schema_of(crew.NewFile),
        tools_offered=crew.tools_for(phase),
        step_index=step_index,
        attempt=attempt,
    )
    data = _extract_json(raw)
    data.setdefault("path", step.target_file)
    new = crew.NewFile.model_validate(data)
    return Edit(path=new.path or step.target_file, anchor="", replacement=new.content)


def propose(
    step: crew.Step,
    ctx_text: str,
    feedback: str = "",
    temperature: float = 0.0,
    *,
    num_ctx: int | None = None,
    step_index: int | None = None,
    attempt: int | None = None,
) -> Edit:
    """One edit proposal. `ctx_text` is an already-rendered Ctx (D6)."""
    phase = "repair" if feedback else "build"
    raw = model_ollama.chat(
        SYSTEM,
        ctx_text,
        phase=phase,
        num_ctx=num_ctx or crew.PHASE_NUM_CTX[phase],
        temperature=temperature,
        schema=schema_of(Edit),
        tools_offered=crew.tools_for(phase),
        step_index=step_index,
        attempt=attempt,
    )
    data = _extract_json(raw)
    # The model reliably knows what to write and less reliably where; the step
    # already names the file, so don't let a hallucinated path redirect the edit.
    data.setdefault("path", step.target_file)
    edit = Edit.model_validate(data)
    if not edit.path:
        edit.path = step.target_file

    calllog.record(
        calllog.CallRecord(
            phase=f"{phase}.parsed",
            prompt_tokens=None,
            tools_offered=[],
            raw_output="",
            parsed_output={
                "path": edit.path,
                "anchor_len": len(edit.anchor),
                "replacement_len": len(edit.replacement),
            },
            parse_ok=True,
            latency_ms=0,
            wall_clock_since_start=calllog.now_offset(),
            step_index=step_index,
            attempt=attempt,
        )
    )
    return edit
