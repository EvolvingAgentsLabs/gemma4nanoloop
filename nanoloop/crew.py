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

import ast
import json
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
    # Skill routing happens at PLAN time, with the catalog in the planner's
    # prompt (D5: the model routes to and parameterizes a capability; the graph
    # runs it). A step with a skill costs ZERO model calls in the build phase —
    # the executor is deterministic Python.
    skill: str = Field(default="", description="Skill name to run, or empty to edit code.")
    skill_data: str = Field(default="", description="JSON parameters for the skill.")
    # Deterministic acceptance for THIS step. The gates prove the repo is
    # healthy; they cannot prove a step did its own job. Observed: a step titled
    # "Add by_tag method" instead made complete() case-insensitive — valid code,
    # all gates green, reported ok, and by_tag never existed. The model only has
    # to NAME the symbol; code checks it (D2/D3).
    defines: str = Field(
        default="",
        description="Function/class name this step must create, e.g. 'by_tag'. "
        "Empty if the step changes behaviour without adding a name.",
    )


class Acceptance(BaseModel):
    """One checkable statement about the FINISHED work.

    Derived from the GOAL, never from the steps. That distinction is the whole
    point: criteria read off your own plan are circular and pass by
    construction. Observed failure — goal "add by_tag AND make add accept tags",
    planner emitted ONE step covering only add(), reported 1/1 ok, and by_tag
    was never mentioned again. A goal-level criterion catches exactly that.
    """

    symbol: str = Field(description="Function or class that must exist when done.")
    file: str = Field(description="Repo-relative file it must be defined in.")


class Plan(BaseModel):
    steps: list[Step] = Field(description="Ordered steps. Each edits one file.")
    acceptance: list[Acceptance] = Field(
        default_factory=list,
        description="What must be true when the WHOLE goal is done. Derive from "
        "the goal itself, not from the steps above.",
    )


class Edit(BaseModel):
    """An anchor-based edit. The model copies `anchor` verbatim from the file.

    An EMPTY anchor means "create this file", and is legal ONLY when the file
    does not exist (see apply_edit). That is not a hole in D4: D4 forbids
    regenerating an EXISTING file, which is where a 12B corrupts work that is
    already correct. A file that does not exist yet has nothing to corrupt, and
    without this the crew cannot add a single new module or test.
    """

    path: str = Field(description="Repo-relative file to edit.")
    anchor: str = Field(
        description="Exact existing text to replace, unique in the file. "
        "Leave EMPTY only when creating a new file."
    )
    replacement: str = Field(description="Text to put in its place, or the new file's contents.")


class NewFile(BaseModel):
    """A file that does not exist yet.

    Deliberately a SEPARATE schema from Edit. Reusing Edit with an empty anchor
    forces the anchor-copying prompt onto a task that has no anchor, and the
    model tries to satisfy both jobs at once. Measured: 0/4 successes that way,
    all syntactically invalid Python.
    """

    path: str = Field(description="Repo-relative path of the new file.")
    content: str = Field(description="Complete contents of the file.")


