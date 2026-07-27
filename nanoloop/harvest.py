"""Read work off the repo instead of waiting to be told what to do.

The crew needed a human for two things: the goal, and the definition of done.
The second cannot be delegated to the model — measured, it invents criteria
(`text_item` for a goal that never mentioned it) and forgets others.

But a repo in a red state is already full of specified work. A failing test is a
COMPLETE task specification:

    goal        "make this test pass"
    acceptance  the test itself — executable, unambiguous, written by a human
    location    the traceback names the file
    verdict     pytest, which has no opinion

That removes both weak links at once: nobody writes the goal, and nobody writes
the criterion, because the repo already contains them.

Sources, ordered by how good their oracle is:

    pytest   a failing test        the gold standard: the criterion IS the test
    mypy     a type error          precise, located, verifiable
    ruff     a lint ruff cannot fix   narrow but unambiguous

Deliberately NOT harvested: TODO/FIXME comments. They carry no oracle, so a
"done" would be the model's opinion — exactly what this module exists to avoid.
"""

from __future__ import annotations

import ast
import json
import re
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .crew import Acceptance, _gate_env

PYTEST_FAILED = re.compile(r"^(?:FAILED|ERROR)\s+(\S+?)(?:\s+-\s+(.*))?$", re.MULTILINE)
MYPY_ERROR = re.compile(
    r"^(?P<file>[^\s:]+):(?P<line>\d+):(?:\d+:)?\s*error:\s*(?P<msg>.+?)(?:\s+\[(?P<code>[\w-]+)\])?$",
    re.MULTILINE,
)
RUFF_ISSUE = re.compile(
    r"^(?P<file>[^\s:]+):(?P<line>\d+):(?P<col>\d+):\s*(?P<code>\w+)\s+(?P<msg>.+)$", re.MULTILINE
)


@dataclass
class Task:
    """One unit of work the repo asked for, with its oracle attached."""

    source: str  # pytest | mypy | ruff
    goal: str
    target_file: str
    evidence: str  # the raw failure, verbatim — this is what makes it real
    acceptance: list[Acceptance] = field(default_factory=list)

    def to_dict(self) -> dict:
        d = asdict(self)
        d["acceptance"] = [a.model_dump() for a in self.acceptance]
        return d


def _run(workspace: Path, args: list[str], timeout: int = 300) -> tuple[int, str]:
    try:
        proc = subprocess.run(
            args,
            cwd=str(workspace),
            capture_output=True,
            text=True,
            timeout=timeout,
            env=_gate_env(),
        )
        return proc.returncode, (proc.stdout or "") + (proc.stderr or "")
    except (subprocess.TimeoutExpired, OSError) as e:
        return -1, f"[could not run {args[0]}: {e}]"


def _pytest_check(node_id: str) -> str:
    """Acceptance for a failing test: run exactly that test, demand exit 0.

    Runs through run_check like any other criterion, so nothing special is
    needed downstream — and unlike a symbol-existence check, this one cannot be
    satisfied by a stub.
    """
    return (
        "import subprocess, sys\n"
        f"r = subprocess.run([sys.executable, '-m', 'pytest', '-q', '--no-header', {node_id!r}],\n"
        "                   capture_output=True, text=True)\n"
        "assert r.returncode == 0, r.stdout[-2000:]\n"
    )


def _file_of(node_id: str) -> str:
    return node_id.split("::", 1)[0]


def module_under_test(workspace: Path, test_path: str) -> str:
    """Guess which module the failing test is about, from its own imports.

    The failure is OBSERVED in the test file, but the fix almost never belongs
    there — pointing the planner at the test invites it to edit the test until
    it passes, which is the one outcome that makes the whole exercise
    worthless. The test's first local import is a good, deterministic hint.

    Falls back to the test file when nothing local is imported; the planner is
    still free to choose, this only sets the starting point.
    """
    src = workspace / test_path
    if not src.exists():
        return test_path
    try:
        tree = ast.parse(src.read_text(encoding="utf-8", errors="replace"))
    except (OSError, SyntaxError):
        return test_path
    for node in ast.walk(tree):
        names = []
        if isinstance(node, ast.ImportFrom) and node.module:
            names.append(node.module)
        elif isinstance(node, ast.Import):
            names.extend(a.name for a in node.names)
        for name in names:
            rel = Path(name.replace(".", "/"))
            for candidate in (rel.with_suffix(".py"), rel / "__init__.py"):
                if (workspace / candidate).exists():
                    return str(candidate)
    return test_path


MISSING_MODULE = re.compile(r"No module named ['\"]([\w.]+)['\"]")


def environment_problems(output: str) -> set[str]:
    """Modules pytest could not import.

    A test that fails because `matplotlib` is not installed is NOT a coding
    task: no edit the model can make will fix it, and handing it over burns the
    budget on the `ruff: command not found` failure all over again — this time
    at repo scale. Measured on PennyLane: the first "failures" a harvest saw
    were `flaky` and `matplotlib` missing, nothing to do with the code.
    """
    return set(MISSING_MODULE.findall(output))


