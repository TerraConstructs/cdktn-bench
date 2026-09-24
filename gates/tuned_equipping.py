"""gates/tuned_equipping.py — a tuned row is only tuned if the material arrived.

The equipping hash proves a DECLARATION moved. It cannot prove the material
reached the container, and Harbor makes both ways of not reaching it silent:
skills are installed with `cp -r <skills_dir>/* ... || true`
(`harbor/agents/installed/claude_code.py::_build_register_skills_command`), so an
empty tree is a no-op; MCP servers are written into `$CLAUDE_CONFIG_DIR/.claude.json`
and started by claude-code, which logs a server it cannot start and continues, so
a `stdio` command missing from the image is an absent tool, not a failed trial.
The result would be ROADMAP M2's signature failure: a row published as tuned by a
trial that was bare.

So the declaration is checked against the artifact, in halves split on what they
need — `static_defects` and `oracle_identity_defects` read only the task's own
bytes (`make equipping-check`, wired into `make check`); `image_defects` runs one
`docker run` per declared `stdio` command (`make equipping-preflight`, needs the
arm images). Until both are green for a level, a trial at that level publishes a
`harness` value that overstates what the agent had.
"""

from __future__ import annotations

import hashlib
import json
import subprocess
import sys
from pathlib import Path

from gates.equipping import (
    EquippingLabelMismatch,
    _discover_equipping_files,
    equipping_level,
    harbor_declared_equipping,
)

REPO_ROOT = Path(__file__).resolve().parent.parent
TASKS_DIR = REPO_ROOT / "tasks"

# Where generator/equipping.py lands the material in the image. Restated here
# rather than imported: `generator/` is host-only tooling and `gates/` must not
# depend on it, so the two are held equal by test instead.
CONTAINER_EQUIPPING_ROOT = "/opt/equipping"


def static_defects(task_dir: str | Path) -> list[str]:
    """Everything wrong with one task's equipping that its own bytes can prove."""
    task_dir = Path(task_dir)
    try:
        level = equipping_level(task_dir)
    except EquippingLabelMismatch as exc:
        return [str(exc)]
    declared = harbor_declared_equipping(task_dir)
    files = {p.as_posix() for p in _discover_equipping_files(task_dir)}
    defects: list[str] = []

    if level == "bare":
        # Not redundant with equipping_level's own check: that one reads Harbor's
        # declarations, this one reads the file glob, and a skills tree shipped
        # without a `skills_dir` line equips nothing while still moving the hash.
        if files:
            defects.append(
                f"bare task ships equipping files: {sorted(files)} — a bare row's "
                f"container must hold no skill or MCP config"
            )
        return defects

    skills_dir = declared["skills_dir"]
    if not skills_dir:
        defects.append("no [environment] skills_dir declared at a tuned level")
    else:
        if not skills_dir["declared"].startswith(CONTAINER_EQUIPPING_ROOT + "/"):
            defects.append(
                f"skills_dir {skills_dir['declared']!r} is not under "
                f"{CONTAINER_EQUIPPING_ROOT}/, which is the only path the "
                f"generator-appended Dockerfile COPY lands material at"
            )
        if not skills_dir["files"]:
            defects.append(
                f"skills_dir {skills_dir['declared']!r} resolves to no readable "
                f"files in the build context — Harbor's `cp ... || true` would "
                f"install nothing and say nothing"
            )
        dockerfile = task_dir / "environment" / "Dockerfile"
        copy_line = f"COPY equipping/ {CONTAINER_EQUIPPING_ROOT}/"
        if not dockerfile.is_file() or copy_line not in dockerfile.read_text():
            defects.append(
                f"environment/Dockerfile does not carry `{copy_line}`, so the "
                f"material is in the build context and not in the image"
            )

    servers = declared["mcp_servers"] or []
    if not servers:
        defects.append("no [[environment.mcp_servers]] declared at a tuned level")
    for server in servers:
        transport = server.get("transport")
        if transport == "stdio" and not server.get("command"):
            defects.append(f"stdio MCP server {server.get('name')!r} declares no command")
        if transport in ("streamable-http", "http", "sse") and not server.get("url"):
            defects.append(f"{transport} MCP server {server.get('name')!r} declares no url")

    # The two channels are rendered from one dict (generator/equipping.py), so a
    # disagreement means one of them was hand-edited.
    mcp_json = task_dir / "environment" / "equipping" / "mcp.json"
    if servers and not mcp_json.is_file():
        defects.append("environment/equipping/mcp.json is missing while task.toml declares servers")
    elif mcp_json.is_file():
        try:
            from_file = json.loads(mcp_json.read_text()).get("mcp_servers")
        except (json.JSONDecodeError, OSError) as exc:
            from_file = f"unreadable: {exc}"
        if from_file != servers:
            defects.append(
                f"environment/equipping/mcp.json and task.toml [environment] "
                f"mcp_servers disagree: {from_file!r} vs {servers!r}"
            )
    return defects


