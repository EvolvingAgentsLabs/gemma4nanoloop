"""The crew: a phase-scoped state machine that replaces the DeepAgents orchestrator.

PLAN.md's architecture decisions live here, so read D1-D8 before changing anything.

D1  The orchestrator is a GRAPH, not an LLM. Plan->Build->Review->Test->Ship is a
    fixed sequence. Making it a model decision costs the `task` tool (meta-tool-use,
    the hardest thing for a small model) and forces every tool into one binding.
    The graph decides the sequence; the model only decides WITHIN a step.
D2  The plan is typed JSON, executed by code. Long-horizon reasoning becomes
    horizon-1 reasoning performed N times — the only kind a 12B does reliably.
D3  Verification leaves the model. ruff/mypy/pytest replace the reviewer subagent.
    The model sees failures, never opinions.
D4  Edits are anchor-based and fail loudly (see anchors.py).
D6  Context is COMPILED, not accumulated. Never the transcript.
D7  Greedy first, diversity second. Best-of-N only after the greedy sample fails.
D8  Every candidate starts from a clean tree (see snapshot.py).

Phase-scoped tool binding is the measured win: peak schema cost per call drops
from ~5,548 tokens to ~817 (-85%) by never offering a tool the current phase
cannot use.
"""

from __future__ import annotations

import os
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path

from pydantic import BaseModel, Field

from . import anchors, calllog
from .anchors import AnchorError

# ---------------------------------------------------------------------------
# Typed plan (D2)
# ---------------------------------------------------------------------------


class Step(BaseModel):
    """One horizon-1 unit of work. Small enough that the model never needs the
    whole repo in context — if it does, the step is too big and must be split."""

    title: str = Field(description="Short imperative summary of this step.")
    target_file: str = Field(description="Repo-relative path this step edits.")
    intent: str = Field(description="What must be true after this step.")


class Plan(BaseModel):
    steps: list[Step] = Field(description="Ordered steps. Each edits one file.")


class Edit(BaseModel):
    """An anchor-based edit. The model copies `anchor` verbatim from the file."""

    path: str = Field(description="Repo-relative file to edit.")
    anchor: str = Field(description="Exact existing text to replace. Must be unique.")
    replacement: str = Field(description="Text to put in its place.")


def schema_of(model: type[BaseModel]) -> dict:
    """JSON Schema for structured decoding. ~198 tok for Plan, ~104 for Edit."""
    return model.model_json_schema()


# ---------------------------------------------------------------------------
# Phase binding (the -85% result)
# ---------------------------------------------------------------------------

PHASE_TOOLS: dict[str, list[str]] = {
    "plan": [],  # ~0 tok   - pure structured output
    "build": ["read_file", "use_skill"],  # ~374 tok
    "repair": ["read_file"],  # ~34 tok
    "test": [],  # ~0 tok   - gates are deterministic (D3)
    "ship": ["run_shell"],  # ~817 tok - the peak
}

# Per-phase context budget. LiteRT-LM tops out at 32K; never design a phase that
# needs the whole repo (PLAN.md hardware table).
PHASE_NUM_CTX: dict[str, int] = {
    "plan": 16384,
    "build": 8192,
    "repair": 8192,
    "test": 4096,
    "ship": 4096,
}

DEFAULT_GATES: list[str] = [
    "ruff check .",
    "ruff format --check .",
    "python -m pytest -q",
]

# On a fanless Air, every extra candidate costs wall-clock and thermal headroom.
# PLAN.md §6 names raising this as an anti-pattern: fix the prompt or the gate.
DEFAULT_N_CANDIDATES = int(os.environ.get("NANOLOOP_N_CANDIDATES", "2"))
DEFAULT_MAX_REPAIRS = int(os.environ.get("NANOLOOP_MAX_REPAIRS", "2"))

GATE_OUTPUT_LIMIT = 2000


# ---------------------------------------------------------------------------
# Gates (D3)
# ---------------------------------------------------------------------------


@dataclass
class GateResult:
    command: str
    ok: bool
    output: str

    @property
    def failed(self) -> bool:
        return not self.ok


def _truncate_front(text: str, limit: int = GATE_OUTPUT_LIMIT) -> str:
    """Truncate from the FRONT, keeping the tail.

    Tracebacks carry their payload at the tail — the assertion, the exception
    type, the failing line. Truncating from the back throws away the only part
    the repair loop can act on. This is a correctness detail, not formatting.
    """
    if len(text) <= limit:
        return text
    return "[...truncated...]\n" + text[-limit:]