def from_pytest(workspace: Path, tests: str = "") -> list[Task]:
    """One task per failing test. The richest source there is.

    `tests` scopes the run. Without it this executes the entire suite, which on
    a real repo is not a harvest cycle: PennyLane collects 52,740 tests. Scoping
    is not a nicety, it is what makes this usable outside a fixture.
    """
    args = [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rf"]
    if tests:
        args.append(tests)
    code, out = _run(workspace, args, timeout=1800)
    if code == 0:
        return []

    missing = environment_problems(out)
    tasks = []
    for node_id, message in PYTEST_FAILED.findall(out):
        if any(m in (message or "") for m in missing):
            continue  # environment, not code
        path = _file_of(node_id)
        test_name = node_id.rpartition("::")[2]
        tasks.append(
            Task(
                source="pytest",
                goal=f"Make the failing test {node_id} pass. Fix the code under "
                f"test, not the test itself.",
                target_file=module_under_test(workspace, path),
                evidence=f"{node_id} — {message or 'failed'}",
                acceptance=[Acceptance(symbol=test_name, file=path, check=_pytest_check(node_id))],
            )
        )
    return tasks


def from_mypy(workspace: Path) -> list[Task]:
    """One task per file with type errors — per file, not per error, because
    fixing one annotation usually settles several."""
    code, out = _run(workspace, ["mypy", ".", "--no-error-summary", "--no-color-output"])
    if code == 0:
        return []
    by_file: dict[str, list[str]] = {}
    for m in MYPY_ERROR.finditer(out):
        by_file.setdefault(m.group("file"), []).append(f"line {m.group('line')}: {m.group('msg')}")
    tasks = []
    for path, errors in by_file.items():
        listed = "\n".join(f"  - {e}" for e in errors[:10])
        tasks.append(
            Task(
                source="mypy",
                goal=f"Fix the type errors in {path}:\n{listed}",
                target_file=path,
                evidence="\n".join(errors),
                acceptance=[
                    Acceptance(
                        symbol="",  # a type error is about a file, not one symbol
                        file=path,
                        check=(
                            "import subprocess\n"
                            f"r = subprocess.run(['mypy', {path!r}, '--no-error-summary'],\n"
                            "                   capture_output=True, text=True)\n"
                            "assert r.returncode == 0, r.stdout[-2000:]\n"
                        ),
                    )
                ],
            )
        )
    return tasks


def from_ruff(workspace: Path) -> list[Task]:
    """Only what ruff CANNOT fix itself — the rest is already handled by
    crew.autofix and would be busywork for the model."""
    _run(workspace, ["ruff", "check", ".", "--fix", "--quiet"])
    code, out = _run(workspace, ["ruff", "check", ".", "--output-format=concise"])
    if code == 0:
        return []
    by_file: dict[str, list[str]] = {}
    for m in RUFF_ISSUE.finditer(out):
        by_file.setdefault(m.group("file"), []).append(
            f"line {m.group('line')}: {m.group('code')} {m.group('msg')}"
        )
    return [
        Task(
            source="ruff",
            goal=f"Fix the lint problems ruff cannot fix automatically in {path}:\n"
            + "\n".join(f"  - {e}" for e in errors[:10]),
            target_file=path,
            evidence="\n".join(errors),
            acceptance=[
                Acceptance(
                    symbol="",
                    file=path,
                    check=(
                        "import subprocess\n"
                        f"r = subprocess.run(['ruff', 'check', {path!r}],\n"
                        "                   capture_output=True, text=True)\n"
                        "assert r.returncode == 0, r.stdout[-2000:]\n"
                    ),
                )
            ],
        )
        for path, errors in by_file.items()
    ]


def failing_tests(workspace: Path | str, tests: str = "") -> set[str]:
    """The set of test node IDs failing right now.

    Harvest works on repos that are ALREADY red, so "all gates green" cannot be
    the bar for a task — nothing would ever pass. But dropping the gates
    entirely, which is what the first version did, removes the only check that
    sees the whole suite: task 2 silently broke what task 1 had just fixed and
    the run still reported 2/2 solved, because each task only ever ran its own
    test.

    The right bar for a red repo is a BASELINE: you may leave existing failures
    alone, you may not create new ones.
    """
    args = [sys.executable, "-m", "pytest", "-q", "--tb=no", "-rf"]
    if tests:
        args.append(tests)
    code, out = _run(Path(workspace), args, timeout=1800)
    if code == 0:
        return set()
    return {node for node, _ in PYTEST_FAILED.findall(out)}


def regressions(workspace: Path | str, baseline: set[str], tests: str = "") -> set[str]:
    """Tests failing now that were not failing before."""
    return failing_tests(workspace, tests) - baseline


SOURCES = {"pytest": from_pytest, "mypy": from_mypy, "ruff": from_ruff}


def harvest(workspace: Path | str, sources: list[str] | None = None, tests: str = "") -> list[Task]:
    """Collect work from the repo's own failing signals.

    Order matters: pytest first, because a failing test is the best-specified
    task available and fixing it often clears lint and type noise on the way.
    """
    workspace = Path(workspace)
    picked = sources or ["pytest", "mypy", "ruff"]
    tasks: list[Task] = []
    for name in picked:
        fn = SOURCES.get(name)
        if fn is None:
            continue
        try:
            tasks.extend(fn(workspace, tests) if name == "pytest" else fn(workspace))
        except Exception:  # noqa: BLE001 - one broken source must not kill harvest
            continue
    return tasks


def dump(tasks: list[Task]) -> str:
    return json.dumps([t.to_dict() for t in tasks], indent=2)
