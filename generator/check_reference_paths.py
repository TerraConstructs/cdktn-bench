#!/usr/bin/env python3
"""generator/check_reference_paths.py — generator-time jsonpath-validity gate.

Fixes the third part of benchmark-integrity finding G2 (2026-08-06):
SCHEMA.md §4.2's "one tf_jsonpath covers both TF arms, only values differ,
never path shape" claim was FALSE for plan-time-unknown attributes
(`.planned_values...aws_iam_role_policy...values.policy` resolves to
NOTHING at plan time whenever the policy's Resource references a
provider-computed attribute like the created parameter's `.arn` -- see
specs/SCHEMA.md §4.2's corrected note and
specs/_toy/toy-ssm-parameter.yaml's own "G2 fix" comments for the full
story). That dead path shipped silently because nothing ever resolved a
tier-1 structural_assert against a REAL synthesized/planned artifact --
tier-1 entries are never executed by the generated tests/static_tiers.sh
(tier-1 is Rego/cfn-guard-graded), so a broken tf_jsonpath there was pure
inert documentation, wrong in a way nothing would ever catch.

What this script does: for every `oracle.structural_assert` a spec declares
(tier "0" AND tier "1" alike), resolve its declared path with its declared
op/expected against a REAL synthesized/planned artifact, produced by
running the arm's REAL toolchain (terraform/npm/node/cdk/cdktn -- whatever
is on PATH, same host-toolchain assumption as gates/oracle_falsifiability.py)
against a hand-authored, oracle-CORRECT reference fixture -- not the spec
author's mental model of what the artifact looks like. This is exactly the
check that would have caught policy-actions-read-only's old dead
`.values.policy` tf_jsonpath before it shipped: op="in" against zero
resolved nodes is False, so a real assert_check failure here, instead of
silence.

It resolves every path through the SAME mechanism the real generated
tests/static_tiers.sh uses for tier-0 (`generator/jsonpath_jq.py`'s jq
compilation + `_assert_lib.sh`'s `assert_check` bash function) -- not a
second, Python-side JSONPath evaluator (`oracles/lib/structural.py` uses
`jsonpath_ng`, which cannot parse the `||`-OR'd filter syntax several tier-1
CFN paths use at all -- see that module's own docstring). Reusing the real
jq-compiled path means this check is checking the SAME code every trial
actually runs, and sidesteps that parser gap entirely.

Fixtures: `generator/tests/fixtures/<spec-id>/<arm-dirname>/<entry_file>`
-- ONE hand-authored, oracle-CORRECT file per enabled arm, dropped in place
of the ALREADY-GENERATED task's own entry_file (everything else --
provider.tf/bin/app.ts/main.ts bootstrap, environment/ toolchain, tests/ --
comes from the real generated task dir, so this exercises the exact same
path a trial's verifier does, including this repo's own G1/G3 fixes to
that toolchain). Optionally, `.../bad/<entry_file>` -- a fixture that
deliberately VIOLATES one or more catches -- is used for an additional,
best-effort cross-check: any op != "not_exists" that fails on the bad
fixture (proving the path can tell good from bad) is reported but never
required, since not every scenario will have one; but if declared, an
op == "not_exists" assert that does NOT resolve a violation on the bad
fixture is flagged (a not_exists check passing vacuously on a real correct
artifact tells you nothing about whether it would ever catch a real
violation -- this is the belt-and-suspenders half of the check).

A spec with no `generator/tests/fixtures/<spec-id>/` directory yet reports
NOT_AUTHORED (non-gating) -- mirrors gates/oracle_falsifiability.py's
solve.sh convention; this script is meant to run standalone, long before a
scenario's real solution/solve.sh exists (Slice D).

Usage:
    uv run python generator/check_reference_paths.py specs/_toy/toy-ssm-parameter.yaml
    make check-paths SPEC=specs/_toy/toy-ssm-parameter.yaml

Exit 0 iff every declared structural_assert resolves+passes (its own
op/expected) against its arm's reference fixture, for every arm that has
one authored. Exit 3 iff every enabled arm reports NOT_AUTHORED (no arm
has a reference fixture yet under generator/tests/fixtures/<spec-id>/) --
a DISTINCT, non-zero code from a real pass, added for the "check-paths is
VACUOUS for every real scenario, yet `make ci` prints 'check-paths PASS'"
finding (2026-08-06): before this, a spec with zero fixtures authored
reported the exact same exit code (0) and the exact same PASS-shaped
per-arm lines as a spec whose fixtures actually ran the real toolchain and
resolved every path -- ci/run-ci.sh's summary table could not (and did
not) tell the two apart. Callers that want NOT_AUTHORED to stay
non-gating (this script's own long-documented convention -- Slice D simply
hasn't authored a fixture yet) should treat rc==3 specially, not as a
failure; see ci/run-ci.sh's own SKIP-status handling for the reference
implementation. Requires the real arm toolchain (terraform, node/npm, jq)
on PATH, and network the first time `npm ci` needs to populate
node_modules for awscdk/terraconstructs fixtures -- same assumptions as
gates/oracle_falsifiability.py; not wired into `make check`/test-gates for
the same reason (mk/rails.mk's gate-preflight note).

AWS access: this script runs CREDENTIAL-FREE, against
`gates/aws_stub.py::running_stub()` -- started ONCE per invocation in
main(), its env threaded into every toolchain subprocess below. Live AWS is
the only trial mode (aws-access.html), so the generated
tests/static_tiers.sh this script executes preflights `aws sts
get-caller-identity` on both Terraform-shaped arms and voids the run
without it; the stub answers that preflight, and it is what keeps this
check from either failing on a credential-free host or silently planning
against an operator's real account.
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
    """Build a scratch /app/project equivalent: a copy of the GENERATED
    task's own environment/<workspace-subdir> (the exact tree the arm's own
    Dockerfile COPYs into WORKDIR /app/project -- flattened, no
    'workspace'/'app' prefix, matching real container layout) with the
    fixture file dropped in at entry_file, plus that task's own tests/
    (for its real, already-generated static_tiers.sh + _assert_lib.sh)."""
    task = task_dir(spec, arm)
    project = tmp / "project"
    shutil.copytree(task / "environment" / ARM_WORKSPACE_SUBDIR[arm], project)

    per_arm = getattr(spec.instruction.per_arm, arm)
    entry_rel = per_arm.output_contract.entry_file
    # `fixture_file=None` is --seed mode: NO overlay at all. The project is the
    # generated task's workspace exactly as it stands, i.e. exactly what the
    # agent opens on turn one -- which is the whole point of the seed gate
    # (design memo §4.2: "the same procedure with the fixture overlay omitted").
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
    static_text = (task / "tests" / "static_tiers.sh").read_text()
    # Path-patch the two absolute, in-container paths this script bakes in
    # (same technique gates/oracle_falsifiability.py uses) so it runs
    # correctly against this host-side scratch dir instead.
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
    tests/static_tiers.sh -- this is what actually builds/synths/plans the
    fixture. Its own exit code is NOT a useful success/failure signal here:
    a toolchain failure writes a reward and exits 0 exactly as a success
    does, and on the Terraform-shaped arms a failed `aws sts
    get-caller-identity` preflight exits early via the `run_invalid`
    contract -- so no exit code distinguishes the cases this check cares
    about. The reward.txt CONTENT is not the signal either (the toy spec's
    tier-1 policy is still a Slice-D-pending stub, so tier1_status is always
    SKIPPED_STUB regardless of the fixture's own correctness). The caller
    determines toolchain success the same way static_tiers.sh's own next
    step does: by checking whether the artifact file actually landed on
    disk.

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

        # Optional, best-effort bad-fixture differential check (informational
        # for op != not_exists -- already implied by the good-fixture check
        # above passing; the real value here is not_exists-op entries, whose
        # good-fixture pass alone can't prove the path ever resolves to
        # anything on a violating artifact).
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
# --seed mode: the BROWNFIELD seed-parity gate (SCHEMA.md §2.7)
# ---------------------------------------------------------------------------
#
# What "the three seeds are equivalent" must and must not mean (design memo
# §4.1). NOT resource-count or resource-type parity: the whole thesis of this
# benchmark is that one L2 construct decomposes into N Terraform resources, so a
# census check would fail every honest seed. Equivalence is defined
# BEHAVIOURALLY, by declared facts:
#
#   1. every arm's seed synth/plans GREEN, with no overlay -- a workspace that
#      doesn't is not "existing infrastructure", it is a generation failure;
#   2. every `seed_assert` holds on every arm it declares applies_to, resolved
#      through the SAME jq compiler + `_assert_lib.sh::assert_check` a real
#      trial's tier-0 runs.
#
# The residual, human half is `workspace_seed.premise`: a mechanical gate can
# prove "these three configurations satisfy the same declared facts", never
# "these three describe the same system". That is exactly the status `oracle.
# intent` already has, and the premise is reviewed the same way.


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
    # ONE stub for the whole invocation -- every arm's toolchain run shares
    # it (the same lifecycle gates/grading_proof.py uses). The generated
    # tests/static_tiers.sh this drives preflights `aws sts
    # get-caller-identity` on the Terraform-shaped arms; the stub answers
    # it, so the check needs no ambient credentials and can never reach a
    # real account.
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
            # Distinct rc from a real pass -- see this module's own docstring
            # ("Exit 3 iff...") for the finding this closes.
            print(
                f"\ncheck-reference-paths: NOT_AUTHORED for {spec.id!r} -- no enabled "
                "arm has a reference fixture yet under generator/tests/fixtures/ "
                "(the G2 path-resolution proof has NOT actually run for this "
                "scenario; non-gating, but callers must not treat this the same "
                "as a real PASS).",
                file=sys.stderr,
            )
            return 3
        print(f"\ncheck-reference-paths OK for {spec.id!r}")
        return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
