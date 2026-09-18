#!/usr/bin/env python3
"""Generator-time jsonpath-validity gate.

For every `oracle.structural_assert` a spec declares -- tier "0" AND tier "1"
alike -- resolve its declared path and op/expected against a REAL
synthesized/planned artifact, produced by running the arm's real toolchain
against a hand-authored, oracle-CORRECT reference fixture. Tier-1 paths are
never executed by the generated tests/static_tiers.sh (tier 1 is
Rego/cfn-guard-graded), so without this a broken `tf_jsonpath` there is inert
documentation, wrong in a way nothing would ever catch.

Exit 0 iff every declared structural_assert resolves and passes against its
arm's reference fixture. Exit 3 iff every enabled arm reports NOT_AUTHORED (no
fixture under generator/tests/fixtures/<spec-id>/) -- a distinct, non-zero code
so callers can keep that case non-gating without treating it as a real PASS.

Usage: `make check-paths SPEC=specs/_toy/toy-ssm-parameter.yaml`

`--seed` is brownfield seed-parity mode. Fixture layout, toolchain
requirements, AWS access, seed parity: docs/gates.md#check-reference-paths
"""

from __future__ import annotations

import argparse
import json
import shlex
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "gates"))
from aws_stub import running_stub  # noqa: E402
from gen import ARM_WORKSPACE_SUBDIR, task_dir  # noqa: E402
from jsonpath_jq import jsonpath_to_jq  # noqa: E402
from spec_model import Arm, SeedAssert, Spec, StructuralAssert, load_spec  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "tests" / "fixtures"


@dataclass
class PathCheckResult:
    label: str
    ok: bool
    detail: str


def _is_authored(fixture_dir: Path) -> bool:
    return fixture_dir.exists() and any(fixture_dir.rglob("*"))