def schema_of(model: type[BaseModel]) -> dict:
    """JSON Schema for structured decoding, with EVERY field required.

    Pydantic omits any field with a `default=` from `required`, and constrained
    decoding then treats it as optional — so the model simply does not emit it.

    That made two verification mechanisms silently inert: `Step.defines` came
    back "" on the very step that should have declared `by_tag`, and
    `Plan.acceptance` came back `[]`, so plan verification passed vacuously
    while `by_tag` was missing from the code. Both checks appeared to run and
    neither could ever fail.

    The Python defaults stay, so code can still build a Step without them; only
    the schema handed to the model is tightened.
    """
    schema = model.model_json_schema()

    def require_all(node: dict) -> None:
        if node.get("type") == "object" and "properties" in node:
            node["required"] = list(node["properties"])
        for defn in node.get("$defs", {}).values():
            require_all(defn)

    require_all(schema)
    return schema


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
        # Create — only for a file that does not exist. See Edit's docstring:
        # this is not a write_file backdoor, it is the only way to add a module.
        if edit.anchor.strip():
            raise AnchorError(
                anchors.Match.NOT_FOUND,
                f"file does not exist: {edit.path}. To create it, leave `anchor` "
                f"empty and put the whole file in `replacement`.",
            )
        _check_syntax(edit.path, edit.replacement)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(edit.replacement, encoding="utf-8")
        return "created"

    if not edit.anchor.strip():
        # D4, the part that matters: never regenerate a file that already exists.
        raise AnchorError(
            anchors.Match.AMBIGUOUS,
            f"{edit.path} already exists, so `anchor` cannot be empty — an empty "
            f"anchor would overwrite the whole file. Copy the exact text to replace.",
        )

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
    # Only rendered when the target file does NOT exist. Writing a new module
    # means writing its imports, and without the map the model invents package
    # names — observed: `from todo_app.store import Store` in a repo whose
    # package is `todo`. For an edit it is noise, so it stays out.
    repo_map: str = ""

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
        if self.repo_map:
            parts.append(
                f"# Modules that exist (import ONLY from these — do not invent "
                f"package names)\n{self.repo_map}"
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


def autofix(workspace: Path | str, path: str) -> None:
    """Apply ruff's own mechanical fixes to one file before gating it.

    D3 says verification leaves the model. The same logic applies to FORMATTING:
    asking a small model to emit import-sorted, ruff-clean source wastes repair
    cycles on problems a tool fixes deterministically and perfectly.

    Observed across three runs of one task: the model produced correct logic that
    failed the gate on `I001 import block un-sorted` and `F401 pytest imported
    but unused` — both in ruff's auto-fixable set. Each cost a full repair round
    trip and still came back imperfect.

    Only mechanical fixes are applied. A genuine error (undefined name, bad call,
    failing test) survives untouched and still reaches the model as feedback.
    """
    target = Path(workspace) / path
    if target.suffix != ".py" or not target.exists():
        return
    env = _gate_env()
    for cmd in (["ruff", "check", "--fix", "--quiet", path], ["ruff", "format", "--quiet", path]):
        try:
            subprocess.run(
                cmd, cwd=str(workspace), capture_output=True, text=True, timeout=60, env=env
            )
        except (subprocess.TimeoutExpired, OSError):
            return  # ruff missing or wedged: let the real gate report it


def defines_symbol(workspace: Path | str, path: str, name: str) -> bool:
    """Is `name` defined in this Python file?

    Accepts a DOTTED name (`Store.add`) as well as a bare one. The model writes
    qualified names naturally, and treating `Store.add` as a literal identifier
    fails on correct code — observed as a false "not defined" for a method that
    was right there. A false positive here blocks working code, which is worse
    than not checking at all.
    """
    target = Path(workspace) / path
    if not name:
        return True  # nothing claimed, nothing to check
    if target.suffix != ".py":
        return True  # not parseable here; let the gates speak instead
    if not target.exists():
        # A name WAS claimed and there is no file to hold it. Returning True
        # here would let "define by_tag in store.py" pass when store.py does
        # not exist — the exact silent pass this function exists to prevent.
        return False
    try:
        tree = ast.parse(target.read_text(encoding="utf-8"))
    except (OSError, SyntaxError):
        return False
    defs = [
        n
        for n in ast.walk(tree)
        if isinstance(n, ast.ClassDef | ast.FunctionDef | ast.AsyncFunctionDef)
    ]
    if "." in name:
        owner, _, member = name.rpartition(".")
        for node in defs:
            if isinstance(node, ast.ClassDef) and node.name == owner:
                return any(
                    isinstance(c, ast.FunctionDef | ast.AsyncFunctionDef) and c.name == member
                    for c in node.body
                )
        name = member  # owner absent: fall back to the bare member
    return any(n.name == name for n in defs)


class SyntaxErrorInEdit(ValueError):
    """Generated Python does not parse. Feeds the repair loop like any gate."""


def _check_syntax(path: str, text: str) -> None:
    """Reject unparseable Python BEFORE it touches the disk.

    Cheaper and far more precise than letting `ruff check` catch it a gate later:
    the model gets the line, the column and the expected token instead of a lint
    summary, and a broken file never exists even momentarily. The observed
    failure was `store.add("Task 1", ["work"]` — one missing paren, repeated
    across four attempts.
    """
    if not path.endswith(".py"):
        return
    try:
        ast.parse(text)
    except SyntaxError as e:
        raise SyntaxErrorInEdit(
            f"the generated Python is not valid: line {e.lineno}, {e.msg}. "
            f"Check that every bracket and parenthesis is closed, then return "
            f"the COMPLETE corrected file."
        ) from e


def run_skill(step: Step, workspace: Path | str) -> str:
    """Execute the skill a plan step selected. Deterministic Python, no model."""
    from . import skills as skills_mod

    sk = skills_mod.get(step.skill)
    if sk is None:
        available = ", ".join(s.name for s in skills_mod.discover()) or "none"
        raise ValueError(f"no skill '{step.skill}'; available: {available}")
    params: dict = {}
    if step.skill_data:
        try:
            parsed = json.loads(step.skill_data)
            params = parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError as e:
            raise ValueError(f"skill_data is not valid JSON: {e}") from e
    if not sk.has_executor:
        raise ValueError(f"skill '{step.skill}' has no deterministic executor")
    return skills_mod.execute(sk, params, Path(workspace))


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

    # A skill step is deterministic: the planner already chose it and supplied
    # the parameters, so there is nothing left for the model to decide (D5).
    # Zero model calls, and the executor either works or raises.
    if step.skill:
        if snapshot is not None:
            snapshot.save()
        try:
            out = run_skill(step, workspace)
            kinds.append("skill")
        except Exception as e:  # noqa: BLE001
            if snapshot is not None:
                snapshot.restore()
            return StepResult(step, False, 0, 0, ["skill_failed"], f"{type(e).__name__}: {e}")
        results = run_gate(workspace, gates)
        if all(r.ok for r in results):
            return StepResult(step, True, 0, 0, kinds)
        if snapshot is not None:
            snapshot.restore()
        return StepResult(step, False, 0, 0, kinds, f"{out}\n\n{gate_feedback(results)}")

    def attempt(temperature: float, attempt_no: int) -> tuple[bool, str]:
        """One propose -> apply -> gate cycle. Returns (ok, error_text)."""
        nonlocal calls, kinds
        if snapshot is not None:
            snapshot.save()  # D8: every candidate starts from a clean tree

        ctx.last_error = feedback
        ctx.file_slice = _read_slice(workspace, step.target_file)
        # See Ctx.repo_map: needed only when writing a file from nothing.
        if not (workspace / step.target_file).exists():
            from . import repomap

            ctx.repo_map = repomap.build(workspace)
        else:
            ctx.repo_map = ""
        try:
            edit = propose(step, ctx.render(), feedback, temperature)
            calls += 1
        except Exception as e:  # noqa: BLE001
            calls += 1
            return False, f"the model did not return a valid Edit: {e}"

        try:
            kind = apply_edit(workspace, edit)
            kinds.append(kind)
            autofix(workspace, edit.path)  # mechanical lint/format, not the model's job
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
        if not all(r.ok for r in results):
            if snapshot is not None:
                snapshot.restore()
            return False, gate_feedback(results)
        # Gates green is necessary, not sufficient: they say nothing about
        # whether THIS step happened. See Step.defines.
        if not defines_symbol(workspace, step.target_file, step.defines):
            if snapshot is not None:
                snapshot.restore()
            return False, (
                f"the code is valid but `{step.defines}` is still not defined in "
                f"{step.target_file}. This step must add it. Do not change "
                f"anything else."
            )
        return True, ""

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


def _grounded(symbol: str, goal: str) -> bool:
    """Is this criterion actually traceable to the goal?

    The planner invents criteria: a run for "add by_tag and make add accept
    tags" also demanded `text_item`, a name appearing nowhere in the goal.
    Enforcing that would fail a correct implementation. A requirement the goal
    never states cannot be a requirement, so ungrounded criteria are dropped
    rather than enforced.

    Matching is on the last dotted component and case-insensitive, so
    `Store.add` is grounded by the goal phrase "Store.add" or plain "add".
    """
    if not symbol:
        return False
    bare = symbol.rpartition(".")[2]
    haystack = goal.lower().replace("_", "").replace(" ", "")
    return bare.lower().replace("_", "") in haystack


def verify_plan(workspace: Path | str, plan: Plan, goal: str = "") -> list[str]:
    """Unmet acceptance criteria, as human-readable strings.

    Per-step verification (Step.defines) cannot see a plan that never covered
    part of the goal. This closes that hole: the criteria come from the goal, so
    a missing step surfaces as a missing symbol rather than as a green run.

    Criteria the goal does not mention are ignored — see _grounded().
    """
    unmet = []
    for a in plan.acceptance:
        if not a.symbol:
            continue
        if goal and not _grounded(a.symbol, goal):
            continue
        if not defines_symbol(workspace, a.file, a.symbol):
            unmet.append(f"`{a.symbol}` is not defined in {a.file}")
    return unmet


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


MAX_REPLANS = int(os.environ.get("NANOLOOP_MAX_REPLANS", "2"))


@dataclass
class GoalResult:
    plans: list[Plan] = field(default_factory=list)
    steps: list[StepResult] = field(default_factory=list)
    unmet: list[str] = field(default_factory=list)
    rounds: int = 0

    @property
    def ok(self) -> bool:
        return not self.unmet and all(r.ok for r in self.steps)


def run_goal(
    goal: str,
    workspace: Path | str,
    plan_fn,  # (goal, repo_map, gaps) -> Plan
    propose,
    *,
    gates: list[str] | None = None,
    max_replans: int = MAX_REPLANS,
    on_plan=None,
    on_step=None,
    **kw,
) -> GoalResult:
    """Plan -> run -> verify -> REPLAN on the gaps, bounded.

    Detecting an unmet criterion and stopping still leaves the human to finish
    the job. Replanning closes that: the unmet criteria go back to the planner
    as the goal of a second pass, with a FRESHLY BUILT repo map so it can see
    what already exists and not redo it.

    Bounded on purpose. A planner that cannot satisfy a criterion in two extra
    passes is not going to on the third — it is either misreading the goal or
    the criterion is wrong, and both need a human. Looping until success would
    burn tokens forever on an impossible criterion.
    """
    from . import repomap

    workspace = Path(workspace)
    out = GoalResult()
    gaps: list[str] = []

    for round_no in range(max_replans + 1):
        out.rounds = round_no + 1
        plan = plan_fn(goal, repomap.build(workspace), gaps or None)
        out.plans.append(plan)
        if on_plan:
            on_plan(round_no, plan, gaps)

        results = run_plan(plan, goal, workspace, propose, gates=gates, on_step=on_step, **kw)
        out.steps.extend(results)

        # Criteria carry over: a second plan may drop or reword them, and the
        # goal's requirements do not change just because the planner forgot one.
        seen = {(a.symbol, a.file) for p in out.plans for a in p.acceptance}
        merged = Plan(steps=[], acceptance=[Acceptance(symbol=s, file=f) for s, f in sorted(seen)])
        out.unmet = verify_plan(workspace, merged, goal)
        if not out.unmet:
            return out
        gaps = out.unmet

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
