"""generator/equipping.py — the `arm x equipping` dimension (ROADMAP M2).

Equipping is a RUN dimension, not a spec property: same scenario, same
instruction, same image, different skills/MCP. A spec only OPTS IN
(`Spec.equipping.levels`, the shape `arms.hcl_modules` uses for an optional arm);
the material lives once under `equipping/` for the whole corpus, with the three
levels and what `tuned-stale` makes stale documented in `equipping/README.md`.

A level file names skill directories to copy and MCP servers to declare; both reach
the trial through Harbor's own `task.toml [environment]` channels (`mcp_servers`,
`skills_dir`), which `gates/equipping.py` hashes as scheme 2 (Amendment 47), and
the copied `skills/` tree and emitted `mcp.json` are in that hash's file glob too.

`skills_dir` is a path INSIDE the container: a TUNED task's Dockerfile carries one
generator-appended COPY (`gen.py::patch_dockerfile_equipping_copy`) landing
`equipping/` at CONTAINER_EQUIPPING_ROOT, deliberately NOT under /app/project
because a skill is equipping and must not reach the graded artifact. A bare task
gets no COPY and no directory. That the material then ARRIVES is checked by
`gates/tuned_equipping.py`, not assumed — see docs/gates.md.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Literal

import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent
EQUIPPING_DIR = REPO_ROOT / "equipping"
LEVELS_DIR = EQUIPPING_DIR / "levels"

EquippingLevel = Literal["bare", "tuned", "tuned-stale"]
BARE: EquippingLevel = "bare"
TUNED_LEVELS: tuple[EquippingLevel, ...] = ("tuned", "tuned-stale")

# Where the arm Dockerfiles land `environment/equipping/`, and therefore what
# `[environment] skills_dir` points at. Outside /app/project on purpose.
CONTAINER_EQUIPPING_ROOT = "/opt/equipping"
CONTAINER_SKILLS_DIR = f"{CONTAINER_EQUIPPING_ROOT}/skills"

# The subdirectory of a task's `environment/` this material is written to. Created
# only at a tuned level, alongside the Dockerfile COPY that lands it.
TASK_EQUIPPING_SUBDIR = "equipping"
MCP_CONFIG_NAME = "mcp.json"


class UnknownEquippingLevel(ValueError):
    """A level with no `equipping/levels/<arm>.<level>.yaml` behind it."""


def level_path(arm_dirname: str, level: EquippingLevel) -> Path:
    return LEVELS_DIR / f"{arm_dirname}.{level}.yaml"


def available_levels(arm_dirname: str) -> list[EquippingLevel]:
    return [lvl for lvl in TUNED_LEVELS if level_path(arm_dirname, lvl).is_file()]


def load_level(arm_dirname: str, level: EquippingLevel) -> dict:
    path = level_path(arm_dirname, level)
    if not path.is_file():
        raise UnknownEquippingLevel(
            f"equipping level {level!r} is not defined for arm directory "
            f"{arm_dirname!r}: {path.relative_to(REPO_ROOT)} does not exist. "
            f"Defined levels for this arm: {available_levels(arm_dirname) or 'none'}"
        )
    data = yaml.safe_load(path.read_text()) or {}
    return {"skills": data.get("skills") or [], "mcp_servers": data.get("mcp_servers") or []}


def materialize(arm_dirname: str, level: EquippingLevel, dest_environment: Path) -> dict:
    """Write one level's material into a generated task's `environment/`.

    Returns the level's declarations, for build_task_toml to emit. `bare` writes
    nothing and returns empty lists, so a bare task keeps the arm template's
    `equipping/.keep` and its task.toml stays byte-identical.
    """
    if level == BARE:
        return {"skills": [], "mcp_servers": []}
    declared = load_level(arm_dirname, level)
    root = dest_environment / TASK_EQUIPPING_SUBDIR
    root.mkdir(parents=True, exist_ok=True)
    for skill in declared["skills"]:
        src = EQUIPPING_DIR / skill["source"]
        if not src.is_dir():
            raise UnknownEquippingLevel(
                f"{level_path(arm_dirname, level).relative_to(REPO_ROOT)} names "
                f"skill source {skill['source']!r}, which is not a directory"
            )
        dest = root / "skills" / skill["as"]
        dest.mkdir(parents=True, exist_ok=True)
        for f in sorted(src.rglob("*")):
            if not f.is_file():
                continue
            out = dest / f.relative_to(src)
            out.parent.mkdir(parents=True, exist_ok=True)
            out.write_bytes(f.read_bytes())
    if declared["mcp_servers"]:
        # `mcp.json` so the hash's file glob sees the MCP declarations too, in
        # Harbor's own shape (harbor/cli/utils.py) and from the same dict task.toml
        # is rendered from, so the two channels cannot drift apart.
        (root / MCP_CONFIG_NAME).write_text(
            json.dumps({"mcp_servers": declared["mcp_servers"]}, indent=2) + "\n"
        )
    return declared


def task_toml_environment_lines(declared: dict) -> list[str]:
    """The `[environment]` additions for one level: `skills_dir` plus one
    `[[environment.mcp_servers]]` table per server. Empty for `bare`."""
    lines: list[str] = []
    if declared["skills"]:
        lines.append(f'skills_dir = "{CONTAINER_SKILLS_DIR}"')
    for server in declared["mcp_servers"]:
        lines.append("")
        lines.append("[[environment.mcp_servers]]")
        lines.append(f'name = "{server["name"]}"')
        lines.append(f'transport = "{server["transport"]}"')
        if server.get("url"):
            lines.append(f'url = "{server["url"]}"')
        if server.get("command"):
            lines.append(f'command = "{server["command"]}"')
            lines.append(f"args = {json.dumps(server.get('args') or [])}")
    return lines
