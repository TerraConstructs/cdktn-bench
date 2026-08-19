"""generator/tests/test_dockerfile_workspace_coverage.py — the guard for
docs/design/poisoned-workspace-design.md §9-B1 ("the `seeded_files` container
gap").

THE BUG THIS TEST WOULD HAVE CAUGHT: a generated task's Dockerfile used to be a
verbatim copy of its arm's Dockerfile, which COPYs only the NAMED arm-level
workspace paths it knows about (`COPY workspace/provider.tf ./provider.tf`, ...).
The generator, meanwhile, writes extra files into the task's workspace dir —
spec `seeded_files` (specs/SCHEMA.md §2.5), e.g. apigw-openapi's
`openapi/widgets-api.json` and `lambda/placeholder.zip`. Those files therefore
existed on the HOST (in the build context, and in the sandbox tree
gates/oracle_falsifiability.py copies directly — which is exactly what masked
the bug) but were never inside the agent's container, while the generated
instruction.md told the agent to read them.

The invariant, stated once and enforced over every environment/ in the repo:

    every git-tracked file under an environment's workspace dir must be
    carried into the image by that environment's own Dockerfile.

"git-tracked" is the build-artifact filter: `.gitignore` already excludes the
tsc/synth emit (`**/environment/workspace/lib/*.js`, `cdktf.out/`,
`node_modules/`, ...), which is precisely the set that must NOT be baked into an
image. Using git's own answer keeps this test from re-deriving (and drifting
from) that list.

Covers the ARM environments too, not just generated tasks: an arm-level
workspace file added without its COPY is the same bug one level up, and the
generator would faithfully propagate it into every task.
"""

from __future__ import annotations

import shutil
import subprocess
from pathlib import Path

import pytest
from gen import (
    ARM_WORKSPACE_SUBDIR,
    ARMS_DIR,
    REPO_ROOT,
    dockerfile_context_sources,
    dockerfile_copies_path,
    dockerfile_workspace_workdir,
    patch_dockerfile_workspace_copies,
)

# Every workspace-subdir name any arm uses (gen.ARM_WORKSPACE_SUBDIR: "workspace"
# for awscdk/hcl_raw, "app" for terraconstructs). Discovered from an
# environment/ dir rather than from the arm name so this also covers
# tasks/anchor/smoke, which is hand-maintained (ci/check-smoke-drift.sh) and has
# no arm mapping of its own.
_WORKSPACE_SUBDIRS = sorted(set(ARM_WORKSPACE_SUBDIR.values()))

# Files that are legitimately present in a workspace dir on the HOST but must
# NOT be COPY'd into the image. Keyed by "<env-dir-relative-to-repo-root>:
# <workspace-relative path>"; every entry needs a comment saying why the agent
# must not see it (a reference solution, a grading fixture, ...). EMPTY on
# purpose: as of this test's introduction nothing in any workspace is host-only
# — a workspace dir *is* the agent's /app/project, so "present but not COPY'd"
# is the bug, not a category. Anything added here without a justification is a
# regression in disguise.
HOST_ONLY_ALLOWLIST: dict[str, str] = {}


def _git_tracked(paths: list[str]) -> list[str]:
    try:
        out = subprocess.run(
            ["git", "ls-files", "-z", "--", *paths],
            cwd=REPO_ROOT,
            capture_output=True,
            text=True,
            check=True,
        )
    except (OSError, subprocess.CalledProcessError) as exc:  # pragma: no cover
        pytest.skip(f"git unavailable / not a work tree: {exc}")
    return [p for p in out.stdout.split("\0") if p]


def _environment_dirs() -> list[Path]:
    """Every environment/ in the repo that has a workspace dir: the three arms
    plus every generated task under tasks/ plus the hand-maintained smoke
    task."""
    roots = [ARMS_DIR, REPO_ROOT / "tasks"]
    found: list[Path] = []
    for root in roots:
        for dockerfile in sorted(root.rglob("environment/Dockerfile")):
            env_dir = dockerfile.parent
            if any((env_dir / sub).is_dir() for sub in _WORKSPACE_SUBDIRS):
                found.append(env_dir)
    assert found, "no environment/ dirs with a workspace found — bad discovery glob"
    return found


def _cases() -> list[tuple[str, Path, str]]:
    cases: list[tuple[str, Path, str]] = []
    for env_dir in _environment_dirs():
        for sub in _WORKSPACE_SUBDIRS:
            if (env_dir / sub).is_dir():
                rel = env_dir.relative_to(REPO_ROOT).as_posix()
                cases.append((f"{rel}[{sub}]", env_dir, sub))
    return cases


_CASES = _cases()


@pytest.mark.parametrize(
    ("env_dir", "workspace_subdir"),
    [(c[1], c[2]) for c in _CASES],
    ids=[c[0] for c in _CASES],
)
def test_every_tracked_workspace_file_is_copied_into_the_image(
    env_dir: Path, workspace_subdir: str
) -> None:
    """§9-B1: a file the agent is told about must actually reach the container."""
    workspace = env_dir / workspace_subdir
    env_rel = env_dir.relative_to(REPO_ROOT).as_posix()
    sources = dockerfile_context_sources((env_dir / "Dockerfile").read_text())

    tracked = _git_tracked([workspace.relative_to(REPO_ROOT).as_posix()])
    assert tracked, f"{workspace} has no git-tracked files — is it generated but uncommitted?"

    missing = []
    for repo_rel in tracked:
        ws_rel = Path(repo_rel).relative_to(workspace.relative_to(REPO_ROOT)).as_posix()
        if f"{env_rel}:{ws_rel}" in HOST_ONLY_ALLOWLIST:
            continue
        if not dockerfile_copies_path(sources, f"{workspace_subdir}/{ws_rel}"):
            missing.append(ws_rel)

    assert not missing, (
        f"{env_rel}/Dockerfile never COPYs {len(missing)} file(s) that exist in "
        f"{env_rel}/{workspace_subdir}/ — they are visible on the host (and to the "
        f"host-side gates) but NOT to the agent in the container: {missing}. "
        f"Fix the generator (generator/gen.py::patch_dockerfile_workspace_copies) "
        f"or the arm Dockerfile — see docs/design/poisoned-workspace-design.md §9-B1."
    )


