"""Run every fixture a spec ships and keep the artifact its toolchain produced.

One implementation of "enumerate the reference and broken fixtures, drive each
through the arm's real toolchain under gates/aws_stub.py, and hand back the
graded document", shared by gates/tier0_parity.py and
scripts/spike/collect_artifacts.py. Producing an artifact costs 25-60s of
terraform/cdk; grading one costs milliseconds, so anything that wants to grade
a corpus repeatedly collects once through here and re-reads the tree.

It drives gates/oracle_falsifiability.py::_run_solve, so a fixture runs here
exactly as `make falsifiability` runs it, except that each run's working copy
is KEPT (under `work_dir`): a scenario's real tier-1 input is the merged
document static_tiers.sh writes into the run's logs dir, not the plan.json
under the project dir, and tier 0 grades the plan itself -- both live in that
working copy.

Nothing here writes to the repo, and no call reaches real AWS.
"""

from __future__ import annotations

import shutil
import sys
import time
import types
from collections.abc import Iterator
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))
sys.path.insert(0, str(REPO_ROOT / "gates"))

import oracle_falsifiability as of  # noqa: E402
from gen import ARM_DIRNAME, task_dir  # noqa: E402
from oracle_falsifiability import arm_env  # noqa: E402
from spec_model import Arm, Spec, Step  # noqa: E402

ARMS: tuple[Arm, ...] = ("hcl_raw", "terraconstructs", "awscdk", "hcl_modules")

# Kept working copies are for reproducing a divergence by hand; the installed
# dependency trees are ~600 MB per run and reproducible from the lockfiles.
PRUNE = ("node_modules", ".terraform", ".git")


class KeptTempDir:
    """`tempfile.TemporaryDirectory` shape that does not delete on exit."""

    def __init__(self, root: Path):
        self._root = root
        self._n = 0
        self.last: Path | None = None

    def __call__(self, prefix: str = "", dir: str | None = None):  # noqa: A002
        # A name already on disk is skipped rather than reused: the caller
        # creates subdirectories inside it with `parents=True` and no
        # `exist_ok`, so handing back a populated directory from an earlier
        # (or interrupted) run crashes the run instead of reproducing it.
        while True:
            self._n += 1
            path = self._root / f"{prefix}{self._n:04d}"
            if not path.exists():
                break
        path.mkdir(parents=True)
        self.last = path
        return _Kept(path)


class _Kept:
    def __init__(self, path: Path):
        self.path = path

    def __enter__(self) -> str:
        return str(self.path)

    def __exit__(self, *exc) -> bool:
        return False


def install(work_dir: Path) -> KeptTempDir:
    """Make _run_solve's scratch dirs land under `work_dir` and survive the
    run. Only oracle_falsifiability's view of `tempfile` is swapped; the real
    module keeps its deleting behaviour for every other caller in the
    process."""
    work_dir.mkdir(parents=True, exist_ok=True)
    keep = KeptTempDir(work_dir)
    of.tempfile = types.SimpleNamespace(TemporaryDirectory=keep)
    return keep


def tests_dir(task: Path, step: Step | None) -> Path:
    """A multi-step task's oracle lives under its step, never at the task root
    (the shared root `tests/` must stay oracle-free)."""
    return task / "steps" / step.name / "tests" if step is not None else task / "tests"


def fixtures(task: Path) -> list[tuple[str, Path]]:
    """`(label, solve.sh)` for the reference solution and every declared
    broken fixture, in a stable order."""
    out = [("reference", task / "solution" / "solve.sh")]
    broken = task / "solution" / "broken"
    if broken.is_dir():
        for d in sorted(broken.iterdir()):
            if (d / "solve.sh").exists():
                out.append((f"broken/{d.name}", d / "solve.sh"))
    return [(name, p) for name, p in out if p.exists()]


def plan_runs(spec: Spec, arm: Arm) -> list[tuple[Step | None, str, Path]]:
    """`(step, label, solve.sh)` for every fixture of one arm.

    Task-root fixtures are graded by the FINAL step's oracle; each non-final
    step contributes its own reference under its own oracle.
    """
    task = task_dir(spec, arm)
    if not task.is_dir():
        return []
    steps = spec.steps or []
    final_step = steps[-1] if spec.is_multi_step() else None
    runs = [(final_step, name, solve) for name, solve in fixtures(task)]
    for st in steps[:-1]:
        solve = task / "steps" / st.name / "solution" / "solve.sh"
        if solve.exists():
            runs.append((st, f"steps/{st.name}/reference", solve))
    return runs


def prune(work: Path | None) -> None:
    if work is None:
        return
    for sub in work.rglob("*"):
        if sub.is_dir() and sub.name in PRUNE:
            shutil.rmtree(sub, ignore_errors=True)


@dataclass
class Collected:
    """One fixture's run: where its documents landed and what it scored."""

    label: str
    spec_id: str
    arm: Arm
    fixture: str
    step: Step | None
    task: Path
    tests: Path
    plan: Path | None
    merged: Path | None
    reward: float | None
    seconds: float
    workdir: Path | None

    @property
    def slug(self) -> str:
        return self.label.replace("/", "__")


def collect(
    spec: Spec,
    env: dict[str, str],
    keep: KeptTempDir,
    *,
    arms: tuple[Arm, ...] = ARMS,
    require_tests: tuple[str, ...] = (),
) -> Iterator[Collected]:
    """Run every fixture of every named arm and yield where each landed.

    A generator, not a list: a fixture costs half a minute and a corpus-wide
    collection runs for an hour, so a caller has to be able to report each
    result as it lands rather than after the last one.

    `require_tests` names files that must exist in the step's `tests/` dir for
    the fixture to be worth running (`policy.rego` for a tier-1 consumer,
    `hcl_merge.py` for the HCL pre-parser one), so a caller skips an arm it
    cannot grade instead of paying 30s to discover that.
    """
    for arm in arms:
        try:
            task = task_dir(spec, arm)
        except Exception:
            continue
        if not task.is_dir():
            continue
        artifact_rel = getattr(spec.instruction.per_arm, arm).output_contract.artifact_path
        with arm_env(arm, env) as run_env:
            for step, name, solve in plan_runs(spec, arm):
                tdir = tests_dir(task, step)
                if not (tdir / "static_tiers.sh").exists():
                    continue
                if any(not (tdir / f).exists() for f in require_tests):
                    continue
                label = f"{spec.id}/{ARM_DIRNAME[arm]}/{name}"
                t0 = time.time()
                run = of._run_solve(
                    task, arm, solve, label,
                    artifact_rel=artifact_rel, step=step, env=run_env,
                )
                work = keep.last
                plan = work / "project" / artifact_rel if work else None
                merged = work / "logs" / "verifier" / "oracle-input.json" if work else None
                collected = Collected(
                    label=label, spec_id=spec.id, arm=arm, fixture=name, step=step,
                    task=task, tests=tdir,
                    plan=plan if plan and plan.is_file() and plan.stat().st_size else None,
                    merged=merged if merged and merged.is_file() and merged.stat().st_size else None,
                    reward=run.reward, seconds=round(time.time() - t0, 1), workdir=work,
                )
                prune(work)
                yield collected
