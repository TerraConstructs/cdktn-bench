"""Falsifiability gate: proves a scenario's oracle can tell good from bad.

A generated `tests/static_tiers.sh` proves nothing about a scenario's
discriminating power until it is shown to (a) accept a genuinely correct
solution AND (b) reject at least one genuinely bad one *per declared catch* --
otherwise a reward of 1.0 could just mean "the oracle never fails".

Exit 0 iff, for every enabled arm, `solution/solve.sh` is authored (not a
generator stub) and scores reward 1.0, and every `spec.catches[].name` has a
`solution/broken/<name>/solve.sh` scoring reward 0.0. A still-stubbed solve.sh
is reported NOT_AUTHORED rather than FAIL -- the one non-gating exception;
once it is authored, missing broken/ coverage for any catch is a hard FAIL.

Usage:
    uv run python gates/oracle_falsifiability.py specs/_toy/toy-ssm-parameter.yaml
    make falsifiability SPEC=specs/_toy/toy-ssm-parameter.yaml

Multi-step oracles, per-tier fixture handling and AWS access:
docs/gates.md#oracle-falsifiability
"""

from __future__ import annotations

import argparse
import contextlib
import json
import re
import shutil
import subprocess
import sys
import tempfile
from collections.abc import Iterator
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

sys.path.insert(0, str(Path(__file__).resolve().parent))
import tf_registry  # noqa: E402
from aws_stub import running_stub  # noqa: E402

REPO_ROOT = Path(__file__).resolve().parent.parent

# The only arm whose toolchain needs more than the AWS stub: its modules resolve
# from the loopback registry, never from registry.terraform.io.
REGISTRY_ARM: Arm = "hcl_modules"


@contextlib.contextmanager
def arm_env(arm: Arm, env: dict[str, str]) -> Iterator[dict[str, str]]:
    """`env` for one arm's fixture runs; unchanged for every arm but this one.

    `hcl_modules` additionally runs under gates/tf_registry.py::running_registry,
    which adds the `TF_CLI_CONFIG_FILE` whose `host` override points
    `registry.terraform.io`'s modules service at the loopback responder. Without
    it this arm's `terraform init` resolves its modules from the PUBLIC
    registry, so the gate would grade a solution the arm's own offline image
    cannot build. Other arms declare no modules, so handing them that config
    would only couple three green arms to a fourth arm's subprocess.

    Lives here rather than in gates/artifact_collector.py, which imports this
    module: both gates need it, and one definition is what keeps them running
    their fixtures in the same environment.
    """
    if arm != REGISTRY_ARM:
        yield env
        return
    with tf_registry.running_registry(env=env) as registry_env:
        yield registry_env

# The fixed marker string a `predicted_tier_caught: "live"` broken/ fixture's
# gate run must print, after mechanically confirming the static-
# indistinguishability property that is this catch's whole point (see
# check_arm()'s "live" branch). Shared here, not duplicated per fixture, so the
# gate and every fixture agree on the exact string.
LIVE_ONLY_CONFIRMED_MARKER = "CDKTN_BENCH_LIVE_ONLY_CONFIRMED"

# The catch tiers no host-side gate can run, and which therefore share one
# verdict rule: "live" (only a real AWS call discriminates the mistake) and
# "teardown" (only the generator-injected destroy does -- specs/SCHEMA.md §5.2,
# DECISIONS.md Amendment 41). Both expect the fixture to keep static reward 1.0
# and to earn LIVE_ONLY_CONFIRMED_MARKER mechanically.
LIVE_FAMILY_TIERS = ("live", "teardown")

_MIRROR_CACHE: dict[str, dict[str, set[str]] | None] = {}