def _prepare_project(
    spec: Spec, arm: Arm, fixture_file: Path | None, tmp: Path, env: dict[str, str]
) -> Path:
    """Build a scratch /app/project equivalent: a copy of the GENERATED task's
    own environment/<workspace-subdir> (the exact tree the arm's Dockerfile
    COPYs into WORKDIR /app/project -- flattened, no 'workspace'/'app' prefix,
    matching real container layout) with the fixture file dropped in at
    entry_file, plus that task's own tests/ for its real, already-generated
    static_tiers.sh, _assert_lib.sh and compiled tier0.rego."""
    task = task_dir(spec, arm)
    project = tmp / "project"
    shutil.copytree(task / "environment" / ARM_WORKSPACE_SUBDIR[arm], project)

    per_arm = getattr(spec.instruction.per_arm, arm)
    entry_rel = per_arm.output_contract.entry_file
    # `fixture_file=None` is --seed mode: NO overlay at all. The project is the
    # generated task's workspace exactly as it stands, i.e. exactly what the
    # agent opens on turn one -- the whole point of the seed gate.
    if fixture_file is not None:
        dest = project / entry_rel
        dest.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(fixture_file, dest)
    else:
        seed = project / entry_rel
        if not seed.is_file() or not seed.read_text().strip():
            raise FileNotFoundError(
                f"--seed: the generated task's {entry_rel} is missing or empty for "
                f"arm {arm!r} -- run `make gen SPEC=specs/{spec.id}.yaml` first"
            )
        # The seed is the file the agent is asked to CHANGE. copytree preserves
        # the source mode; assert it here so a 0o444 regression is caught by the
        # gate that reads the workspace rather than by a failed agent edit.
        if not seed.stat().st_mode & 0o200:
            raise PermissionError(
                f"--seed: {entry_rel} is not writable on arm {arm!r} -- a "
                "brownfield seed must be agent-editable (SCHEMA.md §2.7)"
            )

    if (project / "package.json").exists():
        subprocess.run(
            ["npm", "ci", "--no-audit", "--no-fund"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
            env=env,
        )

    tests_dst = project / "tests"
    tests_dst.mkdir(exist_ok=True)
    shutil.copy2(task / "tests" / "_assert_lib.sh", tests_dst / "_assert_lib.sh")
    # The compiled tier-0 Rego, for a spec whose `oracle.tier0_engine` is
    # `rego`: static_tiers.sh loads it from its own directory, and without it
    # `opa eval` ABORTS -- no per-assert line is printed at all, and the script
    # reports the tier-0 engine error rather than anything about the fixture.
    tier0_rego = task / "tests" / "tier0.rego"
    if tier0_rego.exists():
        shutil.copy2(tier0_rego, tests_dst / "tier0.rego")
    static_text = (task / "tests" / "static_tiers.sh").read_text()
    # Repoint the two absolute, in-container paths static_tiers.sh bakes in at
    # this host-side scratch dir (same technique gates/oracle_falsifiability.py
    # uses).
    static_text = static_text.replace("/app/project", str(project))
    logs_dir = tmp / "logs" / "verifier"
    logs_dir.mkdir(parents=True, exist_ok=True)
    static_text = static_text.replace("/logs/verifier", str(logs_dir))
    static_path = tests_dst / "static_tiers.sh"
    static_path.write_text(static_text)
    static_path.chmod(0o755)
    return project


def _run_toolchain(project: Path, env: dict[str, str]) -> str:
    """Run the real, already-generated (and now path-patched)
    tests/static_tiers.sh -- what actually builds/synths/plans the fixture.

    Its exit code is NOT a usable success signal: a toolchain failure writes a
    reward and exits 0 exactly as a success does, and on the Terraform-shaped
    arms a failed `aws sts get-caller-identity` preflight exits early via the
    `run_invalid` contract. reward.txt's CONTENT is not the signal either -- a
    scenario whose tier-1 policy is still a stub reports SKIPPED_STUB
    regardless of the fixture's own correctness. The caller determines
    toolchain success the way static_tiers.sh's own next step does: by checking
    whether the artifact file landed on disk.

    `env`: the credential-free AWS environment from
    gates/aws_stub.py::running_stub(); it is what satisfies the preflight.
    """
    proc = subprocess.run(
        ["bash", str(project / "tests" / "static_tiers.sh")],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
        env=env,
    )
    return proc.stdout + proc.stderr


def _assert_check_via_bash(
    project: Path, name: str, jsonpath: str, op: str, expected: object, artifact: Path
) -> tuple[bool, str]:
    """Resolve+apply one structural_assert against `artifact` by calling the
    REAL `assert_check` bash function from this task's own (generated)
    _assert_lib.sh -- the same jq-compiled evaluator every trial's tier-0
    actually runs, so a tier-1 path that jsonpath_ng can't even parse (the
    `||`-OR'd CFN filters) is still checked for real, and there is no
    second, drifting implementation of op semantics to keep in sync."""
    jq_filter = jsonpath_to_jq(jsonpath)
    expected_json = json.dumps(expected)
    script = (
        f"set -uo pipefail\n"
        f'source {shlex.quote(str(project / "tests" / "_assert_lib.sh"))}\n'
        f"assert_check {shlex.quote(name)} {shlex.quote(jq_filter)} "
        f"{shlex.quote(op)} {shlex.quote(expected_json)} {shlex.quote(str(artifact))}\n"
    )
    proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True, check=False)
    ok = proc.returncode == 0
    return ok, (proc.stdout + proc.stderr).strip()


def _applies(a: StructuralAssert, arm: Arm) -> bool:
    return arm in a.applies_to


