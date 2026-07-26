"""Tools for the nanoLoop harness.

Shell + file tools. Safe under OpenShell: every subprocess the agent spawns is
already inside the OpenShell sandbox (the whole process is launched with
`openshell sandbox create -- nanoloop ...`), so the OpenShell policy engine
gates filesystem/network/process actions out-of-process. These tools do NOT
reimplement policy — they trust the sandbox boundary.
"""

from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

from langchain_core.tools import tool

from . import memory, skills
from .session import Session

# Active session for this process. Set by main.run(); tools read/write it so the
# task log + human decisions persist to disk as the crew works.
_SESSION: Session | None = None


def set_session(session: Session | None) -> None:
    global _SESSION
    _SESSION = session


def _hitl_enabled() -> bool:
    """Human gate is OFF by default; opt in with the `interactive` CLI prefix.

    `nanoloop interactive ...` sets HARNESS_HITL=1. Gates still auto-approve (and
    log 'auto') when there's no tty, so an enabled gate never hangs a
    non-interactive run.
    """
    flag = os.environ.get("HARNESS_HITL", "0").lower() in ("1", "true", "yes")
    return flag and sys.stdin.isatty()


# Workspace root — all file/shell actions confined here. Defaults to ./workspace
# under the current dir. Absolute paths from the model are remapped inside it.
WORKDIR = Path(os.environ.get("HARNESS_WORKDIR", "./workspace")).resolve()


def _resolve(path: str) -> Path:
    """Map any model-supplied path to a safe location inside WORKDIR."""
    WORKDIR.mkdir(parents=True, exist_ok=True)
    p = Path(path)
    # Strip leading slash / drive so absolute paths land inside the workspace.
    rel = Path(*[part for part in p.parts if part not in ("/", p.anchor)])
    target = (WORKDIR / rel).resolve()
    # Block path-traversal escapes (`..`, symlinks). is_relative_to avoids the
    # str-prefix bug where "/workspace-evil" passes a "/workspace" check.
    if target != WORKDIR and not target.is_relative_to(WORKDIR):
        raise ValueError(f"path escapes workspace: {path}")
    return target


@tool
def run_shell(command: str, timeout: int = 120) -> str:
    """Run a shell command and return combined stdout/stderr.

    Runs inside the OpenShell sandbox; disallowed actions are blocked by policy.
    """
    WORKDIR.mkdir(parents=True, exist_ok=True)
    try:
        proc = subprocess.run(
            command,
            shell=True,
            capture_output=True,
            text=True,
            timeout=timeout,
            cwd=str(WORKDIR),
        )
    except subprocess.TimeoutExpired:
        return f"[timeout after {timeout}s] {command}"
    except OSError as e:
        return f"[error] {e}"
    out = (proc.stdout or "") + (proc.stderr or "")
    return f"[exit {proc.returncode}]\n{out}".strip()


@tool
def read_file(path: str) -> str:
    """Read a UTF-8 text file from the workspace."""
    try:
        p = _resolve(path)
    except ValueError as e:
        return f"[error] {e}"
    if not p.exists():
        return f"[not found] {path}"
    return p.read_text(encoding="utf-8", errors="replace")


@tool
def write_file(path: str, content: str) -> str:
    """Write content to a file in the workspace, creating parent dirs."""
    try:
        p = _resolve(path)
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_text(content, encoding="utf-8")
    except OSError as e:
        return f"[error] {e}"
    return f"[wrote {len(content)} bytes] {p.relative_to(WORKDIR)}"


@tool
def human_review(gate: str, summary: str, action: str = "") -> str:
    """Pause for human approval at a key point (a 'gate').

    Call this BEFORE any irreversible or high-impact step — pushing, deploying,
    deleting, spending, or finishing a phase that needs sign-off.
      gate:    short label, e.g. "plan-approval", "pre-ship".
      summary: what you're about to do / what you decided.
      action:  the concrete command or change awaiting approval (optional).

    Returns the human's verdict. If running non-interactively, auto-approves and
    records the decision so the audit trail stays complete.
    """
    if not _hitl_enabled():
        if _SESSION:
            _SESSION.record_decision(gate, action, "auto", "non-interactive")
        return "AUTO-APPROVED (non-interactive). Proceed, but stay conservative."

    print(f"\n── HUMAN GATE: {gate} ──")
    print(summary)
    if action:
        print(f"  action: {action}")
    try:
        reply = input("approve? [y]es / [n]o / or type guidance: ").strip()
    except EOFError:
        reply = "y"

    low = reply.lower()
    if low in ("", "y", "yes"):
        verdict, msg = "approved", "APPROVED. Proceed."
    elif low in ("n", "no"):
        verdict, msg = "rejected", "REJECTED. Do not proceed; stop or revise."
    else:
        verdict, msg = "guidance", f"HUMAN GUIDANCE: {reply}"
    if _SESSION:
        _SESSION.record_decision(gate, action, verdict, reply)
    return msg


