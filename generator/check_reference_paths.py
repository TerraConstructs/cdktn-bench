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
from gen import ARM_WORKSPACE_SUBDIR, task_dir  # noqa: E402
from jsonpath_jq import jsonpath_to_jq  # noqa: E402
from spec_model import Arm, Spec, StructuralAssert, load_spec  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURES_DIR = Path(__file__).resolve().parent / "tests" / "fixtures"


@dataclass
class PathCheckResult:
    label: str
    ok: bool
    detail: str


def _is_authored(fixture_dir: Path) -> bool:
    return fixture_dir.exists() and any(fixture_dir.rglob("*"))


def _prepare_project(spec: Spec, arm: Arm, fixture_file: Path, tmp: Path) -> Path:
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
    dest = project / entry_rel
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.copy2(fixture_file, dest)

    if (project / "package.json").exists():
        subprocess.run(
            ["npm", "ci", "--no-audit", "--no-fund"],
            cwd=project,
            check=True,
            capture_output=True,
            text=True,
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


def _run_toolchain(project: Path) -> str:
    """Run the real, already-generated (and now path-patched)
    tests/static_tiers.sh -- this is what actually builds/synths/plans the
    fixture. Its own exit code is NOT a useful success/failure signal here:
    by design (see generator/gen.py's build_static_tiers_sh template) it
    always writes a reward and `exit 0`, on a toolchain failure exactly as
    much as on success -- the reward.txt CONTENT is the real signal, and
    even that is irrelevant to this check (the toy spec's tier-1 policy is
    still a Slice-D-pending stub, so tier1_status is always SKIPPED_STUB
    regardless of the fixture's own correctness). The caller determines
    toolchain success the same way static_tiers.sh's own next step does:
    by checking whether the artifact file actually landed on disk."""
    proc = subprocess.run(
        ["bash", str(project / "tests" / "static_tiers.sh")],
        cwd=project,
        capture_output=True,
        text=True,
        check=False,
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


def check_arm(spec: Spec, arm: Arm) -> list[PathCheckResult]:
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
        project = _prepare_project(spec, arm, fixture_file, tmp)
        log = _run_toolchain(project)

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
                bad_project = _prepare_project(spec, arm, bad_fixture, tmp_bad)
                bad_log = _run_toolchain(bad_project)
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


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path", type=Path)
    args = parser.parse_args(argv[1:])

    spec = load_spec(args.spec_path)
    all_ok = True
    any_authored = False
    for arm in spec.arms.enabled_arms():
        if _is_authored(FIXTURES_DIR / spec.id / arm):
            any_authored = True
        for r in check_arm(spec, arm):
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
