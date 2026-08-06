"""gates/oracle_falsifiability.py — the Phase-2 exit criterion, made
executable now (benchmark-integrity review finding "end-to-end reward —
oracle-violating solution scores 1.0").

Demonstrated failure this gate exists to prevent: running a generated
scenario's tier-0/tier-1 verifier against a hand-crafted artifact that
violates every clause of the scenario's own `oracle.intent` (a wrong IAM
role trust, a wildcard-resource inline policy) scored a clean 1.0 reward --
the scaffolding awarded full marks to a solution that fails the thing it
was supposed to check for. A generated `tests/static_tiers.sh` proves
nothing about a scenario's actual discriminating power until it is shown
to (a) accept a genuinely correct solution, AND (b) reject at least one
genuinely bad one *per declared catch* -- otherwise a reward of 1.0 could
just mean "the oracle never fails," not "this solution is correct."

Convention this gate enforces (new, since none existed before): for a task
directory to pass, it must have

    solution/solve.sh                  -- writes a known-good entry_file,
                                           then runs tests/static_tiers.sh
                                           (exactly what the generator's own
                                           stub docstring already says a
                                           real solve.sh does)
    solution/broken/<catch-name>/solve.sh
                                        -- one per spec.catches[].name,
                                           writes a deliberately-bad
                                           entry_file that violates that
                                           specific catch, then runs
                                           tests/static_tiers.sh the same
                                           way

Usage:
    uv run python gates/oracle_falsifiability.py specs/_toy/toy-ssm-parameter.yaml
    make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml

Exit 0 iff, for every enabled arm: solution/solve.sh is authored (not a
generator stub) AND scores reward 1.0, AND every catch has a
solution/broken/<catch-name>/solve.sh that scores reward 0.0. A scenario
whose solve.sh is still a generator stub is reported NOT_AUTHORED (Slice D
hasn't gotten to it yet) rather than FAIL -- that is the one non-gating
exception, matching the rest of this codebase's stub-detection convention
(is_stub_policy in generator/gen.py's ASSERT_LIB_SH). Once solve.sh IS
authored, missing broken/ coverage for any catch is a hard FAIL: "no
scenario should be registerable without it."
"""

from __future__ import annotations

import argparse
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
from gen import ARM_WORKSPACE_SUBDIR, task_dir  # noqa: E402
from spec_model import Arm, Spec, load_spec  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

SOLVE_STUB_MARKER = "is not yet authored (Slice D)"


@dataclass
class RunResult:
    label: str
    reward: float | None
    ok: bool
    detail: str


def _is_stub(solve_sh: Path) -> bool:
    if not solve_sh.exists():
        return True
    return SOLVE_STUB_MARKER in solve_sh.read_text()


def _run_solve(task: Path, arm: Arm, solve_sh: Path, label: str) -> RunResult:
    """Copy `task`'s environment/<workspace-subdir> (the exact tree the
    arm's own Dockerfile COPYs into WORKDIR /app/project -- flattened, no
    'workspace'/'app' prefix, matching real container layout: `workspace/`
    for awscdk/hcl_raw, `app/` for terraconstructs, per gen.py's
    ARM_WORKSPACE_SUBDIR) into the SANDBOX ROOT, run `solve_sh` there with
    cwd=that scratch dir, and read back /logs/verifier/reward.txt. Runs
    entirely on the host using whatever toolchain is on PATH
    (terraform/cfn-guard/opa/node/npm) -- the same approach used to
    hand-verify every other fix in this review, not a new mechanism.

    Finding F1 (benchmark-integrity review, fixed 2026-08-06): this used to
    copytree the WHOLE `environment/` dir (workspace/fixtures/mirror-src/
    preflight.sh/terraformrc for hcl_raw; the analogous per-arm layout for
    the others) into the sandbox, landing the arm's actual entry_file/
    bootstrap files at `<sandbox>/workspace/main.tf` or `<sandbox>/app/
    main.ts` -- one directory level too deep. But the generated
    `tests/static_tiers.sh` (patched below to run against this sandbox
    exactly the way it runs against `/app/project` in a real trial) does
    `cd /app/project` and then reads `main.tf`/`cdk.out/...` etc directly
    at that root -- so with the old copy, `terraform init`/`cdk synth`
    always ran against an EMPTY directory (no .tf/.ts files at the root
    the tools actually looked in), and every solve.sh, however correct,
    could only ever fail. Reusing generator/check_reference_paths.py's own
    `_prepare_project` pattern (`environment/<ARM_WORKSPACE_SUBDIR[arm]>`
    flattened onto the sandbox root, the same mapping every arm's own
    Dockerfile encodes) fixes this: proven below by a self-test
    (gates/tests/test_oracle_falsifiability.py) that runs this exact
    function against a known-good, hand-authored solve.sh and asserts
    reward 1.0 -- a regression back to the whole-`environment/` copy makes
    that test fail loudly instead of silently reintroducing the bug."""
    with tempfile.TemporaryDirectory(prefix="falsifiability-") as tmp:
        project = Path(tmp) / "project"
        logs = Path(tmp) / "logs" / "verifier"
        logs.mkdir(parents=True)
        workspace_dir = task / "environment" / ARM_WORKSPACE_SUBDIR[arm]
        shutil.copytree(workspace_dir, project, dirs_exist_ok=True)
        shutil.copytree(task / "tests", project / "tests", dirs_exist_ok=True)
        shutil.copytree(task / "solution", project / "solution", dirs_exist_ok=True)
        # awscdk/terraconstructs ship package.json/package-lock.json in
        # their workspace subdir but node_modules is only populated inside
        # the arm's Docker image (`npm ci` at build time) -- on the host
        # sandbox it must be installed for real, same as
        # generator/check_reference_paths.py's own `_prepare_project`.
        if (project / "package.json").exists():
            subprocess.run(
                ["npm", "ci", "--no-audit", "--no-fund"],
                cwd=project,
                check=True,
                capture_output=True,
                text=True,
            )
        rel_solve = solve_sh.relative_to(task)
        reward_file = logs / "reward.txt"
        # tests/static_tiers.sh (generated with absolute /logs/verifier and
        # /app/project paths, since that's where it really runs inside a
        # trial's container) is patched to point at this scratch sandbox
        # instead, mirroring the manual proof technique used throughout
        # this review -- solve.sh's own docstring convention is "writes a
        # known-good entry_file, then runs the same tests/static_tiers.sh a
        # real trial's verifier runs", so patching that one file is enough
        # to make the whole chain self-contained on the host.
        static_tiers = project / "tests" / "static_tiers.sh"
        if static_tiers.exists():
            text = static_tiers.read_text()
            text = text.replace("/logs/verifier", str(logs))
            text = text.replace("/app/project", str(project))
            static_tiers.write_text(text)
        proc = subprocess.run(
            ["bash", str(project / rel_solve)],
            cwd=project,
            capture_output=True,
            text=True,
            check=False,
        )
        if not reward_file.exists():
            return RunResult(label, None, False, f"no reward.txt written; stderr={proc.stderr[-2000:]}")
        try:
            reward = float(reward_file.read_text().strip())
        except ValueError:
            return RunResult(label, None, False, f"reward.txt unparseable: {reward_file.read_text()!r}")
        return RunResult(label, reward, True, proc.stdout[-2000:])