def check_arm(spec: Spec, arm: Arm, env: dict[str, str]) -> list[PathCheckResult]:
    results: list[PathCheckResult] = []
    fixture_dir = FIXTURES_DIR / spec.id / arm
    if not _is_authored(fixture_dir):
        results.append(PathCheckResult(f"{arm}", True, "NOT_AUTHORED (no reference fixture yet)"))
        return results

    per_arm = getattr(spec.instruction.per_arm, arm)
    entry_rel = per_arm.output_contract.entry_file
    fixture_file = fixture_dir / entry_rel
    if not fixture_file.exists():
        results.append(
            PathCheckResult(
                f"{arm}/{entry_rel}", False, f"fixture dir exists but {entry_rel!r} is missing"
            )
        )
        return results

    with tempfile.TemporaryDirectory(prefix="check-paths-good-") as tmp_s:
        tmp = Path(tmp_s)
        project = _prepare_project(spec, arm, fixture_file, tmp, env)
        log = _run_toolchain(project, env)

        artifact = project / per_arm.output_contract.artifact_path
        if not artifact.exists() or artifact.stat().st_size == 0:
            results.append(
                PathCheckResult(
                    f"{arm}/artifact",
                    False,
                    f"no artifact produced at {artifact} -- toolchain output:\n{log[-4000:]}",
                )
            )
            return results

        for a in spec.oracle.structural_asserts:
            if not _applies(a, arm):
                continue
            jsonpath = a.cfn_jsonpath if arm == "awscdk" else a.tf_jsonpath
            assert jsonpath is not None
            ok, detail = _assert_check_via_bash(project, a.name, jsonpath, a.op, a.expected, artifact)
            label = f"{arm}/{a.name} (tier {a.tier})"
            results.append(PathCheckResult(label, ok, detail))

        # Optional, best-effort bad-fixture differential check. Informational
        # for op != not_exists (already implied by the good-fixture check
        # passing); the value is in not_exists entries, whose good-fixture pass
        # alone cannot prove the path ever resolves to anything on a violating
        # artifact.
        bad_fixture = fixture_dir / "bad" / entry_rel
        if bad_fixture.exists():
            with tempfile.TemporaryDirectory(prefix="check-paths-bad-") as tmp_bad_s:
                tmp_bad = Path(tmp_bad_s)
                bad_project = _prepare_project(spec, arm, bad_fixture, tmp_bad, env)
                bad_log = _run_toolchain(bad_project, env)
                bad_artifact = bad_project / per_arm.output_contract.artifact_path
                if bad_artifact.exists() and bad_artifact.stat().st_size > 0:
                    for a in spec.oracle.structural_asserts:
                        if not _applies(a, arm) or a.op != "not_exists":
                            continue
                        jsonpath = a.cfn_jsonpath if arm == "awscdk" else a.tf_jsonpath
                        assert jsonpath is not None
                        passed, _ = _assert_check_via_bash(
                            bad_project, a.name, jsonpath, a.op, a.expected, bad_artifact
                        )
                        # not_exists PASSING on the bad/violating fixture too
                        # means the path never resolves to anything on
                        # EITHER artifact -- indistinguishable from a dead
                        # path (informational, not a hard failure: the toy's
                        # bad fixture may simply not violate every catch).
                        label = f"{arm}/{a.name} (not_exists, bad-fixture discriminates?)"
                        results.append(
                            PathCheckResult(
                                label,
                                not passed,
                                "bad fixture still resolves 0 nodes -- path may be permanently "
                                "dead, not just correctly negative"
                                if passed
                                else "bad fixture resolves >=1 node -- path discriminates",
                            )
                        )
                else:
                    results.append(
                        PathCheckResult(
                            f"{arm}/bad-fixture-toolchain",
                            True,
                            f"informational only, non-gating -- bad fixture failed to build/plan:\n{bad_log[-2000:]}",
                        )
                    )

    return results


# ---------------------------------------------------------------------------
# --seed mode: the BROWNFIELD seed-parity gate (specs/SCHEMA.md §2.7)
# ---------------------------------------------------------------------------
#
# Seed equivalence is defined BEHAVIOURALLY, by declared facts: every arm's
# seed synths/plans GREEN with no overlay, and every `seed_assert` holds on
# every arm its `applies_to` names. It is explicitly NOT resource-count or
# resource-type parity -- see docs/gates.md#check-reference-paths for why a
# census check would fail every honest seed, and for the residual human half
# (`workspace_seed.premise`) no mechanical gate can cover.


def check_seed_arm(spec: Spec, arm: Arm, env: dict[str, str]) -> list[PathCheckResult]:
    """Run the arm's REAL toolchain against the generated, UN-OVERLAID task
    workspace, then resolve every applicable `seed_assert` against the artifact
    it produced."""
    results: list[PathCheckResult] = []
    seed = spec.workspace_seed
    assert seed is not None
    per_arm = getattr(spec.instruction.per_arm, arm)

    with tempfile.TemporaryDirectory(prefix="check-seed-") as tmp_s:
        tmp = Path(tmp_s)
        try:
            project = _prepare_project(spec, arm, None, tmp, env)
        except (FileNotFoundError, PermissionError) as exc:
            results.append(PathCheckResult(f"{arm}/seed", False, str(exc)))
            return results
        log = _run_toolchain(project, env)

        artifact = project / per_arm.output_contract.artifact_path
        if not artifact.exists() or artifact.stat().st_size == 0:
            results.append(
                PathCheckResult(
                    f"{arm}/seed-plans-green",
                    False,
                    "the seeded workspace did NOT build/synth/plan -- a seed that "
                    "is not green is not existing infrastructure, it is a "
                    f"generation failure. No artifact at {artifact}. Toolchain "
                    f"output:\n{log[-4000:]}",
                )
            )
            return results
        results.append(
            PathCheckResult(
                f"{arm}/seed-plans-green",
                True,
                f"artifact produced at {per_arm.output_contract.artifact_path}",
            )
        )

        applicable = [a for a in seed.seed_asserts if arm in a.applies_to]
        if not applicable:
            results.append(
                PathCheckResult(
                    f"{arm}/seed-asserts",
                    True,
                    "no seed_assert declares this arm in applies_to (an "
                    "arm-shaped asymmetry is legal -- CFN has no `lifecycle` "
                    "meta-argument, for instance -- but a seed with NO pinned "
                    "fact at all on an arm is worth a second look)",
                )
            )
        for a in applicable:
            jsonpath = a.cfn_jsonpath if arm == "awscdk" else a.tf_jsonpath
            assert jsonpath is not None
            ok, detail = _assert_check_via_bash(
                project, a.name, jsonpath, a.op, a.expected, artifact
            )
            pin = f" pins_catch={a.pins_catch}" if a.pins_catch else ""
            results.append(PathCheckResult(f"{arm}/seed:{a.name}{pin}", ok, detail))

    return results


