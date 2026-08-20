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

MULTI-STEP (SCHEMA.md §2.6 / DECISIONS.md Amendment 27, 2026-08-20)
===================================================================
A spec with `steps:` has one oracle PER STEP, under `steps/<name>/tests/`,
and no root `tests/` oracle at all. This gate then:

  * runs the task-root `solution/solve.sh` and every
    `solution/broken/<catch>/solve.sh` against the **FINAL** step's oracle.
    That is not a convenience: the final step's oracle IS the full tier
    suite (spec_model enforces it), so those rows check byte-for-byte what
    they checked before the decomposition -- same asserts, same script, same
    expected rewards. Every declared catch is a fact about the FINAL
    delivered artifact, which is what the root reference solution produces.
  * ADDITIONALLY requires each NON-final step to have its own
    `steps/<name>/solution/solve.sh` scoring reward 1.0 against that step's
    own (subset) oracle. This is the new proof obligation the decomposition
    creates: without it nothing shows an intermediate step's oracle is
    satisfiable, and a step-01 oracle that no correct step-01 solution can
    pass would abort every trial at the min_reward gate before step 02's
    prompt ever fired.

The sandbox's `tests/` for a given step is the SHARED root `tests/` merged
with that step's own `tests/` -- exactly what Harbor's verifier uploads into
`/tests` for that step (harbor/verifier/verifier.py::_resolve_tests), so a
solve.sh's `bash tests/static_tiers.sh` means the same thing here as in a
real trial.
"""

from __future__ import annotations

import argparse
import json
import re
import shutil
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "generator"))
from gen import (  # noqa: E402
    ARM_DIRNAME,
    ARM_WORKSPACE_SUBDIR,
    SEED_UNCHANGED_FIXTURE,
    SOLVE_STUB_MARKER,
    task_dir,
)
from spec_model import Arm, Catch, Spec, Step, load_spec  # noqa: E402

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from oracles.lib.tier05_jsonata import Tier05Error, run_tier05  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# Slice G addition (apigw-redeploy, 2026-08-06): the fixed marker string a
# `predicted_tier_caught: "live"` broken/ fixture's OFFLINE (LIVE unset/0)
# run must print, after mechanically confirming (not just claiming) the
# static-indistinguishability property that is this catch's whole point --
# see check_arm()'s "live" branch below and
# docs/apigw-redeploy-mechanics.md §6(c). Shared here (not duplicated in
# each fixture) so the gate and every fixture agree on the exact string.
LIVE_ONLY_CONFIRMED_MARKER = "CDKTN_BENCH_LIVE_ONLY_CONFIRMED"

_MIRROR_CACHE: dict[str, dict[str, set[str]] | None] = {}


def _arm_mirror_provider_versions(arm: Arm) -> dict[str, set[str]] | None:
    """`{full_name: {version, ...}}` (e.g. `{"registry.terraform.io/hashicorp/aws":
    {"6.52.0"}}`) actually baked into `cdktn-bench/<arm>:dev`'s own
    `/opt/terraform-plugin-mirror`, by extracting it via `docker cp` and
    reading the mirror's own `<namespace>/<type>/index.json` files (the
    same format `terraform providers mirror` writes and a `filesystem_mirror`
    block reads, SCHEMA.md §4.2's sibling contract -- see arms/*/environment/
    terraformrc). Used by `_check_mirror_coverage` below to prove a
    synthesized artifact's actual provider requirements are satisfiable
    OFFLINE by this specific arm image, without needing to run `terraform
    init` against a platform-matched copy of the mirror on the host (which
    doesn't work cross-platform -- the mirror only contains packages for the
    image's own build platform, e.g. linux_arm64, not darwin_arm64/host
    dev-machine platforms; verified directly, see the fix commentary this
    function's caller carries). Returns `None` for `awscdk` (no terraform
    CLI in that arm's grading path) or if the image can't be inspected."""
    if arm == "awscdk":
        return None
    if arm in _MIRROR_CACHE:
        return _MIRROR_CACHE[arm]
    image = f"cdktn-bench/{ARM_DIRNAME[arm]}:dev"
    cache_dir = REPO_ROOT / ".cache" / "falsifiability-tf-mirror" / arm
    mirror_dir = cache_dir / "mirror"
    container = None
    try:
        created = subprocess.run(
            ["docker", "create", image, "true"],
            capture_output=True,
            text=True,
            check=True,
        )
        container = created.stdout.strip()
        if mirror_dir.exists():
            shutil.rmtree(mirror_dir)
        cache_dir.mkdir(parents=True, exist_ok=True)
        subprocess.run(
            ["docker", "cp", f"{container}:/opt/terraform-plugin-mirror", str(mirror_dir)],
            check=True,
            capture_output=True,
            text=True,
        )
    except (subprocess.CalledProcessError, FileNotFoundError) as exc:
        print(
            f"WARNING: could not extract {image}'s own provider mirror ({exc}) "
            "-- provider-mirror-coverage checking is DISABLED for this run, "
            "which reopens the registry-vs-mirror divergence gap. Run "
            "`make build-arms` first.",
            file=sys.stderr,
        )
        _MIRROR_CACHE[arm] = None
        return None
    finally:
        if container:
            subprocess.run(["docker", "rm", "-f", container], capture_output=True, check=False)

    versions: dict[str, set[str]] = {}
    registry_root = mirror_dir / "registry.terraform.io"
    if registry_root.is_dir():
        for namespace_dir in registry_root.iterdir():
            if not namespace_dir.is_dir():
                continue
            for type_dir in namespace_dir.iterdir():
                index_json = type_dir / "index.json"
                if not index_json.is_file():
                    continue
                full_name = f"registry.terraform.io/{namespace_dir.name}/{type_dir.name}"
                try:
                    versions[full_name] = set(json.loads(index_json.read_text()).get("versions", {}))
                except (json.JSONDecodeError, OSError):
                    continue
    _MIRROR_CACHE[arm] = versions
    return versions


_PINNED_VERSION_RE = re.compile(r"^[0-9]+\.[0-9]+\.[0-9]+$")


def _check_mirror_coverage(document: dict, arm: Arm) -> tuple[bool, str]:
    """Every provider `configuration.provider_config` in a synthesized
    artifact names (by `full_name` + a literal, pinned `version_constraint`
    -- a range constraint doesn't pin one version to check, and is skipped,
    not silently treated as covered) must actually be present in THIS arm
    image's own offline mirror (`_arm_mirror_provider_versions`). Fixes the
    root cause of benchmark-integrity finding "apigw-openapi / terraconstructs
    arm -- catch cannot fire at all in the real image": a solution that
    synthesizes cleanly and plans successfully on the HOST (which resolves
    providers from the public registry) can still be fundamentally
    unrunnable inside the arm's actual `--network none` image if a required
    provider was never mirrored there -- exactly what happened with
    `hashicorp/archive` before that finding's fix (arms/terraconstructs/
    environment/mirror-src/main.tf). Returns `(True, "")` when mirror
    checking is unavailable (image not built -- a separately reported,
    louder warning) rather than silently failing every run for an unrelated
    reason."""
    mirror = _arm_mirror_provider_versions(arm)
    if mirror is None:
        return True, ""
    missing: list[str] = []
    for cfg in document.get("configuration", {}).get("provider_config", {}).values():
        full_name = cfg.get("full_name") or f"registry.terraform.io/{cfg.get('name', '?')}"
        constraint = str(cfg.get("version_constraint", "")).strip()
        if not _PINNED_VERSION_RE.match(constraint):
            continue  # not a single pinned version -- nothing to check statically
        if constraint not in mirror.get(full_name, set()):
            missing.append(f"{full_name}@{constraint} (mirror has: {sorted(mirror.get(full_name, set())) or 'nothing'})")
    if missing:
        return False, "provider(s) required by this artifact are MISSING from the arm image's own offline mirror: " + "; ".join(missing)
    return True, ""


# `== summary: tier0_pass=N tier1_status=X ==` -- generator/gen.py's
# build_static_tiers_sh's own literal format, matched here to recover an
# OBSERVED tier from a run's stdout (see observed_tier() below).
_SUMMARY_RE = re.compile(r"== summary: tier0_pass=(\d) tier1_status=(\S+) ==")
# Every generated toolchain step (build/synth/plan/validate/init) that fails
# before tier-0 structural asserts even run prints "<LABEL> FAILED" and
# writes reward 0.0 immediately (generator/gen.py's toolchain_block) -- a
# rejection at this stage is a tier-"0"-equivalent catch (caught by the
# compiler/synthesizer itself, with no Rego/cfn-guard tooling involved at
# all), the same bucket predicted_tier_caught's "0" denotes.
_TOOLCHAIN_FAILED_RE = re.compile(r"^[A-Z][A-Z0-9_ ]* FAILED$", re.MULTILINE)


def observed_tier(stdout: str) -> str | None:
    """Recover the tier a run's `tests/static_tiers.sh` actually caught a
    violation at, from its stdout -- the mechanical backstop
    `predicted_tier_caught` never had (benchmark-integrity review finding
    "gates/oracle_falsifiability.py -- predicted_tier_caught is never
    verified"). Returns `"0"`, `"1"`, or `None` (never caught by any static
    tier -- the expected outcome for a "0.5"-predicted catch, and a mismatch
    for anything else)."""
    if _TOOLCHAIN_FAILED_RE.search(stdout):
        return "0"
    m = _SUMMARY_RE.search(stdout)
    if not m:
        return None
    tier0_pass, tier1_status = m.group(1), m.group(2)
    if tier0_pass == "0":
        return "0"
    if tier1_status == "FAIL":
        return "1"
    return None


def predicted_tier(catch: Catch, arm: Arm) -> str:
    """`catches[].predicted_tier_caught` for one arm (SCHEMA.md §3):
    `.awscdk` for awscdk; `.hcl` for hcl_raw AND terraconstructs UNLESS
    `.terraconstructs_override` is set, in which case that wins for
    terraconstructs specifically (the "terraconstructs' own typed surface
    diverges" escape hatch)."""
    if arm == "awscdk":
        return catch.predicted_tier_caught.awscdk
    if arm == "terraconstructs" and catch.predicted_tier_caught.terraconstructs_override is not None:
        return catch.predicted_tier_caught.terraconstructs_override
    return catch.predicted_tier_caught.hcl


@dataclass
class RunResult:
    label: str
    reward: float | None
    ok: bool
    detail: str
    # Populated only when the caller asked _run_solve to also evaluate
    # Tier 0.5 against the artifact this run produced (tier05_spec passed) --
    # None otherwise. See the "0.5"-predicted-catch branch in check_arm()
    # below: unlike every other tier, a "0.5"-predicted catch's broken/
    # fixture is EXPECTED to score reward 1.0 (Tier 0.5 never gates
    # reward.txt, DECISIONS.md "Tier-0.5 runs host-side, non-gating" --
    # that invisibility to the static tiers IS the catch's own defining
    # property, the anti-L2 falsifiability instrument prereg §5/H2 names).
    # Falsifying such a catch means proving Tier 0.5 ITSELF catches it,
    # which needs the actual (still-warm) artifact this same sandboxed run
    # produced -- not a second, separately-sandboxed invocation.
    tier05_ok: bool | None = None
    tier05_detail: str = ""
    # Populated whenever this run produced an artifact on a terraform-shaped
    # arm (hcl_raw/terraconstructs) -- False means this artifact requires a
    # provider genuinely absent from that arm image's own offline mirror
    # (see _check_mirror_coverage). None means the check didn't apply/run.
    mirror_ok: bool | None = None
    mirror_detail: str = ""


def _is_stub(solve_sh: Path) -> bool:
    if not solve_sh.exists():
        return True
    return SOLVE_STUB_MARKER in solve_sh.read_text()


def _stage_tests_dir(task: Path, project: Path, step: Step | None) -> None:
    """Build the sandbox's `tests/` the way Harbor builds a step's `/tests`.

    Single-step: the task's own `tests/`, unchanged.
    Multi-step: the SHARED root `tests/` first, then `steps/<name>/tests/`
    over the top -- the same two source dirs, in the same order, that
    `harbor/verifier/verifier.py::_resolve_tests` uploads into `/tests` for
    that step. The shared dir is optional there and here (a multi-step task's
    root `tests/` holds only a README).
    """
    shared = task / "tests"
    if shared.is_dir():
        shutil.copytree(shared, project / "tests", dirs_exist_ok=True)
    if step is not None:
        step_tests = task / "steps" / step.name / "tests"
        if step_tests.is_dir():
            shutil.copytree(step_tests, project / "tests", dirs_exist_ok=True)


def _run_solve(
    task: Path,
    arm: Arm,
    solve_sh: Path,
    label: str,
    *,
    tier05_spec: dict | None = None,
    artifact_rel: str | None = None,
    step: Step | None = None,
) -> RunResult:
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
        _stage_tests_dir(task, project, step)
        if (task / "solution").is_dir():
            shutil.copytree(task / "solution", project / "solution", dirs_exist_ok=True)
        # Multi-step: the step tree is copied at its real relative path, so a
        # `steps/<n>/solution/solve.sh` still resolves (and so a step solution
        # can reach the root one -- steps/01's reference solution is a thin
        # STEP=01 wrapper around it, by design; see that file's header).
        if (task / "steps").is_dir():
            shutil.copytree(task / "steps", project / "steps", dirs_exist_ok=True)
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

        document: dict | None = None
        if artifact_rel is not None:
            artifact = project / artifact_rel
            if artifact.exists() and artifact.stat().st_size > 0:
                document = json.loads(artifact.read_text())

        tier05_ok: bool | None = None
        tier05_detail = ""
        if tier05_spec is not None:
            if document is None:
                tier05_ok = False
                tier05_detail = f"tier05: no artifact at {project / (artifact_rel or '?')} to evaluate"
            else:
                try:
                    results = run_tier05(document, tier05_spec)
                    tier05_ok = bool(results) and all(r.passed for r in results)
                    tier05_detail = "; ".join(r.explain() for r in results if not r.passed)
                except Tier05Error as exc:
                    tier05_ok = False
                    tier05_detail = f"tier05: {exc}"

        # Provider-mirror-coverage check (arms/*.hcl-shaped only -- see
        # _check_mirror_coverage's own docstring for the finding this
        # closes): a solution that reaches reward 1.0 on the HOST (public
        # registry) but requires a provider genuinely absent from the arm
        # image's own offline mirror is not really achievable inside a real
        # trial's `--network none` container -- surfaced here as a distinct
        # `mirror_ok=False`, folded into `.ok` by check_arm below, rather
        # than silently trusting a host-side reward of 1.0.
        mirror_ok: bool | None = None
        mirror_detail = ""
        if arm in ("hcl_raw", "terraconstructs") and document is not None:
            mirror_ok, mirror_detail = _check_mirror_coverage(document, arm)

        # Full stdout (not truncated) -- observed_tier() must see the
        # "== summary: tier0_pass=... ==" / "<LABEL> FAILED" lines
        # regardless of how much tier-0 assert-check chatter precedes them;
        # main() truncates for display only.
        return RunResult(
            label, reward, True, proc.stdout,
            tier05_ok=tier05_ok, tier05_detail=tier05_detail,
            mirror_ok=mirror_ok, mirror_detail=mirror_detail,
        )


def _check_non_final_steps(spec: Spec, arm: Arm, task: Path) -> list[RunResult]:
    """Every NON-final step needs its own reference solution scoring 1.0.

    The new proof obligation the multi-step decomposition creates (see this
    module's docstring). Nothing else in the repo shows that an intermediate
    step's oracle is SATISFIABLE, and an unsatisfiable step-01 oracle would
    abort every trial at the `min_reward` hard gate before step 02's prompt
    is ever delivered -- silently, since Harbor records a step abort on the
    StepResult and not on the trial (DECISIONS.md Amendment 26 §3).

    The FINAL step is deliberately absent here: its reference is the
    task-root `solution/solve.sh`, checked by `check_arm` under its original
    label so `gates/grading_proof.py`'s own row lookups keep working.
    """
    results: list[RunResult] = []
    steps = spec.steps or []
    artifact_rel = getattr(spec.instruction.per_arm, arm).output_contract.artifact_path
    for step in steps[:-1]:
        step_solve = task / "steps" / step.name / "solution" / "solve.sh"
        label = f"{arm}/steps/{step.name}/solution/solve.sh"
        if _is_stub(step_solve):
            results.append(RunResult(label, None, True, "NOT_AUTHORED (step reference solution pending)"))
            continue
        run = _run_solve(task, arm, step_solve, label, artifact_rel=artifact_rel, step=step)
        run.ok = run.ok and run.reward == 1.0
        if run.mirror_ok is False:
            run.ok = False
        results.append(run)
    return results


def _check_seed_unchanged(
    spec: Spec, arm: Arm, task: Path, step: Step | None
) -> list[RunResult]:
    """THE MANDATORY BROWNFIELD DO-NOTHING CATCH (SCHEMA.md §2.7,
    DECISIONS.md Amendment 28 §5).

    A brownfield workspace does not start empty — it starts from working,
    green configuration. That creates one failure mode no other check in this
    repo can see: if the change request the prompt asks for is *already
    satisfied by the seed*, an agent that edits nothing at all scores 1.0, and
    every gate stays green. `solution/solve.sh` scoring 1.0 proves the oracle
    ACCEPTS a correct change; it never proves the oracle REJECTS the absence of
    one.

    So: every `workspace_seed` spec must ship
    `solution/broken/seed-unchanged/solve.sh` (a no-op — generator-OWNED, see
    gen.py::build_seed_unchanged_solve_sh) and it must score **< 1.0**. Missing
    is a hard FAIL, not a skip: the fixture is generator-written, so its absence
    means either a stale task dir or a deliberate deletion, and both must be
    loud.

    `< 1.0` rather than `== 0.0` on purpose. 0.0 is what today's reward contract
    produces and is what this pilot observes, but the *claim* being falsified is
    "doing nothing does not earn full marks" — pinning it to an exact 0.0 would
    couple this gate to the reward scale rather than to the property.
    """
    if spec.workspace_seed is None:
        return []
    label = f"{arm}/solution/broken/{SEED_UNCHANGED_FIXTURE}/solve.sh (DO-NOTHING)"
    solve = task / "solution" / "broken" / SEED_UNCHANGED_FIXTURE / "solve.sh"
    if not solve.exists():
        return [
            RunResult(
                label,
                None,
                False,
                "MISSING -- every workspace_seed spec must ship the do-nothing "
                "negative (SCHEMA.md §2.7). It is generator-owned: run "
                f"`make gen SPEC=specs/{spec.id}.yaml`.",
            )
        ]
    artifact_rel = getattr(spec.instruction.per_arm, arm).output_contract.artifact_path
    run = _run_solve(task, arm, solve, label, artifact_rel=artifact_rel, step=step)
    scored = run.reward is not None and run.reward < 1.0
    # A reward BELOW 1.0 is necessary but NOT sufficient, and this is the one
    # fixture where that distinction bites. `tests/static_tiers.sh` writes 0.0
    # for a toolchain failure too -- `TF-PLAN FAILED`, `MISSING ARTIFACT`, the
    # mock-STS `tf-plan-mock-sts-unavailable` bail-out -- and each of those is a
    # RUN-INVALIDATING condition that static_tiers.sh itself labels "NOT a bad
    # solution". Accepting those 0.0s would let this gate report "doing nothing
    # is rejected" on a run where nothing was ever graded, which is exactly the
    # vacuous pass the do-nothing catch exists to prevent (and it is not
    # hypothetical: a batch run on 2026-08-20 produced `TF-PLAN FAILED` on the
    # terraconstructs arm from mock-STS port contention between back-to-back
    # fixtures, while the same fixture run in isolation failed honestly on
    # `security-group-uses-the-new-team-prefixed-name`).
    #
    # So the tier-0 summary marker must be present: it is printed only after the
    # arm's toolchain actually produced a graded artifact and ran the asserts.
    # Fail-closed -- an unprovable claim fails rather than passes.
    graded = "tier0_pass=" in run.detail
    if run.ok and scored and not graded:
        run.detail = (
            "the do-nothing fixture scored < 1.0 but the arm's toolchain never "
            "produced a graded artifact (no tier-0 summary in its output), so "
            "this run proves NOTHING about whether the oracle rejects doing "
            "nothing -- static_tiers.sh writes 0.0 for a broken toolchain too. "
            "This is a run-invalidating infrastructure condition, not a "
            "verdict: fix the toolchain (or re-run -- mock-STS port contention "
            "between back-to-back fixtures is a known cause) and try again.\n"
            + run.detail
        )
    if run.ok and not scored:
        run.detail = (
            f"submitting the SEED UNCHANGED scored reward={run.reward} -- this "
            "scenario's change request is already satisfied by its own starting "
            "workspace, so it rewards doing nothing and measures nothing. Either "
            "the change request or the oracle must move.\n" + run.detail
        )
    run.ok = run.ok and scored and graded
    return [run]


def check_arm(spec: Spec, arm: Arm) -> list[RunResult]:
    task = task_dir(spec, arm)
    solve_sh = task / "solution" / "solve.sh"
    results: list[RunResult] = []

    # Multi-step: the task-root reference + every broken/ fixture are graded
    # against the FINAL step's oracle -- which spec_model guarantees is the
    # full tier suite, i.e. exactly what they were graded against before the
    # decomposition. `final_step` is None for a single-step spec, which makes
    # every _run_solve call below byte-identical to its pre-steps behaviour.
    final_step: Step | None = (spec.steps or [None])[-1] if spec.is_multi_step() else None

    if _is_stub(solve_sh):
        results.append(RunResult(f"{arm}/solution/solve.sh", None, True, "NOT_AUTHORED (Slice D pending)"))
        return results

    results.extend(_check_non_final_steps(spec, arm, task))
    results.extend(_check_seed_unchanged(spec, arm, task, final_step))

    # Tier-0.5-aware plumbing (SCHEMA.md §4.4, DECISIONS.md "Tier-0.5 runs
    # host-side, non-gating"): a catch whose predicted_tier_caught is "0.5"
    # for THIS arm (the anti-L2 falsifiability instrument, prereg §5/H2) is
    # by construction invisible to every static tier that feeds
    # reward.txt -- that invisibility IS the catch. Its broken/ fixture is
    # therefore EXPECTED to score reward 1.0 (not 0.0 like every other
    # tier), and is only genuinely falsified by proving Tier 0.5 itself
    # (oracles.lib.tier05_jsonata.run_tier05) catches it against the SAME
    # artifact this sandboxed run produced.
    tier05_spec = spec.oracle.tier05_jsonata.model_dump(mode="json") if spec.oracle.tier05_jsonata else None
    artifact_rel = getattr(spec.instruction.per_arm, arm).output_contract.artifact_path

    good = _run_solve(
        task, arm, solve_sh, f"{arm}/solution/solve.sh",
        tier05_spec=tier05_spec, artifact_rel=artifact_rel, step=final_step,
    )
    good.ok = good.ok and good.reward == 1.0
    if tier05_spec is not None:
        # The REFERENCE solution's own embedded expressions must genuinely
        # be correct too, not just structurally clean -- a good.reward==1.0
        # that turns out tier05_ok==False would mean this spec's own
        # solve.sh has a real JSONata bug the static tiers can't see either.
        good.ok = good.ok and good.tier05_ok is True
    if good.mirror_ok is False:
        # A reward of 1.0 on the HOST doesn't mean this solution is really
        # achievable inside the arm's own offline image -- see
        # _check_mirror_coverage.
        good.ok = False
    results.append(good)

    catch_names = {catch.name for catch in spec.catches}
    for catch in spec.catches:
        # Slice G addition (apigw-redeploy, 2026-08-06): a catch whose
        # `applies_to` (spec_model.Catch, default all 3 arms -- 100%
        # backward compatible) excludes THIS arm names a mistake that is
        # structurally impossible to reproduce here (e.g. a hand-omitted TF
        # `triggers` block has no direct L2 equivalent -- the L2 always
        # computes one). No broken/ fixture is required or expected; this is
        # reported N/A (non-gating), not MISSING.
        if arm not in catch.applies_to:
            results.append(RunResult(
                f"{arm}/solution/broken/{catch.name}/solve.sh", None, True,
                f"N/A -- catch {catch.name!r} does not apply to arm {arm!r} "
                "(spec_model.Catch.applies_to)",
            ))
            continue
        broken_solve = task / "solution" / "broken" / catch.name / "solve.sh"
        label = f"{arm}/solution/broken/{catch.name}/solve.sh"
        if not broken_solve.exists():
            results.append(RunResult(label, None, False, "MISSING -- every catch needs a broken/ fixture once solve.sh is authored"))
            continue
        tier = predicted_tier(catch, arm)
        if tier == "live":
            # Slice G addition: a catch whose mistake is invisible to EVERY
            # static tier by construction (docs/apigw-redeploy-mechanics.md
            # §6(c) -- only a live apply->modify->re-apply->curl loop
            # discriminates it). Mirrors the "0.5" branch immediately below
            # in SHAPE (reward is EXPECTED to stay 1.0 -- that invisibility
            # IS the catch), but the falsifying evidence is a fixed marker
            # string this fixture's own OFFLINE run prints after
            # mechanically confirming the static-indistinguishability
            # property itself (e.g. two-plan triggers-hash diff showing no
            # change) -- LIVE_ONLY_CONFIRMED_MARKER, not a second static-
            # tool invocation (there is no static tool for this tier by
            # definition). This keeps `make ci`/`make falsifiability` fully
            # offline -- no AWS credentials or network needed -- while still
            # requiring the fixture to MECHANICALLY demonstrate (not just
            # claim in a comment) that it reproduces the documented gap.
            bad = _run_solve(
                task, arm, broken_solve, label,
                artifact_rel=artifact_rel, step=final_step,
            )
            bad.ok = bad.ok and bad.reward == 1.0 and LIVE_ONLY_CONFIRMED_MARKER in bad.detail
            if bad.reward == 1.0 and LIVE_ONLY_CONFIRMED_MARKER not in bad.detail:
                bad.detail = (
                    f"predicted_tier_caught={tier!r} (live-only) but this fixture's "
                    f"stdout never printed {LIVE_ONLY_CONFIRMED_MARKER!r} -- a "
                    "live-only catch's offline run must mechanically confirm the "
                    "static-indistinguishability property it claims, not just "
                    "assert it in a comment\n" + bad.detail
                )
        elif tier == "0.5":
            bad = _run_solve(
                task, arm, broken_solve, label,
                tier05_spec=tier05_spec, artifact_rel=artifact_rel, step=final_step,
            )
            # Falsified two ways at once, both required: (a) reward stays
            # 1.0 -- proving the static tiers genuinely cannot see this
            # catch, the parity claim itself; (b) tier05_ok is False --
            # proving Tier 0.5 genuinely DOES catch it. Either alone is not
            # enough: reward==1.0 with no tier05 check at all would just be
            # an unfalsified catch again (this is exactly the "reward is
            # constant 1.0, nothing proves grading" F2-shaped gap, applied
            # to the one tier reward.txt can never cover by design).
            bad.ok = bad.ok and bad.reward == 1.0 and bad.tier05_ok is False
        else:
            bad = _run_solve(
                task, arm, broken_solve, label,
                artifact_rel=artifact_rel, step=final_step,
            )
            observed = observed_tier(bad.detail)
            # Mechanical backstop for `predicted_tier_caught` (benchmark-
            # integrity review finding "gates/oracle_falsifiability.py --
            # predicted_tier_caught is never verified"): reward==0.0 alone
            # only proves SOMETHING caught the violation, never that it was
            # caught at the TIER the spec records (and the per-catch tier-
            # attribution table's headline H1/H2 comparison depends on that
            # tier being right, not just on reward being 0). A catch
            # recorded "1" that a real run actually catches at "0" (a
            # stronger, earlier catch) or vice versa now fails this gate
            # instead of passing silently.
            bad.ok = bad.ok and bad.reward == 0.0 and observed == tier
            if bad.reward == 0.0 and observed != tier:
                bad.detail = (
                    f"predicted_tier_caught={tier!r} but observed_tier={observed!r} "
                    f"from this run's own static_tiers.sh output (reward 0.0 either "
                    f"way -- this is a tier-attribution mismatch, not a grading miss)\n"
                    + bad.detail
                )
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
            # The brownfield do-nothing fixture already ran, under its own
            # dedicated, differently-worded check (_check_seed_unchanged above:
            # required verdict `< 1.0`, missing = FAIL). Running it a second
            # time here would double the slowest step in this gate and report
            # the same fact under a vaguer label.
            if spec.workspace_seed is not None and extra_dir.name == SEED_UNCHANGED_FIXTURE:
                continue
            extra_solve = extra_dir / "solve.sh"
            label = f"{arm}/solution/broken/{extra_dir.name}/solve.sh"
            if not extra_solve.exists():
                results.append(RunResult(label, None, False, "directory present but solve.sh missing"))
                continue
            bad = _run_solve(task, arm, extra_solve, label, step=final_step)
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
            tier05_note = f" tier05_ok={r.tier05_ok}" if r.tier05_ok is not None else ""
            last_line = r.detail.splitlines()[-1] if r.detail else ""
            print(f"[{status}] {r.label}: reward={r.reward}{tier05_note} -- {last_line}")
            if not r.ok and "tier-attribution mismatch" in r.detail:
                print(f"    {r.detail.splitlines()[0]}")
            if not r.ok and r.tier05_detail:
                print(f"    tier05_detail: {r.tier05_detail}")
            if r.mirror_ok is False:
                print(f"    mirror_detail: {r.mirror_detail}")
            if not r.ok:
                all_ok = False

    if all_ok:
        print(f"\nfalsifiability OK for {spec.id!r}")
        return 0
    print(f"\nfalsifiability FAILED for {spec.id!r}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))