def _gate_env() -> dict[str, str]:
    """PATH with the running interpreter's bin/ first.

    Gates run through `sh`, which does not inherit an activated virtualenv. Bare
    `ruff` then resolves against the system PATH and fails with
    `ruff: command not found` — which the repair loop dutifully feeds back to
    the model, burning attempts on an error no edit can fix. Observed on the
    first end-to-end run: 4 model calls, all with exact anchors, all wasted.
    """
    env = dict(os.environ)
    bindir = str(Path(sys.executable).parent)
    env["PATH"] = bindir + os.pathsep + env.get("PATH", "")
    return env


def run_gate(cwd: Path | str, gates: list[str] | None = None) -> list[GateResult]:
    """Run quality gates in order and stop at the first failure.

    NOTE the `is None` test. `gates or DEFAULT_GATES` makes an explicitly empty
    `gates=[]` fall through to the defaults — a trap already hit once and fixed
    (PLAN.md §1). Do not reintroduce it.
    """
    if gates is None:
        gates = DEFAULT_GATES

    env = _gate_env()
    results: list[GateResult] = []
    for cmd in gates:
        try:
            proc = subprocess.run(
                cmd,
                shell=True,
                capture_output=True,
                text=True,
                timeout=300,
                cwd=str(cwd),
                env=env,
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            res = GateResult(cmd, proc.returncode == 0, _truncate_front(out))
        except subprocess.TimeoutExpired:
            res = GateResult(cmd, False, f"[timeout after 300s] {cmd}")
        except OSError as e:
            res = GateResult(cmd, False, f"[error] {e}")
        results.append(res)
        if res.failed:
            break  # first failure is the actionable one; the rest is noise
    return results


def gate_feedback(results: list[GateResult]) -> str:
    """Render gate failures as exact-error feedback for the repair loop."""
    for r in results:
        if r.failed:
            return f"The command `{r.command}` failed:\n\n{r.output}"
    return ""


# ---------------------------------------------------------------------------
# Edits (D4)
# ---------------------------------------------------------------------------


def apply_edit(root: Path | str, edit: Edit, *, fuzzy: bool | None = None) -> str:
    """Apply an anchor-based edit. Raises AnchorError on 0 or >1 matches.

    A hard failure you can see beats a silent corruption you cannot (D4). The
    raised message is fed straight into the repair loop.
    """
    root = Path(root)
    target = (root / edit.path).resolve()
    if not target.is_relative_to(root.resolve()):
        raise ValueError(f"path escapes workspace: {edit.path}")
    if not target.exists():
        raise AnchorError(anchors.Match.NOT_FOUND, f"file does not exist: {edit.path}")

    text = target.read_text(encoding="utf-8")
    res = anchors.locate(text, edit.anchor, fuzzy=fuzzy)
    updated = text[: res.start] + edit.replacement + text[res.end :]
    target.write_text(updated, encoding="utf-8")
    return res.kind.value


# ---------------------------------------------------------------------------
# Context compiler (D6)
# ---------------------------------------------------------------------------


@dataclass
class Ctx:
    """Rendered fresh every turn. Never accumulates, never holds a transcript.

    If the model truly needs more than this, the step is too big — split it
    (PLAN.md §6). Growing Ctx is the wrong fix.
    """

    goal: str
    done: list[str] = field(default_factory=list)  # completed step TITLES only
    step: Step | None = None
    file_slice: str = ""
    last_error: str = ""
    skills_catalog: str = ""

    def render(self) -> str:
        parts = [f"# Goal\n{self.goal}"]
        if self.done:
            parts.append("# Completed steps\n" + "\n".join(f"- {t}" for t in self.done))
        if self.step:
            parts.append(
                f"# Current step\n{self.step.title}\n"
                f"file: {self.step.target_file}\n"
                f"intent: {self.step.intent}"
            )
        if self.file_slice:
            parts.append(
                f"# Current contents of {self.step.target_file if self.step else 'file'}\n"
                f"```\n{self.file_slice}\n```"
            )
        if self.skills_catalog:
            parts.append(f"# Available skills\n{self.skills_catalog}")
        if self.last_error:
            parts.append(
                f"# The previous attempt FAILED\n{self.last_error}\n"
                f"Fix exactly this. Do not change anything else."
            )
        return "\n\n".join(parts)


# ---------------------------------------------------------------------------
# The build loop (D7)
# ---------------------------------------------------------------------------


@dataclass
class StepResult:
    step: Step
    ok: bool
    model_calls: int
    repair_attempts: int
    anchor_kinds: list[str] = field(default_factory=list)
    final_error: str = ""


def build_step(
    step: Step,
    ctx: Ctx,
    workspace: Path | str,
    propose,  # (step, ctx_text, feedback, temperature) -> Edit
    *,
    gates: list[str] | None = None,
    n_candidates: int = DEFAULT_N_CANDIDATES,
    max_repairs: int = DEFAULT_MAX_REPAIRS,
    snapshot=None,  # snapshot.Workspace-like: .save() / .restore()
    step_index: int | None = None,
) -> StepResult:
    """Greedy attempt -> bounded repair loop -> best-of-N only if greedy failed.

    Typical cost is ONE model call. Best-of-N activates only after the greedy
    sample fails a gate, because on this hardware a 300-token edit is 15-20s and
    diversity is expensive (D7).
    """
    workspace = Path(workspace)
    calls = 0
    repairs = 0
    kinds: list[str] = []
    feedback = ""

    def attempt(temperature: float, attempt_no: int) -> tuple[bool, str]:
        """One propose -> apply -> gate cycle. Returns (ok, error_text)."""
        nonlocal calls, kinds
        if snapshot is not None:
            snapshot.save()  # D8: every candidate starts from a clean tree

        ctx.last_error = feedback
        ctx.file_slice = _read_slice(workspace, step.target_file)
        try:
            edit = propose(step, ctx.render(), feedback, temperature)
            calls += 1
        except Exception as e:  # noqa: BLE001
            calls += 1
            return False, f"the model did not return a valid Edit: {e}"

        try:
            kind = apply_edit(workspace, edit)
            kinds.append(kind)
        except AnchorError as e:
            kinds.append(e.kind.value)
            if snapshot is not None:
                snapshot.restore()
            return False, str(e)
        except (ValueError, OSError) as e:
            if snapshot is not None:
                snapshot.restore()
            return False, str(e)

        results = run_gate(workspace, gates)
        if all(r.ok for r in results):
            return True, ""
        if snapshot is not None:
            snapshot.restore()
        return False, gate_feedback(results)

    # --- greedy ---
    ok, err = attempt(0.0, 0)
    if ok:
        return StepResult(step, True, calls, 0, kinds)
    feedback = err

    # --- bounded repair, with the exact error fed back ---
    while repairs < max_repairs:
        repairs += 1
        ok, err = attempt(0.0, repairs)
        if ok:
            return StepResult(step, True, calls, repairs, kinds)
        feedback = err

    # --- best-of-N, last resort only (D7) ---
    for i in range(1, max(1, n_candidates)):
        ok, err = attempt(0.2 * (i + 1), max_repairs + i)
        if ok:
            return StepResult(step, True, calls, repairs, kinds)
        feedback = err

    return StepResult(step, False, calls, repairs, kinds, feedback)


def _read_slice(workspace: Path, path: str, limit: int = 12000) -> str:
    """Current contents of the target file, bounded.

    The model must copy an anchor out of this text verbatim, so it is shown in
    full whenever it fits. Beyond the limit we keep the HEAD — unlike gate
    output, a source file's structure lives at the top.
    """
    p = Path(workspace) / path
    if not p.exists():
        return "[file does not exist yet]"
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
    except OSError as e:
        return f"[unreadable: {e}]"
    return text if len(text) <= limit else text[:limit] + "\n[...truncated...]"


def run_plan(
    plan: Plan,
    goal: str,
    workspace: Path | str,
    propose,
    *,
    gates: list[str] | None = None,
    on_step=None,
    **kw,
) -> list[StepResult]:
    """Iterate the typed plan (D2). The graph decides the sequence, not the model."""
    ctx = Ctx(goal=goal)
    out: list[StepResult] = []
    for i, step in enumerate(plan.steps):
        ctx.step = step
        res = build_step(step, ctx, workspace, propose, gates=gates, step_index=i, **kw)
        out.append(res)
        if on_step:
            on_step(i, res)
        if not res.ok:
            break  # a broken step invalidates every step that follows it
        ctx.done.append(step.title)
        ctx.last_error = ""
    return out


__all__ = [
    "Step",
    "Plan",
    "Edit",
    "schema_of",
    "Ctx",
    "GateResult",
    "StepResult",
    "PHASE_TOOLS",
    "PHASE_NUM_CTX",
    "DEFAULT_GATES",
    "run_gate",
    "gate_feedback",
    "apply_edit",
    "build_step",
    "run_plan",
    "calllog",
]