def test_guard_fails_when_a_copy_is_dropped(tmp_path: Path) -> None:
    """Negative control: the check above must actually FAIL on the pre-fix
    shape. Copies a real generated environment, deletes the generator-appended
    COPY block from its Dockerfile (reproducing the bug exactly), and asserts
    the coverage check reports the seeded files as missing."""
    src = REPO_ROOT / "tasks" / "anchor" / "apigw-openapi-hcl-raw" / "environment"
    if not src.is_dir():  # pragma: no cover
        pytest.skip("apigw-openapi-hcl-raw not generated")
    env_dir = tmp_path / "environment"
    shutil.copytree(src, env_dir)

    arm_dockerfile = (ARMS_DIR / "hcl-raw" / "environment" / "Dockerfile").read_text()
    (env_dir / "Dockerfile").write_text(arm_dockerfile)  # the pre-fix verbatim copy

    sources = dockerfile_context_sources(arm_dockerfile)
    uncovered = [
        p.relative_to(env_dir / "workspace").as_posix()
        for p in sorted((env_dir / "workspace").rglob("*"))
        if p.is_file()
        and not dockerfile_copies_path(
            sources, f"workspace/{p.relative_to(env_dir / 'workspace').as_posix()}"
        )
    ]
    assert uncovered == ["lambda/placeholder.zip", "openapi/widgets-api.json"]


def test_copy_parser_handles_the_shapes_the_arm_dockerfiles_use() -> None:
    text = (
        "FROM scratch\n"
        "# a comment\n"
        "COPY workspace/package.json workspace/package-lock.json ./\n"
        "COPY --chown=1000:1000 workspace/bin ./bin\n"
        'COPY ["workspace/cdk.json", "./cdk.json"]\n'
        "COPY workspace/a \\\n"
        "     workspace/b ./\n"
        "COPY --from=builder /opt/thing /opt/thing\n"
    )
    sources = dockerfile_context_sources(text)
    assert sources == [
        "workspace/package.json",
        "workspace/package-lock.json",
        "workspace/bin",
        "workspace/cdk.json",
        "workspace/a",
        "workspace/b",
    ]
    # directory COPY covers everything beneath it
    assert dockerfile_copies_path(sources, "workspace/bin/app.ts")
    assert dockerfile_copies_path(sources, "workspace/package.json")
    # --from=<stage> is not a build-context path and must not count as coverage
    assert not dockerfile_copies_path(sources, "opt/thing")
    assert not dockerfile_copies_path(sources, "workspace/openapi/widgets-api.json")


def test_workspace_workdir_is_derived_not_guessed() -> None:
    """The appended block must target the directory the arm's OWN workspace
    COPYs land in — /app/project for all three v1 arms (DECISIONS.md
    "Agent-container baseline contract")."""
    for arm, sub in ARM_WORKSPACE_SUBDIR.items():
        dockerfile = ARMS_DIR / {"hcl_raw": "hcl-raw"}.get(arm, arm) / "environment" / "Dockerfile"
        assert dockerfile_workspace_workdir(dockerfile.read_text(), sub) == "/app/project"


def test_patch_is_a_noop_without_seeded_files() -> None:
    """A task with nothing extra in its workspace keeps a Dockerfile
    byte-identical to its arm's."""
    text = (ARMS_DIR / "hcl-raw" / "environment" / "Dockerfile").read_text()
    assert patch_dockerfile_workspace_copies(text, "workspace", []) == text


def test_patch_emits_one_named_copy_per_file_preserving_relative_paths() -> None:
    text = (ARMS_DIR / "hcl-raw" / "environment" / "Dockerfile").read_text()
    patched = patch_dockerfile_workspace_copies(
        text, "workspace", ["lambda/placeholder.zip", "openapi/widgets-api.json"]
    )
    assert "COPY workspace/lambda/placeholder.zip ./lambda/placeholder.zip" in patched
    assert "COPY workspace/openapi/widgets-api.json ./openapi/widgets-api.json" in patched
    # never a blanket copy (arms/*/README.md "workspace split" — the named-COPY
    # discipline is deliberate). Checked against the parsed COPY *sources*, not
    # the raw text, so the block's own explanatory comment doesn't false-positive.
    sources = dockerfile_context_sources(patched)
    assert not any(s.rstrip("/") == "workspace" for s in sources)
    # ...and the patched Dockerfile now covers them
    assert dockerfile_copies_path(sources, "workspace/openapi/widgets-api.json")
    assert dockerfile_copies_path(sources, "workspace/lambda/placeholder.zip")
    # still ends on its CMD
    assert patched.rstrip().endswith('CMD ["/bin/bash"]')