def run_seed_mode(spec: Spec, env: dict[str, str]) -> int:
    if spec.workspace_seed is None:
        print(
            f"seed-parity: NOT_AUTHORED for {spec.id!r} -- this spec declares no "
            "`workspace_seed` block, i.e. it is a GREENFIELD scenario whose "
            "workspace starts from the empty entry_file skeleton (SCHEMA.md "
            "§2.4). Nothing to check; non-gating.",
            file=sys.stderr,
        )
        return 3

    all_ok = True
    matrix: list[tuple[str, str, bool]] = []
    for arm in spec.arms.enabled_arms():
        for r in check_seed_arm(spec, arm, env):
            status = "PASS" if r.ok else "FAIL"
            first_line = r.detail.splitlines()[0] if r.detail else ""
            print(f"[{status}] {r.label}: {first_line}")
            matrix.append((arm, r.label, r.ok))
            if not r.ok:
                all_ok = False
                for line in r.detail.splitlines()[1:]:
                    print(f"    {line}")

    print("\nseed-parity matrix (arm x fact):")
    for arm, label, ok in matrix:
        print(f"  {'PASS' if ok else 'FAIL'}  {arm:16s} {label}")

    if not all_ok:
        print(f"\nseed-parity FAILED for {spec.id!r}", file=sys.stderr)
        return 1
    print(
        f"\nseed-parity OK for {spec.id!r} -- every arm's seed builds/plans green "
        "offline and satisfies every seed_assert it declares"
    )
    return 0


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path", type=Path)
    parser.add_argument(
        "--seed",
        action="store_true",
        help="BROWNFIELD seed-parity mode (SCHEMA.md §2.7): resolve "
        "`workspace_seed.seed_asserts` against the GENERATED, UN-OVERLAID task "
        "workspace, and require that workspace to build/synth/plan green on "
        "every enabled arm. Exit 3 (NOT_AUTHORED, non-gating) for a spec with "
        "no workspace_seed block.",
    )
    args = parser.parse_args(argv[1:])

    spec = load_spec(args.spec_path)
    # ONE stub for the whole invocation; every arm's toolchain run shares it.
    # The generated tests/static_tiers.sh this drives preflights `aws sts
    # get-caller-identity` on the Terraform-shaped arms and the stub answers it,
    # so the check needs no ambient credentials and can never reach a real
    # account.
    with running_stub() as env:
        if args.seed:
            return run_seed_mode(spec, env)
        all_ok = True
        any_authored = False
        for arm in spec.arms.enabled_arms():
            if _is_authored(FIXTURES_DIR / spec.id / arm):
                any_authored = True
            for r in check_arm(spec, arm, env):
                status = "PASS" if r.ok else "FAIL"
                first_line = r.detail.splitlines()[0] if r.detail else ""
                print(f"[{status}] {r.label}: {first_line}")
                if not r.ok:
                    all_ok = False
                    for line in r.detail.splitlines()[1:]:
                        print(f"    {line}")

        if not all_ok:
            print(f"\ncheck-reference-paths FAILED for {spec.id!r}", file=sys.stderr)
            return 1
        if not any_authored:
            # Distinct rc from a real pass: a spec with zero fixtures authored
            # must not print PASS-shaped lines ci/run-ci.sh cannot tell apart
            # from a run that really resolved every path.
            print(
                f"\ncheck-reference-paths: NOT_AUTHORED for {spec.id!r} -- no enabled "
                "arm has a reference fixture yet under generator/tests/fixtures/ "
                "(the reference-path resolution proof has NOT actually run for this "
                "scenario; non-gating, but callers must not treat this the same "
                "as a real PASS).",
                file=sys.stderr,
            )
            return 3
        print(f"\ncheck-reference-paths OK for {spec.id!r}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