def _arm_mirror_provider_versions(arm: Arm) -> dict[str, set[str]] | None:
    """`{full_name: {version, ...}}` baked into `cdktn-bench/<arm>:dev`'s own
    `/opt/terraform-plugin-mirror`, extracted via `docker cp` and read from the
    mirror's `<namespace>/<type>/index.json` files (the format `terraform
    providers mirror` writes and the arm's `filesystem_mirror` block reads --
    see arms/*/environment/terraformrc).

    Read from the image rather than by running `terraform init` against a
    host-side copy: the mirror only contains packages for the image's own build
    platform (linux_arm64), never the host's (darwin_arm64), so a host init
    cannot resolve from it at all. Returns `None` for `awscdk` (no terraform
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
    """Every provider `configuration.provider_config` in a synthesized artifact
    must be present in THIS arm image's own offline mirror
    (`_arm_mirror_provider_versions`), matched by `full_name` plus a literal,
    pinned `version_constraint`. A range constraint pins no single version to
    check and is skipped, not silently treated as covered.

    A solution that synthesizes and plans successfully on the HOST (which
    resolves providers from the public registry) can still be unrunnable inside
    the arm's `--network none` image if a required provider was never mirrored
    there (arms/terraconstructs/environment/mirror-src/main.tf is where they
    are declared). Returns `(True, "")` when mirror checking is unavailable --
    image not built, separately reported as a louder warning -- rather than
    failing every run for an unrelated reason."""
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


# `== summary: tier0_pass=N tier1_status=X ==` -- the generated verifier's own
# literal format, matched to recover an OBSERVED tier from a run's stdout (see
# observed_tier() below). Anchored to a WHOLE line, because the same stdout
# carries tier-0 log lines and tier-1 `DENY:` messages quoting the artifact's
# own addresses, and an unanchored match would read a forged verdict out of one.
_SUMMARY_RE = re.compile(
    r"^== summary: tier0_pass=(\d) tier1_status=(\S+) ==\r?$", re.MULTILINE
)
# A toolchain step (build/synth/plan/validate/init) that fails before tier-0
# asserts run prints "<LABEL> FAILED" and writes reward 0.0 immediately
# (generator/gen.py's toolchain_block). That is tier-"0"-equivalent: caught by
# the compiler/synthesizer itself, the bucket predicted_tier_caught's "0"
# denotes.
_TOOLCHAIN_FAILED_RE = re.compile(r"^[A-Z][A-Z0-9_ ]* FAILED$", re.MULTILINE)


def observed_tier(stdout: str) -> str | None:
    """Recover, from a run's stdout, the tier its `tests/static_tiers.sh`
    actually caught a violation at -- the mechanical backstop for
    `predicted_tier_caught`. Returns `"0"`, `"1"`, or `None` (never caught by
    any static tier: the expected outcome for a "live"- or "teardown"-predicted
    catch, and a mismatch for anything else)."""
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


def apply_live_family_verdict(bad: RunResult, tier: str) -> RunResult:
    """Grade one broken fixture whose catch names a tier this gate cannot run.

    Two such tiers exist and they share this verdict exactly: "live", where the
    mistake is discriminated only by a real AWS call the hand-authored
    tests/live_check.py makes, and "teardown", where it is discriminated only
    by the generator-injected destroy (specs/SCHEMA.md §5.2). In neither case
    may the gate claim a static tier caught the fixture, so the expected static
    reward is 1.0 -- the same one a correct solution earns -- and the falsifying
    evidence is LIVE_ONLY_CONFIRMED_MARKER, printed by the fixture only after it
    mechanically confirms the indistinguishability it claims.

    Mutates and returns `bad`, so the caller's list holds one row per fixture.
    """
    bad.ok = bad.ok and bad.reward == 1.0 and LIVE_ONLY_CONFIRMED_MARKER in bad.detail
    if bad.reward == 1.0 and LIVE_ONLY_CONFIRMED_MARKER not in bad.detail:
        bad.detail = (
            f"predicted_tier_caught={tier!r} (no static tier can see it) but this "
            f"fixture's stdout never printed {LIVE_ONLY_CONFIRMED_MARKER!r} -- such "
            "a catch's gate run must mechanically confirm the "
            "static-indistinguishability property it claims, not just assert it "
            "in a comment\n" + bad.detail
        )
    return bad


def predicted_tier(catch: Catch, arm: Arm) -> str:
    """`catches[].predicted_tier_caught` for one arm (specs/SCHEMA.md §3,
    catches): `.awscdk` for awscdk; `.hcl` for hcl_raw AND terraconstructs UNLESS
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
    # Populated whenever this run produced an artifact on a terraform-shaped
    # arm (every arm but awscdk) -- False means this artifact requires a
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
    artifact_rel: str | None = None,
    step: Step | None = None,
    env: dict[str, str] | None = None,
) -> RunResult:
    """Copy `task`'s `environment/<ARM_WORKSPACE_SUBDIR[arm]>` (the exact tree
    the arm's own Dockerfile COPYs into WORKDIR /app/project -- flattened, no
    'workspace'/'app' prefix: `workspace/` for awscdk/hcl_raw, `app/` for
    terraconstructs) into the SANDBOX ROOT, run `solve_sh` there with cwd=that
    scratch dir, and read back /logs/verifier/reward.txt. Runs entirely on the
    host using whatever toolchain is on PATH (terraform/opa/node/npm).

    The flattening is load-bearing, and shared with
    generator/check_reference_paths.py::_prepare_project. The generated
    `tests/static_tiers.sh` (patched below to run against this sandbox) does
    `cd /app/project` and reads `main.tf`/`cdk.out/...` directly at that root;
    copying the whole `environment/` dir instead lands the entry_file one level
    too deep, so `terraform init`/`cdk synth` run against an empty directory and
    every solve.sh, however correct, can only fail. Enforced by
    gates/tests/test_oracle_falsifiability.py, which runs this function against
    a known-good solve.sh and asserts reward 1.0.

    `env`: the credential-free AWS environment every toolchain subprocess below
    runs under (gates/aws_stub.py::running_stub()). Live AWS is the only trial
    mode (aws-access.html, DECISIONS.md Amendment 32), so the generated
    toolchain always makes STS calls regardless of whether this scenario needs
    them -- there is no offline-fixture branch to fall back to. Defaults to
    `None`, in which case THIS call starts and tears down its own one-off stub
    (correct but wasteful for a caller running many solve.sh in a row);
    `check_arm` hoists one shared `env` per arm, and each gate's `main()`
    hoists further, to ONE stub per gate process."""
    if env is None:
        with running_stub() as stub_env:
            return _run_solve(
                task, arm, solve_sh, label,
                artifact_rel=artifact_rel, step=step,
                env=stub_env,
            )
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
        # `steps/<n>/solution/solve.sh` still resolves, and a step solution can
        # reach the root one (steps/01's reference solution is a thin STEP=01
        # wrapper around it, by design).
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
                env=env,
                check=True,
                capture_output=True,
                text=True,
            )
        rel_solve = solve_sh.relative_to(task)
        reward_file = logs / "reward.txt"
        # tests/static_tiers.sh bakes in the absolute /logs/verifier and
        # /app/project paths it really runs under inside a trial's container;
        # repoint them at this scratch sandbox. Every solve.sh ends by running
        # that one script, so patching it is enough to make the whole chain
        # self-contained on the host.
        static_tiers = project / "tests" / "static_tiers.sh"
        if static_tiers.exists():
            text = static_tiers.read_text()
            text = text.replace("/logs/verifier", str(logs))
            text = text.replace("/app/project", str(project))
            static_tiers.write_text(text)
        proc = subprocess.run(
            ["bash", str(project / rel_solve)],
            cwd=project,
            env=env,
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

        # Terraform-shaped arms only: a solution reaching reward 1.0 on the
        # HOST (public registry) but requiring a provider absent from the arm
        # image's offline mirror is not achievable inside a real trial's
        # `--network none` container. Folded into `.ok` by check_arm rather than
        # trusting a host-side 1.0. See _check_mirror_coverage.
        mirror_ok: bool | None = None
        mirror_detail = ""
        if arm != "awscdk" and document is not None:
            mirror_ok, mirror_detail = _check_mirror_coverage(document, arm)

        # Full stdout (not truncated) -- observed_tier() must see the
        # "== summary: tier0_pass=... ==" / "<LABEL> FAILED" lines
        # regardless of how much tier-0 assert-check chatter precedes them;
        # main() truncates for display only.
        return RunResult(
            label, reward, True, proc.stdout,
            mirror_ok=mirror_ok, mirror_detail=mirror_detail,
        )


def _check_non_final_steps(
    spec: Spec, arm: Arm, task: Path, env: dict[str, str] | None = None
) -> list[RunResult]:
    """Every NON-final step needs its own reference solution scoring 1.0.

    Nothing else in the repo shows that an intermediate step's oracle is
    SATISFIABLE, and an unsatisfiable step-01 oracle would abort every trial at
    the `min_reward` hard gate before step 02's prompt is ever delivered --
    silently, since Harbor records a step abort on the StepResult and not on
    the trial (multi-step trials, DECISIONS.md Amendment 26).

    The FINAL step is deliberately absent here: its reference is the task-root
    `solution/solve.sh`, checked by `check_arm` under its original label so
    `gates/grading_proof.py`'s row lookups keep working.
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
        run = _run_solve(task, arm, step_solve, label, artifact_rel=artifact_rel, step=step, env=env)
        run.ok = run.ok and run.reward == 1.0
        if run.mirror_ok is False:
            run.ok = False
        results.append(run)
    return results


def _check_seed_unchanged(
    spec: Spec, arm: Arm, task: Path, step: Step | None, env: dict[str, str] | None = None
) -> list[RunResult]:
    """THE MANDATORY BROWNFIELD DO-NOTHING CATCH (specs/SCHEMA.md §2.7
    `workspace_seed`; brownfield scenarios, DECISIONS.md Amendment 28).

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

    `< 1.0` rather than `== 0.0` on purpose: the claim being falsified is
    "doing nothing does not earn full marks", and pinning an exact 0.0 would
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
    run = _run_solve(task, arm, solve, label, artifact_rel=artifact_rel, step=step, env=env)
    scored = run.reward is not None and run.reward < 1.0
    # A reward below 1.0 is necessary but NOT sufficient: static_tiers.sh writes
    # 0.0 for run-invalidating toolchain failures too (`TF-PLAN FAILED`,
    # `MISSING ARTIFACT`, the `aws-unavailable` preflight bail-out), so the
    # tier-0 summary marker -- printed only once a graded artifact exists and
    # the asserts ran -- must also be present. Fail-closed.
    graded = "tier0_pass=" in run.detail
    if run.ok and scored and not graded:
        run.detail = (
            "the do-nothing fixture scored < 1.0 but the arm's toolchain never "
            "produced a graded artifact (no tier-0 summary in its output), so "
            "this run proves NOTHING about whether the oracle rejects doing "
            "nothing -- static_tiers.sh writes 0.0 for a broken toolchain too. "
            "This is a run-invalidating infrastructure condition, not a "
            "verdict: fix the toolchain (or re-run) and try again.\n"
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


def check_arm(spec: Spec, arm: Arm, env: dict[str, str] | None = None) -> list[RunResult]:
    """`env`: the credential-free AWS environment (gates/aws_stub.py::
    running_stub()) every `_run_solve` call below shares. Defaults to
    `None`, in which case this call starts and tears down ONE stub for its
    own whole run (every solve.sh this one `check_arm` call executes shares
    it) -- correct for a standalone call (e.g. this module's own tests) but
    still one stub per arm; a gate's `main()` hoists a single shared `env`
    across every enabled arm, for one stub per gate process."""
    if env is None:
        with running_stub() as stub_env, arm_env(arm, stub_env) as run_env:
            return check_arm(spec, arm, env=run_env)
    task = task_dir(spec, arm)
    solve_sh = task / "solution" / "solve.sh"
    results: list[RunResult] = []

    # Multi-step: the task-root reference and every broken/ fixture are graded
    # against the FINAL step's oracle, which spec_model guarantees is the full
    # tier suite. `final_step` is None for a single-step spec, which keeps every
    # _run_solve call below on its single-step path.
    final_step: Step | None = (spec.steps or [None])[-1] if spec.is_multi_step() else None

    if _is_stub(solve_sh):
        results.append(RunResult(f"{arm}/solution/solve.sh", None, True, "NOT_AUTHORED (solve.sh still a generator stub)"))
        return results

    results.extend(_check_non_final_steps(spec, arm, task, env))
    results.extend(_check_seed_unchanged(spec, arm, task, final_step, env))

    artifact_rel = getattr(spec.instruction.per_arm, arm).output_contract.artifact_path

    good = _run_solve(
        task, arm, solve_sh, f"{arm}/solution/solve.sh",
        artifact_rel=artifact_rel, step=final_step, env=env,
    )
    good.ok = good.ok and good.reward == 1.0
    if good.mirror_ok is False:
        # A reward of 1.0 on the HOST doesn't mean this solution is really
        # achievable inside the arm's own offline image -- see
        # _check_mirror_coverage.
        good.ok = False
    results.append(good)

    catch_names = {catch.name for catch in spec.catches}
    for catch in spec.catches:
        # A catch whose `applies_to` (spec_model.Catch, default all three
        # arms) excludes THIS arm names a mistake structurally impossible to
        # reproduce here -- e.g. a hand-omitted TF `triggers` block has no L2
        # equivalent, the L2 always computes one. No broken/ fixture is
        # required; reported N/A (non-gating), not MISSING.
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
        if tier in LIVE_FAMILY_TIERS:
            bad = apply_live_family_verdict(
                _run_solve(
                    task, arm, broken_solve, label,
                    artifact_rel=artifact_rel, step=final_step, env=env,
                ),
                tier,
            )
        else:
            bad = _run_solve(
                task, arm, broken_solve, label,
                artifact_rel=artifact_rel, step=final_step, env=env,
            )
            observed = observed_tier(bad.detail)
            # Mechanical backstop for `predicted_tier_caught`: reward==0.0
            # alone proves only that SOMETHING caught the violation, never that
            # it was caught at the TIER the spec records -- which the per-catch
            # tier-attribution table depends on. A recorded "1" that a real run
            # catches at "0", or vice versa, fails here instead of passing.
            bad.ok = bad.ok and bad.reward == 0.0 and observed == tier
            if bad.reward == 0.0 and observed != tier:
                bad.detail = (
                    f"predicted_tier_caught={tier!r} but observed_tier={observed!r} "
                    f"from this run's own static_tiers.sh output (reward 0.0 either "
                    f"way -- this is a tier-attribution mismatch, not a grading miss)\n"
                    + bad.detail
                )
        results.append(bad)

    # ALTERNATE REFERENCES: a directory under solution/ that is neither the
    # reference nor broken/. Each is a SECOND correct solution, kept because a
    # shape the oracle must accept is not obvious from the one reference --
    # the hcl_modules arm's "the module's own defaults already satisfy this,
    # so the call need not restate it" case. Required to score 1.0, for the
    # same reason the extra negatives below are required to score 0.0: a
    # claim about grading that no gate runs is a comment, not a proof.
    for alt_dir in sorted(p for p in (task / "solution").iterdir() if p.is_dir()):
        if alt_dir.name == "broken":
            continue
        alt_solve = alt_dir / "solve.sh"
        label = f"{arm}/solution/{alt_dir.name}/solve.sh"
        if not alt_solve.exists():
            results.append(RunResult(label, None, False, "directory present but solve.sh missing"))
            continue
        alt = _run_solve(
            task, arm, alt_solve, label,
            artifact_rel=artifact_rel, step=final_step, env=env,
        )
        alt.ok = alt.ok and alt.reward == 1.0
        results.append(alt)

    # Extra, non-catch-named negative fixtures prove an alternate-but-equally-
    # idiomatic shape is caught too (aws_iam_policy +
    # aws_iam_role_policy_attachment on the TF arms, inlinePolicies on awscdk),
    # not just the ONE shape a catch name covers. Each is required to score 0.0
    # the same way, so re-narrowing the Rego bundle turns this red.
    broken_dir = task / "solution" / "broken"
    if broken_dir.is_dir():
        for extra_dir in sorted(broken_dir.iterdir()):
            if not extra_dir.is_dir() or extra_dir.name in catch_names:
                continue
            # The brownfield do-nothing fixture already ran under its own
            # dedicated check (_check_seed_unchanged: required verdict `< 1.0`,
            # missing = FAIL). Re-running it here would double the slowest step
            # in this gate and report the same fact under a vaguer label.
            if spec.workspace_seed is not None and extra_dir.name == SEED_UNCHANGED_FIXTURE:
                continue
            extra_solve = extra_dir / "solve.sh"
            label = f"{arm}/solution/broken/{extra_dir.name}/solve.sh"
            if not extra_solve.exists():
                results.append(RunResult(label, None, False, "directory present but solve.sh missing"))
                continue
            bad = _run_solve(task, arm, extra_solve, label, step=final_step, env=env)
            bad.ok = bad.ok and bad.reward == 0.0
            results.append(bad)

    return results


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("spec_path", type=Path)
    args = parser.parse_args(argv[1:])

    spec = load_spec(args.spec_path)
    all_ok = True
    # ONE stub for the whole gate process, not one per arm or per solve.sh.
    with running_stub() as env:
        for arm in spec.arms.enabled_arms():
            # One registry responder per ARM, inside the one stub per process:
            # every fixture of this arm shares it, and no other arm pays for it.
            with arm_env(arm, env) as run_env:
                results = check_arm(spec, arm, run_env)
            for r in results:
                status = "PASS" if r.ok else "FAIL"
                last_line = r.detail.splitlines()[-1] if r.detail else ""
                print(f"[{status}] {r.label}: reward={r.reward} -- {last_line}")
                if not r.ok and "tier-attribution mismatch" in r.detail:
                    print(f"    {r.detail.splitlines()[0]}")
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