def check_arm(spec: Spec, arm: Arm) -> list[RunResult]:
    task = task_dir(spec, arm)
    solve_sh = task / "solution" / "solve.sh"
    results: list[RunResult] = []

    if _is_stub(solve_sh):
        results.append(RunResult(f"{arm}/solution/solve.sh", None, True, "NOT_AUTHORED (Slice D pending)"))
        return results

    good = _run_solve(task, arm, solve_sh, f"{arm}/solution/solve.sh")
    good.ok = good.ok and good.reward == 1.0
    results.append(good)

    catch_names = {catch.name for catch in spec.catches}
    for catch in spec.catches:
        broken_solve = task / "solution" / "broken" / catch.name / "solve.sh"
        label = f"{arm}/solution/broken/{catch.name}/solve.sh"
        if not broken_solve.exists():
            results.append(RunResult(label, None, False, "MISSING -- every catch needs a broken/ fixture once solve.sh is authored"))
            continue
        bad = _run_solve(task, arm, broken_solve, label)
        bad.ok = bad.ok and bad.reward == 0.0
        results.append(bad)

    # Extra, non-catch-named negative fixtures under solution/broken/ --
    # added by the "tier-1 oracle vacuity" fix (2026-08-06) alongside the
    # widened rego/cfn-guard bundles, to prove an alternate-but-equally-
    # idiomatic IAM shape (e.g. aws_iam_policy+aws_iam_role_policy_attachment
    # on the TF arms, inlinePolicies on awscdk) is caught too, not just the
    # ONE shape a declared catch's own name happens to cover. Any directory
    # here NOT matching a declared catch name is discovered and required to
    # score reward 0.0 the same way, so a future regression that re-narrows
    # the policy bundle back to a single shape turns this gate red instead
    # of silently losing coverage no catch name names.
    broken_dir = task / "solution" / "broken"
    if broken_dir.is_dir():
        for extra_dir in sorted(broken_dir.iterdir()):
            if not extra_dir.is_dir() or extra_dir.name in catch_names:
                continue
            extra_solve = extra_dir / "solve.sh"
            label = f"{arm}/solution/broken/{extra_dir.name}/solve.sh"
            if not extra_solve.exists():
                results.append(RunResult(label, None, False, "directory present but solve.sh missing"))
                continue
            bad = _run_solve(task, arm, extra_solve, label)
            bad.ok = bad.ok and bad.reward == 0.0
            results.append(bad)

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path", type=Path)
    args = parser.parse_args(argv[1:])

    spec = load_spec(args.spec_path)
    all_ok = True
    for arm in spec.arms.enabled_arms():
        for r in check_arm(spec, arm):
            status = "PASS" if r.ok else "FAIL"
            print(f"[{status}] {r.label}: reward={r.reward} -- {r.detail.splitlines()[-1] if r.detail else ''}")
            if not r.ok:
                all_ok = False

    if all_ok:
        print(f"\nfalsifiability OK for {spec.id!r}")
        return 0
    print(f"\nfalsifiability FAILED for {spec.id!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