# The two paths one equipping level owns; everything else is the scenario, and
# the scenario is graded identically at every level. Held equal to
# `generator/gen.py::_LEVEL_OWNED_PATHS` by test.
LEVEL_OWNED_PATHS = ("task.toml", "environment")


def bare_sibling(task_dir: str | Path) -> Path:
    """The `bare` task this tuned task is a level of."""
    task_dir = Path(task_dir)
    name = task_dir.name.removesuffix("-tuned-stale").removesuffix("-tuned")
    return task_dir.parent / name


def oracle_identity_defects(task_dir: str | Path) -> list[str]:
    """Where a tuned task's grading bytes differ from its bare sibling's.

    Equipping changes the prompt surface, never the oracle. `instruction.md`,
    `tests/` and `solution/` (the reference solution AND the negative fixtures
    `make falsifiability` / `make grading-proof` read) must therefore be
    byte-identical across levels -- otherwise H1's tuned-vs-bare difference could
    be a difference in what was graded.
    """
    task_dir = Path(task_dir)
    bare = bare_sibling(task_dir)
    if not bare.is_dir():
        return [f"no bare sibling at {bare} -- a tuned level of nothing"]

    def manifest(root: Path) -> dict[str, str]:
        return {
            f.relative_to(root).as_posix(): hashlib.sha256(f.read_bytes()).hexdigest()
            for f in root.rglob("*")
            if f.is_file() and f.relative_to(root).parts[0] not in LEVEL_OWNED_PATHS
        }

    ours, theirs = manifest(task_dir), manifest(bare)
    return [
        f"{rel}: {'absent here' if rel not in ours else 'absent on the bare task' if rel not in theirs else 'differs from the bare task'}"
        for rel in sorted(set(ours) | set(theirs))
        if ours.get(rel) != theirs.get(rel)
    ]


def stdio_commands(task_dir: str | Path) -> list[str]:
    """Every `stdio` MCP executable one task's agent is told it has."""
    servers = harbor_declared_equipping(task_dir)["mcp_servers"] or []
    return [
        str(s["command"])
        for s in servers
        if s.get("transport") == "stdio" and s.get("command")
    ]


def image_defects(task_dir: str | Path, image_ref: str) -> list[str]:
    """Declared `stdio` MCP commands that are not on PATH in `image_ref`.

    `--network none`: resolving an executable is a filesystem question, and a
    check that could reach the network could pass for the wrong reason.
    """
    defects: list[str] = []
    for command in stdio_commands(task_dir):
        proc = subprocess.run(
            [
                "docker", "run", "--rm", "--network", "none",
                "--entrypoint", "sh", image_ref,
                "-c", f"command -v {command}",
            ],
            capture_output=True,
            text=True,
            timeout=120,
            check=False,
        )
        if proc.returncode != 0:
            defects.append(
                f"MCP server command {command!r} is not on PATH in {image_ref} — "
                f"claude-code would register it, fail to start it, and continue, "
                f"so the trial publishes a tuned row it did not have"
            )
    return defects


def tuned_task_dirs() -> list[Path]:
    """Every generated task at a tuned level, by directory name."""
    return sorted(
        p
        for p in TASKS_DIR.glob("*/*")
        if p.is_dir() and (p.name.endswith("-tuned") or p.name.endswith("-tuned-stale"))
    )


def _arm_image(task_dir: Path) -> str:
    """`cdktn-bench/<arm>:dev`, the tag `make build-arms`/`make preflight` use.

    Read off the directory name, longest arm first so `hcl-raw` cannot shadow a
    future arm whose name ends in it."""
    name = task_dir.name
    for suffix in ("-tuned-stale", "-tuned"):
        name = name.removesuffix(suffix)
    for arm in sorted(("awscdk", "hcl-raw", "hcl-modules", "terraconstructs"), key=len, reverse=True):
        if name.endswith("-" + arm):
            return f"cdktn-bench/{arm}:dev"
    raise ValueError(f"cannot tell which arm {task_dir} belongs to")


def main(argv: list[str]) -> int:
    check_image = "--static-only" not in argv
    paths = [Path(a) for a in argv if not a.startswith("--")] or tuned_task_dirs()
    if not paths:
        print("no tuned task directories generated yet — nothing to check")
        return 0
    status = 0
    for task_dir in paths:
        defects = static_defects(task_dir)
        if equipping_level(task_dir) != "bare":
            defects += oracle_identity_defects(task_dir)
        if check_image and not defects:
            defects = image_defects(task_dir, _arm_image(task_dir))
        if defects:
            status = 1
            print(f"FAIL {task_dir}", file=sys.stderr)
            for d in defects:
                print(f"  - {d}", file=sys.stderr)
        else:
            print(f"OK   {task_dir}")
    return status


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))