@tool
def track_task(title: str, status: str = "pending", note: str = "") -> str:
    """Record/update a task in the durable session log (memory across runs).

    status: pending | active | done | blocked. Use this as you start and finish
    each phase so a resumed session knows what's left.
    """
    if not _SESSION:
        return "[no active session]"
    t = _SESSION.upsert_task(title, status, note)
    return f"[task {t.id}] {t.status}: {t.title}"


@tool
def remember(name: str, description: str, content: str, type: str = "reference") -> str:
    """Save a durable fact to the Markdown knowledge-graph memory (./Memory).

    Use for facts worth keeping across sessions: user preferences, project
    constraints, decisions, external references. Link related notes inside
    `content` with [[other-note-name]] to build the graph.
      name:        short kebab-case slug (the note's id).
      description: one-line summary used later for recall.
      type:        user | feedback | project | reference.
    """
    n = memory.write(name, description, content, type)
    links = f" → links: {', '.join(n.links)}" if n.links else ""
    return f"[remembered {n.name} ({n.type})]{links}"


@tool
def recall(query: str, limit: int = 5) -> str:
    """Search memory for relevant facts (knowledge-graph notes).

    Returns matching notes (name, type, description, body) ranked by relevance.
    Call this before planning so prior preferences/constraints inform the work.
    """
    notes = memory.search(query, limit)
    if not notes:
        return "[no matching memory]"
    out = []
    for n in notes:
        out.append(f"## {n.name} ({n.type})\n{n.description}\n{n.body}".strip())
    return "\n\n".join(out)


@tool
def memory_links(name: str) -> str:
    """Show a note's knowledge-graph neighbors (inbound + outbound [[links]])."""
    nb = memory.neighbors(name)
    return (
        f"{memory.slugify(name)}\n"
        f"  outbound: {', '.join(nb['outbound']) or '—'}\n"
        f"  inbound:  {', '.join(nb['inbound']) or '—'}"
    )


# `list_skills` deliberately does not exist (PLAN.md D5 corollary).
# nanoLoop injected the catalog into the system prompt AND exposed list_skills as
# a tool. The model already has the catalog; the tool was a wasted slot and a
# wasted round trip. Google's Agent Skills has no such tool either. Do not re-add
# it — see skills.catalog_text(), which is what goes in the prompt.


@tool
def use_skill(name: str, data: str = "") -> str:
    """Run a skill by name. `data` is JSON with the skill's parameters.

    Skills are capabilities, not tools: the catalog costs ~23 tokens per skill in
    the prompt, and only the selected skill's body or executor is loaded (D5).
    """
    s = skills.get(name)
    if not s:
        avail = ", ".join(sk.name for sk in skills.discover()) or "none"
        return f"[no skill '{name}'] available: {avail}"

    params: dict = {}
    if data:
        try:
            parsed = json.loads(data)
            params = parsed if isinstance(parsed, dict) else {"value": parsed}
        except json.JSONDecodeError:
            params = {"value": data}

    # Deterministic executor if the skill ships one; otherwise the instructions.
    # Copy Google's PATTERN (declarative skill + deterministic executor), not
    # their JS-in-webview executor — we have a shell (PLAN.md §3).
    if s.has_executor:
        try:
            return skills.execute(s, params, WORKDIR)
        except Exception as e:  # noqa: BLE001 - surfaced to the repair loop
            return f"[skill '{name}' failed] {type(e).__name__}: {e}"
    return f"# Skill: {s.name}\n{s.description}\n\n{s.body}"


HARNESS_TOOLS = [
    run_shell,
    read_file,
    write_file,
    human_review,
    track_task,
    remember,
    recall,
    memory_links,
    use_skill,
]
