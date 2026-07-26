"""Skills: reusable instruction packs loaded from ./Skills/.

A skill is a Markdown file with frontmatter:

    ---
    name: <slug>
    description: <when to use this skill>
    ---

    <step-by-step instructions the crew should follow>

Layout (either works):
    Skills/<name>.md
    Skills/<name>/SKILL.md      (directory form; can ship support files alongside)

The orchestrator sees the name+description of every skill up front, then calls
`use_skill(<name>)` to pull the full instructions into context on demand.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from . import frontmatter

SKILLS_DIR = Path(os.environ.get("NANOLOOP_SKILLS_DIR", "Skills"))


@dataclass
class Skill:
    name: str
    description: str
    body: str
    path: Path

    @property
    def executor(self) -> Path:
        """Optional deterministic executor: Skills/<name>/execute.py

        Must define `run(params: dict, workspace: Path) -> str`. This is the
        Google pattern (PLAN.md D5): the skill DECLARES a capability and a
        deterministic executor performs it. Prose the model imitates is the
        thing we are replacing, because a 12B imitates prose unreliably.
        """
        return self.path.parent / "execute.py"

    @property
    def has_executor(self) -> bool:
        return self.path.name == "SKILL.md" and self.executor.exists()


def _candidates() -> list[Path]:
    if not SKILLS_DIR.exists():
        return []
    found = list(SKILLS_DIR.glob("*.md"))
    found += list(SKILLS_DIR.glob("*/SKILL.md"))
    return found


def _load(path: Path) -> Skill:
    meta, body = frontmatter.parse(path.read_text(encoding="utf-8"))
    # Name: frontmatter wins; else dir name (SKILL.md) or file stem.
    name = meta.get("name")
    if not name:
        name = path.parent.name if path.name == "SKILL.md" else path.stem
    return Skill(name=name, description=meta.get("description", ""), body=body, path=path)


def discover() -> list[Skill]:
    skills = [_load(p) for p in _candidates()]
    skills.sort(key=lambda s: s.name)
    return skills


def get(name: str) -> Skill | None:
    name = name.strip().lower()
    for s in discover():
        if s.name.lower() == name:
            return s
    return None


def catalog_text() -> str:
    """One line per skill (name: description) for the build-phase prompt.

    ~23 tokens per skill, measured across Google's 11 shipped skills (257 total).
    Full bodies load only on trigger — preloading all of them would cost ~3,079.
    Adding a capability therefore costs 23 tokens, not the 300-800 a tool schema
    would (D5). Keep descriptions one line; that is the whole budget.
    """
    skills = discover()
    if not skills:
        return ""
    return "\n".join(f"- {s.name}: {s.description}" for s in skills)


def execute(skill: Skill, params: dict, workspace: Path) -> str:
    """Load and run a skill's deterministic executor.

    Imported by path rather than as a package so skills stay self-contained
    directories that can be dropped in without touching the harness.
    """
    import importlib.util

    spec = importlib.util.spec_from_file_location(
        f"nanoloop_skill_{skill.name}".replace("-", "_"), skill.executor
    )
    if spec is None or spec.loader is None:
        raise RuntimeError(f"cannot load executor for skill '{skill.name}'")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    run = getattr(module, "run", None)
    if run is None:
        raise RuntimeError(f"skill '{skill.name}' executor defines no run()")
    return str(run(params, Path(workspace)))
