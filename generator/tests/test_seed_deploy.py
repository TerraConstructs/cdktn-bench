"""generator/tests/test_seed_deploy.py -- the BROWNFIELD SEED DEPLOY contract
(specs/SCHEMA.md §2.7.1, docs/design/single-step-seed-deploy.md,
DECISIONS.md Amendment 31 -- the design doc calls it 29; 29 and 30 were
already taken).

`workspace_seed.premise` told the agent its workspace "is already deployed in
this account" and nothing deployed it. On a REPLACEMENT trap that is not a
cosmetic gap: `tests/live_check.py`'s discriminating assertion ("fail if the
OLD security group survives") is satisfied VACUOUSLY on an empty account, so
the live oracle reported `pass` while proving nothing, and three published rows
were voided (docs/brownfield-seed-not-deployed.md).

So the single most important test in this file is
`test_the_vacuity_case_is_caught_mechanically`: the seed's own live assert,
compiled and executed exactly as a real trial executes it, must FAIL against an
empty account. Everything else here exists to make sure that assert is emitted,
is reachable, and cannot be dropped by accident.

Three kinds of test, deliberately in one file because they are one contract:

  1. **Emission**, read off the REAL generated task dirs and off the emitters.
  2. **Validators** -- one test per hard error, each from a one-line spec
     mutation of the real spec, so they stay valid as the schema evolves (the
     same discipline test_multistep_emission.py's `_spec_with_deploy_prior`
     uses).
  3. **Execution**, running the emitted `assert_check` calls in a real bash
     against checked-in AWS CLI response fixtures.

Offline and toolchain-free: no docker, no AWS, no npm. `bash` and `jq` are
assumed present -- the two tools the generated proof itself needs, and both are
already assumed by this repo's own agent-container baseline contract.
"""

from __future__ import annotations

import copy
import json
import os
import re
import shutil
import subprocess
import sys
import tomllib
from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import (  # noqa: E402
    ASSERT_LIB_SH,
    SEED_DEPLOY_RECEIPT_PATH,
    SEED_DEPLOY_REQUIRED_ENV_KEY,
    SEED_STATE_IDENTITY_JQ,
    SEED_STATE_PROOF,
    TASKS_DIR,
    assert_no_agent_user_for_seed_deploy,
    build_seed_pre_invoke_sh,
    build_seed_state_identity_block,
    build_task_toml,
    generate_arm,
    task_dir,
)
from jsonpath_jq import jsonpath_to_jq  # noqa: E402
from spec_model import Spec, load_spec  # noqa: E402

SPEC_PATH = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
FIXTURES = Path(__file__).resolve().parent / "fixtures" / "seed-deploy"
ARMS = ("awscdk", "hcl_raw", "terraconstructs")


@pytest.fixture(scope="module")
def spec() -> Spec:
    return load_spec(SPEC_PATH)


def _raw() -> dict:
    return copy.deepcopy(yaml.safe_load(SPEC_PATH.read_text()))


# ---------------------------------------------------------------------------
# 1. Emission -- read off the REAL generated task dirs
# ---------------------------------------------------------------------------


def test_every_arm_ships_an_executable_seed_deploy_script(spec: Spec) -> None:
    for arm in ARMS:
        script = task_dir(spec, arm) / "pre_invoke" / "pre_invoke.sh"
        assert script.is_file(), f"{arm}: no pre_invoke/pre_invoke.sh"
        # aws_bench/task/script_runner.py execs the entry script directly.
        assert script.stat().st_mode & 0o111, f"{arm}: pre_invoke.sh not executable"
        assert script.read_text().startswith("#!/usr/bin/env bash\n")


def test_assert_lib_has_one_owner_and_is_byte_identical(spec: Spec) -> None:
    """ONE owner (gen.py::ASSERT_LIB_SH), two destinations.

    A forked copy is exactly the drift surface that would let the seed proof
    and tier-0 disagree about what `set_eq` means -- with nothing to notice.
    """
    for arm in ARMS:
        root = task_dir(spec, arm)
        seed_lib = (root / "pre_invoke" / "_assert_lib.sh").read_bytes()
        tests_lib = (root / "tests" / "_assert_lib.sh").read_bytes()
        assert seed_lib == tests_lib, f"{arm}: seed/tests _assert_lib.sh diverged"
        assert seed_lib == ASSERT_LIB_SH.encode(), f"{arm}: neither matches gen.py"


def test_the_script_is_valid_bash(spec: Spec) -> None:
    """`bash -n` on the real emitted bytes. A generated proof that cannot parse
    fails the trial in _prepare with a syntax error instead of a verdict."""
    if shutil.which("bash") is None:  # pragma: no cover - bash is assumed
        pytest.skip("bash not on PATH")
    for arm in ARMS:
        script = task_dir(spec, arm) / "pre_invoke" / "pre_invoke.sh"
        proc = subprocess.run(["bash", "-n", str(script)], capture_output=True)
        assert proc.returncode == 0, f"{arm}: {proc.stderr.decode()}"


def test_the_script_carries_the_arms_own_deploy_command_verbatim(spec: Spec) -> None:
    """The generator never guesses, and never rewrites, a deploy command."""
    for arm in ARMS:
        declared = getattr(
            spec.instruction.per_arm, arm
        ).output_contract.deploy_command
        assert declared is not None
        # >- folded scalars arrive as one line; that is what runs.
        assert declared.strip() in build_seed_pre_invoke_sh(spec, arm)


def test_the_script_exports_a_region(spec: Spec) -> None:
    """Without it every `aws` call dies with exit 253 (`NoRegion`) BEFORE
    reaching AWS -- the measured bug that gated a correct, deployed, converged
    solution to reward 0.0 with an empty `failures` list."""
    for arm in ARMS:
        body = build_seed_pre_invoke_sh(spec, arm)
        assert ': "${AWS_DEFAULT_REGION:=us-east-1}"' in body
        assert "export AWS_DEFAULT_REGION" in body


def test_the_script_carries_its_arms_state_proof(spec: Spec) -> None:
    """Anti-vacuity LAYER 2, and it is genuinely per-arm: the three arms keep
    converged state in three different places."""
    wid = spec.workspace_identity()
    for arm in ARMS:
        expected = (
            SEED_STATE_PROOF[arm]
            .replace("__STATE_IDENTITY__", build_seed_state_identity_block(arm))
            .replace("__WORKSPACE_ID__", wid)
        )
        assert expected in build_seed_pre_invoke_sh(spec, arm)

    # And the specific paths, spelled out rather than inferred, because getting
    # one of them wrong is what cost the terraconstructs row its reward.
    assert "/app/project/terraform.tfstate" in build_seed_pre_invoke_sh(
        spec, "hcl_raw"
    )
    assert (
        f"/app/project/terraform.{wid}.tfstate"
        in build_seed_pre_invoke_sh(spec, "terraconstructs")
    )
    assert "cdktf.out" not in SEED_STATE_PROOF["terraconstructs"]
    assert "describe-stacks" in build_seed_pre_invoke_sh(spec, "awscdk")


def test_one_assert_check_per_declared_live_assert(spec: Spec) -> None:
    seed = spec.workspace_seed
    assert seed is not None and seed.deploy is not None
    for arm in ARMS:
        body = build_seed_pre_invoke_sh(spec, arm)
        # Command lines only -- the surrounding comments name the function too.
        calls = [
            line
            for line in body.splitlines()
            if line.startswith("assert_check ")
        ]
        assert len(calls) == len(seed.deploy.live_asserts)
        for a in seed.deploy.live_asserts:
            assert any(line.startswith(f"assert_check {a.name} ") for line in calls)
        # Each one three-valued (finding m4): rc 2 = could not resolve, rc 1 =
        # contradicted. Collapsing them made a malformed AWS response read as
        # "the account does not hold the seed".
        assert body.count("|| rc=$?") == len(seed.deploy.live_asserts)
        assert "unresolvable=$((unresolvable + 1))" in body


def test_placeholder_json_is_written_last_and_only_on_success(spec: Spec) -> None:
    """ScriptRunner checks the exit code (step 5) BEFORE it looks for the result
    file (step 6), so a failing seed must surface as ScriptExecutionError -- the
    error that names the real problem -- not ScriptResultFileNotFoundError."""
    for arm in ARMS:
        body = build_seed_pre_invoke_sh(spec, arm)
        assert body.count("/logs/pre_invoke/placeholder.json") == 1
        assert body.rstrip().endswith(
            "printf '{}\\n' > /logs/pre_invoke/placeholder.json"
        )
        # ...and every failure path writes the verdict first.
        assert 'jq -n --arg o "$1" --arg r "$2"' in body


def test_the_script_is_not_set_e(spec: Spec) -> None:
    """`set -e` would exit before `fail` could write seed-proof.json, and the
    operator would get an exit code and nothing else."""
    for arm in ARMS:
        body = build_seed_pre_invoke_sh(spec, arm)
        assert "set -uo pipefail" in body
        assert "set -euo pipefail" not in body


def test_task_toml_pins_the_pre_invoke_role_to_the_agents_own(spec: Spec) -> None:
    """A seed the harness can deploy must be a seed the agent can change.

    Unset, aws_bench/utils/aws_creds.py falls back to
    OrganizationAccountAccessRole -- BROADER than the agent's role, which can
    create resources the agent then cannot modify or delete. That is a harness
    privilege asymmetry wearing the costume of an agent failure, which is what
    DECISIONS.md Amendment 24 retired QADeployApplicationRole to avoid.
    """
    for arm in ARMS:
        cfg = tomllib.loads((task_dir(spec, arm) / "task.toml").read_text())
        assert (
            cfg["scenario"]["pre_invoke_role_name"]
            == cfg["scenario"]["agent_role_name"]
        )
        assert cfg["scenario"]["pre_invoke_role_name"] == "QALocalInvocationApplicationAdmin"


def test_task_toml_sizes_the_seed_deploy_budget(spec: Spec) -> None:
    """aws-bench's own default is 600.0 s, which a real apply plus an interface
    VPC endpoint reaching `available` exceeds. NOT scaled by
    --timeout-multiplier, so it has to be right in the file."""
    for arm in ARMS:
        cfg = tomllib.loads((task_dir(spec, arm) / "task.toml").read_text())
        assert cfg["pre_invoke"]["timeout_sec"] == 2400.0


def test_a_spec_without_deploy_emits_no_pre_invoke_and_no_toml_keys(
    spec: Spec, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """REMOVAL. Dropping `deploy` must take the whole mechanism with it.

    _prepare runs pre_invoke/pre_invoke.sh unconditionally for any task that
    HAS the file on disk, so a stale script left behind would keep deploying
    into a real account with nothing in any spec declaring it.
    """
    raw = _raw()
    raw["workspace_seed"].pop("deploy")
    # `deploy_command` now has no consumer at all, which is its own hard error
    # (see test_a_dangling_deploy_command_is_still_refused) -- drop it too, so
    # this test isolates the emission question.
    for arm in ARMS:
        raw["instruction"]["per_arm"][arm]["output_contract"].pop("deploy_command")
    greenfield_seed = Spec.model_validate(raw)

    toml = build_task_toml(greenfield_seed, "hcl_raw", "uuid-0")
    assert "pre_invoke_role_name" not in toml
    assert "[pre_invoke]" not in toml

    # And the directory is actively REMOVED, not merely not-created. Run the
    # real generate_arm against a COPY of the real (already seeded) task dir,
    # with gen.TASKS_DIR redirected -- task_dir() reads that module global at
    # call time, so this exercises the shipped code path without touching the
    # repo's own tasks/.
    import gen as gen_module

    root = tmp_path / "tasks"
    live = task_dir(spec, "hcl_raw")
    shutil.copytree(live, root / "anchor" / live.name)
    monkeypatch.setattr(gen_module, "TASKS_DIR", root)
    assert (task_dir(greenfield_seed, "hcl_raw") / "pre_invoke").is_dir()
    generate_arm(greenfield_seed, "hcl_raw")
    assert not (task_dir(greenfield_seed, "hcl_raw") / "pre_invoke").exists()


# ---------------------------------------------------------------------------
# 2. Validators -- one test per hard error, each a one-line spec mutation
# ---------------------------------------------------------------------------


def test_deploy_requires_a_deploy_command_on_every_enabled_arm() -> None:
    raw = _raw()
    raw["instruction"]["per_arm"]["hcl_raw"]["output_contract"].pop("deploy_command")
    with pytest.raises(ValueError, match="refuses to guess a real deploy"):
        Spec.model_validate(raw)


def test_deploy_requires_a_live_oracle() -> None:
    """A seed deployed into a real account with no live oracle is spend with no
    measurement.

    `gating`, `hand_authored` and the idempotence tier all have their OWN
    "requires live_check.enabled" rules that fire first, so they are turned off
    here too -- the mutation has to leave exactly one rule left to break, or the
    test proves nothing about this one.
    """
    raw = _raw()
    raw["verifier"]["live_check"].update(
        {"enabled": False, "gating": False, "hand_authored": False}
    )
    raw["verifier"]["idempotence"] = {"enabled": False, "gating": False}
    with pytest.raises(ValueError, match="spend with no measurement"):
        Spec.model_validate(raw)


def test_deploy_requires_mutating_concurrency() -> None:
    """aws_trial.py resets the scenario account only for ConcurrencyMode.MUTATING;
    without it the seed's own VPC/SG/endpoint outlive the trial."""
    raw = _raw()
    raw["verifier"]["live_check"]["concurrency_mode"] = "read-only"
    with pytest.raises(ValueError, match="contaminates it for every later"):
        Spec.model_validate(raw)


def test_a_seed_deploy_with_no_existence_proof_is_not_expressible() -> None:
    raw = _raw()
    raw["workspace_seed"]["deploy"]["live_asserts"] = []
    with pytest.raises(ValueError, match="live_asserts"):
        Spec.model_validate(raw)


def test_live_asserts_must_pin_a_catch() -> None:
    """Without the back-reference they drift into proving that SOMETHING got
    deployed rather than that the POISONED thing did."""
    raw = _raw()
    for a in raw["workspace_seed"]["deploy"]["live_asserts"]:
        a.pop("pins_catch", None)
    with pytest.raises(ValueError, match="at least one entry must set"):
        Spec.model_validate(raw)


def test_pins_catch_must_name_a_real_catch() -> None:
    raw = _raw()
    raw["workspace_seed"]["deploy"]["live_asserts"][0]["pins_catch"] = "no-such-catch"
    with pytest.raises(ValueError, match="names no declared catch"):
        Spec.model_validate(raw)


def test_a_brownfield_terraform_plan_must_not_refresh() -> None:
    """MEASURED: with state present the OFFLINE verifier's plan refreshes
    through provider.tf's dummy credentials and dies, scoring a PERFECT solution
    0.0."""
    raw = _raw()
    raw["instruction"]["per_arm"]["hcl_raw"]["output_contract"]["plan_command"] = (
        "terraform init && terraform plan -input=false -out=plan.tfplan && "
        "terraform show -json plan.tfplan > plan.json"
    )
    with pytest.raises(ValueError, match="-refresh=false"):
        Spec.model_validate(raw)


def test_the_refresh_rule_applies_to_every_brownfield_spec_not_only_deploying_ones() -> None:
    """A brownfield agent is asked to roll its own change out, so its own apply
    produces the same state file the seed would have."""
    raw = _raw()
    raw["workspace_seed"].pop("deploy")
    for arm in ARMS:
        raw["instruction"]["per_arm"][arm]["output_contract"].pop("deploy_command")
    raw["instruction"]["per_arm"]["hcl_raw"]["output_contract"]["plan_command"] = (
        "terraform init && terraform plan -out=plan.tfplan && "
        "terraform show -json plan.tfplan > plan.json"
    )
    with pytest.raises(ValueError, match="-refresh=false"):
        Spec.model_validate(raw)


def test_an_aws_token_may_not_be_a_leading_flag() -> None:
    raw = _raw()
    raw["workspace_seed"]["deploy"]["live_asserts"][0]["aws"] = [
        "--filters",
        "ec2",
    ]
    with pytest.raises(ValueError, match="must be the SERVICE name"):
        Spec.model_validate(raw)


@pytest.mark.parametrize("banned", ["--profile", "--region", "--endpoint-url", "--output"])
def test_harness_owned_aws_flags_are_rejected(banned: str) -> None:
    raw = _raw()
    raw["workspace_seed"]["deploy"]["live_asserts"][0]["aws"].append(banned)
    with pytest.raises(ValueError, match="harness-owned"):
        Spec.model_validate(raw)


def test_an_aws_token_may_not_carry_a_single_quote() -> None:
    """The generator emits each token single-quoted; nothing else is needed."""
    raw = _raw()
    raw["workspace_seed"]["deploy"]["live_asserts"][0]["aws"].append("Name='x'")
    with pytest.raises(ValueError, match="single quote"):
        Spec.model_validate(raw)


def test_an_op_that_needs_expected_must_have_one() -> None:
    raw = _raw()
    raw["workspace_seed"]["deploy"]["live_asserts"][0].pop("expected")
    with pytest.raises(ValueError, match="requires 'expected'"):
        Spec.model_validate(raw)


# ---------------------------------------------------------------------------
# 2b. The deploy_command consumer rule -- two legal consumers, never zero
# ---------------------------------------------------------------------------


def test_a_dangling_deploy_command_is_still_refused() -> None:
    """A stepless spec with a real deploy command and NO consumer for it."""
    raw = _raw()
    raw["workspace_seed"].pop("deploy")
    with pytest.raises(ValueError, match="nothing would ever run it"):
        Spec.model_validate(raw)


def test_workspace_seed_deploy_is_a_legal_consumer(spec: Spec) -> None:
    """The positive half of the same rule: this spec declares deploy_command on
    all three arms with no `steps:` at all, and validates."""
    assert spec.steps in (None, [])
    assert spec.workspace_seed is not None and spec.workspace_seed.deploy is not None
    for arm in ARMS:
        assert getattr(
            spec.instruction.per_arm, arm
        ).output_contract.deploy_command is not None


# ---------------------------------------------------------------------------
# 3. Execution -- the compiled asserts, run in a real bash against real AWS
#    CLI response shapes. THIS is the mechanical proof of the vacuity case.
# ---------------------------------------------------------------------------


def _run_assert_check(name: str, jq_filter: str, op: str, expected, artifact: Path) -> int:
    """Source the REAL generated _assert_lib.sh in a bare shell and run one
    assert exactly as the emitted pre_invoke.sh runs it.

    Bare on purpose: `pre_invoke.sh` sources this library with nothing else
    loaded, unlike `static_tiers.sh` which it was written as a companion to. If
    `assert_check` ever grows a dependency on something that script sets, this
    test is what catches it.
    """
    lib = REPO_ROOT / "generator" / "tests" / ".assert_lib_under_test.sh"
    lib.write_text(ASSERT_LIB_SH)
    try:
        script = (
            "set -uo pipefail\n"
            f". {lib}\n"
            f"assert_check {json.dumps(name)} {json.dumps(jq_filter)} "
            f"{json.dumps(op)} {json.dumps(json.dumps(expected))} {artifact}\n"
        )
        return subprocess.run(
            ["bash", "-c", script], capture_output=True
        ).returncode
    finally:
        lib.unlink(missing_ok=True)


def test_the_vacuity_case_is_caught_mechanically(spec: Spec) -> None:
    """THE test this whole mechanism exists for.

    `live_check.py`'s discriminating assertion is "NO security group named
    `internal-services-ssm-endpoint` remains". On an account where the seed was
    never deployed that is satisfied for free -- a `pass` that proves nothing,
    which is exactly what shipped and voided three rows.

    The seed's `old-group-is-live` assert is that assertion's exact negation, so
    it must PASS against a real seeded account and FAIL against an empty one.
    Compiled and executed here through the same jsonpath_jq translator and the
    same _assert_lib.sh a real trial uses.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    seed = spec.workspace_seed
    assert seed is not None and seed.deploy is not None
    a = next(x for x in seed.deploy.live_asserts if x.name == "old-group-is-live")
    jq_filter = jsonpath_to_jq(a.jsonpath)

    seeded = _run_assert_check(
        a.name, jq_filter, a.op, a.expected,
        FIXTURES / "describe-security-groups.json",
    )
    assert seeded == 0, "the seeded account must satisfy the live assert"

    # NOTE: `describe-security-groups-empty.json` is BOTH the empty-account
    # response AND the post-solution one -- the `aws` call this assert emits
    # filters on Name=group-name,Values=internal-services-ssm-endpoint, and a
    # solved account holds no group by that name.
    empty = _run_assert_check(
        a.name, jq_filter, a.op, a.expected,
        FIXTURES / "describe-security-groups-empty.json",
    )
    assert empty != 0, (
        "an EMPTY account must CONTRADICT the live assert -- otherwise the "
        "live oracle's own discriminating assertion is vacuous and the trial "
        "would be allowed to start (docs/brownfield-seed-not-deployed.md)"
    )

    # FINDING B, the OTHER direction. Two groups with the SAME name (legal:
    # EC2 group names are unique per-VPC, and this assert's `aws` call filters
    # account-wide on Name=group-name) must also contradict it. See
    # test_set_eq_collapses_duplicates_and_eq_cannot for the executed proof
    # that the op this used to use could NOT see that case.
    duplicated = _run_assert_check(
        a.name, jq_filter, a.op, a.expected,
        FIXTURES / "describe-security-groups-duplicate-vpcs.json",
    )
    assert duplicated != 0, (
        "an account holding TWO groups by this name must CONTRADICT the live "
        "assert -- one of them is a leftover the reset failed to remove, and "
        "the agent can only rename one of them. Left passing, live_check.py "
        "later sees the OTHER one's old name survive and scores a correct "
        "agent 0.0 (finding B)"
    )


@pytest.mark.parametrize(
    "fixture,expect_pass,why",
    [
        (
            "describe-vpc-endpoints.json",
            True,
            "the ARMED account -- one interface endpoint holding the OLD group",
        ),
        (
            "describe-vpc-endpoints-renamed-only.json",
            False,
            "THE M2 CASE. The endpoint holds only "
            "`platform-internal-services-ssm-endpoint`, i.e. the exact "
            "post-solution state in which the trap is DISARMED. This assert "
            "read `op: contains` until 2026-08-25, and on a STRING node "
            "assert_check's `contains` is jq's literal SUBSTRING test -- and "
            "the new name is a strict SUPERSTRING of the old one, so the one "
            "assert whose whole job is to prove the trap is ARMED passed "
            "against the state in which it is not",
        ),
        (
            "describe-vpc-endpoints-empty.json",
            False,
            "an account with no interface endpoint at all -- the seed never "
            "deployed",
        ),
        (
            "describe-vpc-endpoints-stray-extra-group.json",
            False,
            "FINDING m5. The seed's own endpoint is present and correct, but a "
            "SECOND interface endpoint (a leftover from an incompletely-reset "
            "earlier trial -- aws_trial.py::_reset_scenario_account logs a "
            "reset failure and never raises) holds a foreign group. Neither "
            "live assert can be scoped to this trial's VPC, so bounding the "
            "resolved set is what turns that into a loud, aborting FAIL "
            "instead of a silent pass",
        ),
        (
            "describe-vpc-endpoints-duplicate-vpcs.json",
            False,
            "FINDING B. The same leftover, wearing the SAME NAME -- two "
            "interface endpoints in two VPCs, each holding a group called "
            "`internal-services-ssm-endpoint`. `set_eq` runs `unique` before "
            "comparing, so this collapsed to one element and PASSED; `eq` "
            "requires EXACTLY ONE resolved node and cannot be collapsed. This "
            "is the case that scored a PERFECT agent 0.0: the proof passed, "
            "the agent renamed ITS group, and live_check.py then saw the "
            "leftover's old name survive and reported fail_stale",
        ),
    ],
)
def test_the_endpoint_attachment_assert_is_exact_not_substring(
    spec: Spec, fixture: str, expect_pass: bool, why: str
) -> None:
    """THE OTHER half of the vacuity proof, which had ZERO execution coverage
    until finding M2 (adversarial review, 2026-08-25).

    `old-group-is-live` proves the group exists. `endpoint-holds-the-old-group`
    is the one that proves the trap is ARMED -- the interface endpoint's ENI
    still holds that group, which is what makes EC2 refuse the destroy half of
    the rename. Before this test there was no describe-vpc-endpoints fixture in
    this directory at all, so the assert was pinned by a comment.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    seed = spec.workspace_seed
    assert seed is not None and seed.deploy is not None
    a = next(
        x for x in seed.deploy.live_asserts if x.name == "endpoint-holds-the-old-group"
    )
    rc = _run_assert_check(
        a.name, jsonpath_to_jq(a.jsonpath), a.op, a.expected, FIXTURES / fixture
    )
    if expect_pass:
        assert rc == 0, f"{fixture} should satisfy the assert: {why}"
    else:
        assert rc != 0, f"{fixture} must CONTRADICT the assert: {why}"


def test_the_old_substring_semantics_would_still_have_passed_the_m2_case() -> None:
    """The regression itself, kept executable.

    `contains` is unchanged -- it is SHARED with tier-0 and its substring
    behaviour on strings is deliberate there (see ASSERT_LIB_SH's own table).
    What changed is that a `SeedLiveAssert` may no longer rely on it for an
    exact-membership claim. This test pins WHY, so a future author who
    "simplifies" the spec back to `contains` sees the trap spelled out in a
    failing assertion rather than rediscovering it in a live run.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    jq_filter = jsonpath_to_jq("$.VpcEndpoints[*].Groups[*].GroupName")
    rc = _run_assert_check(
        "m2-regression",
        jq_filter,
        "contains",
        "internal-services-ssm-endpoint",
        FIXTURES / "describe-vpc-endpoints-renamed-only.json",
    )
    assert rc == 0, (
        "if this ever fails, ASSERT_LIB_SH's `contains` stopped being a "
        "substring test on strings and the M2 rationale needs rewriting"
    )
    # ...and no LIVE assert relies on it (structural_asserts legitimately do --
    # they read a synthesized template, which either has the node or does not).
    seed = load_spec(SPEC_PATH).workspace_seed
    assert seed is not None and seed.deploy is not None
    assert not [a for a in seed.deploy.live_asserts if a.op == "contains"]


@pytest.mark.parametrize(
    "fixture,jsonpath",
    [
        (
            "describe-security-groups-duplicate-vpcs.json",
            "$.SecurityGroups[*].GroupName",
        ),
        (
            "describe-vpc-endpoints-duplicate-vpcs.json",
            "$.VpcEndpoints[*].Groups[*].GroupName",
        ),
    ],
)
def test_set_eq_collapses_duplicates_and_eq_cannot(fixture: str, jsonpath: str) -> None:
    """FINDING B's premise, executed -- the justification for the rule, kept
    alive beside the rule (the discipline finding M1 established).

    `set_eq`'s compiled filter is `... | unique | sort` on both sides
    (gen.py::ASSERT_LIB_SH), so N nodes carrying the SAME value collapse to one
    element and compare EQUAL to a one-element `expected`. `eq` is
    `($v | length) == 1 and ($v[0] == $e)` -- it pins the COUNT as well as the
    value, so the multiplicity survives into the verdict.

    If the first assertion ever goes red, `set_eq` stopped running `unique` and
    finding B's rationale (and the spec comment that cites it) must be
    re-derived rather than trusted.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    jq_filter = jsonpath_to_jq(jsonpath)
    assert _run_assert_check(
        "b-regression", jq_filter, "set_eq",
        ["internal-services-ssm-endpoint"], FIXTURES / fixture,
    ) == 0, (
        "set_eq was expected to PASS on a duplicated-name account -- that is "
        "the whole reason both live asserts moved to `eq` (finding B)"
    )
    assert _run_assert_check(
        "b-fixed", jq_filter, "eq",
        "internal-services-ssm-endpoint", FIXTURES / fixture,
    ) == 1, (
        "`eq` must RESOLVE and be CONTRADICTED (rc 1, a verdict -- not rc 2) "
        "on a duplicated-name account"
    )


def test_every_shipped_live_assert_pins_the_count_it_expects(spec: Spec) -> None:
    """The positive half of finding B, on the REAL spec.

    Not a blanket ban on `set_eq` -- SCHEMA.md still allows it for a genuinely
    multi-valued claim. What this pins is that THIS spec's asserts, both of
    which describe a seed that places exactly ONE of a thing in an
    account-wide query, use the op that says so.
    """
    seed = spec.workspace_seed
    assert seed is not None and seed.deploy is not None
    for a in seed.deploy.live_asserts:
        assert a.op == "eq", (
            f"{a.name}: op={a.op!r}. Both of this spec's live asserts describe "
            "exactly one object in an account-wide `aws` query, so they must "
            "pin the count (finding B); `set_eq` runs `unique` and cannot"
        )


def test_every_live_assert_compiles_to_the_expected_jq(spec: Spec) -> None:
    """The compiled filter is baked into the shipped script, so a translator
    change that silently alters it must turn this red rather than change what
    the seed proof means."""
    seed = spec.workspace_seed
    assert seed is not None and seed.deploy is not None
    compiled = {a.name: jsonpath_to_jq(a.jsonpath) for a in seed.deploy.live_asserts}
    assert compiled == {
        "old-group-is-live": ".SecurityGroups | .[] | .GroupName",
        "endpoint-holds-the-old-group": ".VpcEndpoints | .[] | .Groups | .[] | .GroupName",
    }
    for arm in ARMS:
        body = build_seed_pre_invoke_sh(spec, arm)
        for jq_filter in compiled.values():
            assert f"'{jq_filter}'" in body


# ---------------------------------------------------------------------------
# 4. FALSIFIABILITY of the live proof itself (finding M1, adversarial review
#    2026-08-25). min_length=1 counts asserts; it does not make them capable of
#    failing. Three of SCHEMA.md §4.2's nine ops PASS on zero resolved nodes,
#    so a spec could declare a deploy whose ENTIRE live proof was satisfied by
#    a completely empty account -- exactly the inert configuration this
#    mechanism exists to make unexpressible.
# ---------------------------------------------------------------------------

_VACUOUS_OPS = ("not_exists", "absent_or_eq", "not_regex")


@pytest.mark.parametrize("op", _VACUOUS_OPS)
def test_the_rejected_ops_really_do_pass_on_an_empty_account(op: str) -> None:
    """The PREMISE of the rule, executed rather than asserted in a comment.

    If this ever goes red, `_VACUOUS_ON_AN_EMPTY_ACCOUNT` is guarding ops that
    no longer need guarding (or is missing one that does), and the rejection in
    spec_model must be re-derived rather than trusted.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    expected = None if op == "not_exists" else (
        "x" if op == "not_regex" else "anything"
    )
    rc = _run_assert_check(
        f"vacuity-{op}",
        jsonpath_to_jq("$.SecurityGroups[*].GroupName"),
        op,
        expected,
        FIXTURES / "describe-security-groups-empty.json",
    )
    assert rc == 0, (
        f"op={op!r} was expected to PASS on an empty account -- that is the "
        "whole reason SeedLiveAssert rejects it"
    )


@pytest.mark.parametrize("op", _VACUOUS_OPS)
def test_a_live_assert_that_cannot_fail_is_not_expressible(op: str) -> None:
    """One mutation, one rejected op. The load must RAISE."""
    raw = _raw()
    a = raw["workspace_seed"]["deploy"]["live_asserts"][0]
    a["op"] = op
    if op == "not_exists":
        a.pop("expected", None)
    else:
        a["expected"] = "internal-services-ssm-endpoint"
    with pytest.raises(ValueError, match="PASSES on zero resolved nodes"):
        Spec.model_validate(raw)


def test_a_deploy_whose_entire_live_proof_is_negative_is_not_expressible() -> None:
    """The finding's own worst case: EVERY live assert a negative op, so the
    whole anti-vacuity gate is satisfied by an empty account."""
    raw = _raw()
    for a in raw["workspace_seed"]["deploy"]["live_asserts"]:
        a["op"] = "not_exists"
        a.pop("expected", None)
    with pytest.raises(ValueError, match="PASSES on zero resolved nodes"):
        Spec.model_validate(raw)


def test_set_eq_with_an_empty_expected_is_rejected_for_the_same_reason() -> None:
    """`set_eq: []` is "the account holds none of these" -- true on []. Same
    vacuity, reached through an op that is otherwise legal."""
    raw = _raw()
    # Both shipped asserts moved to `eq` (finding B), so the set_eq rule now
    # needs the op set explicitly -- the rule is about the op/expected PAIR and
    # this mutation has to build that pair rather than inherit half of it.
    raw["workspace_seed"]["deploy"]["live_asserts"][0]["op"] = "set_eq"
    raw["workspace_seed"]["deploy"]["live_asserts"][0]["expected"] = []
    with pytest.raises(ValueError, match="EMPTY `expected`"):
        Spec.model_validate(raw)


def test_every_shipped_live_assert_uses_a_falsifiable_op(spec: Spec) -> None:
    """The positive half, on the REAL spec."""
    seed = spec.workspace_seed
    assert seed is not None and seed.deploy is not None
    for a in seed.deploy.live_asserts:
        assert a.op not in _VACUOUS_OPS
        if a.op == "set_eq":
            assert a.expected, f"{a.name}: set_eq with an empty expected"


# ---- 4b. FALSIFIABILITY, the PATH half (finding A, adversarial review round
#      3, 2026-08-25, REPRODUCED). Rejecting the three vacuous OPS did not make
#      the live proof falsifiable: SeedLiveAssert imposed no shape rule on
#      `jsonpath` at all, and a path that resolves to the CONTAINER rather than
#      descending INTO it hands even `exists` one node on an empty account. The
#      code comment and SCHEMA.md then asserted the stronger, still-false
#      property as fact -- which is finding M1's OWN shape, reintroduced by
#      M1's fix.


def test_a_container_path_really_does_pass_on_an_empty_account() -> None:
    """THE PREMISE of the path rule, executed -- the same discipline
    `test_the_rejected_ops_really_do_pass_on_an_empty_account` established for
    the op rule, so the rule cannot outlive its justification.

    `[ .SecurityGroups ]` over `{"SecurityGroups": []}` is `[[]]` -- length 1,
    and `assert_check`'s `map(select(. != null))` drops nulls, not empty
    arrays. So `exists` passes on a completely empty account.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc = _run_assert_check(
        "container-path",
        jsonpath_to_jq("$.SecurityGroups"),
        "exists",
        None,
        FIXTURES / "describe-security-groups-empty.json",
    )
    assert rc == 0, (
        "a container-naming jsonpath was expected to PASS on an empty account "
        "-- that is the whole reason SeedLiveAssert now requires the compiled "
        "filter to ITERATE a collection"
    )
    # ...and the descending form, which the rule leaves legal, resolves to ZERO
    # nodes on the same bytes. Both halves, or the rule proves nothing.
    assert _run_assert_check(
        "iterating-path",
        jsonpath_to_jq("$.SecurityGroups[*].GroupName"),
        "exists",
        None,
        FIXTURES / "describe-security-groups-empty.json",
    ) != 0


def test_a_container_path_live_assert_is_not_expressible() -> None:
    """One mutation: keep a falsifiable OP, use a container PATH. The load must
    RAISE -- before finding A this was accepted, emitted, and reported
    `seed_deployed` against an empty account."""
    raw = _raw()
    a = raw["workspace_seed"]["deploy"]["live_asserts"][0]
    a["jsonpath"] = "$.SecurityGroups"
    a["op"] = "exists"
    a.pop("expected", None)
    with pytest.raises(ValueError, match="never ITERATES a collection"):
        Spec.model_validate(raw)


def test_a_deploy_whose_entire_live_proof_names_containers_is_not_expressible() -> None:
    """The finding's worst case: EVERY live assert a container path, so the
    whole anti-vacuity gate passes on an empty account with three legal ops."""
    raw = _raw()
    for a in raw["workspace_seed"]["deploy"]["live_asserts"]:
        a["jsonpath"] = "$.SecurityGroups"
        a["op"] = "exists"
        a.pop("expected", None)
    with pytest.raises(ValueError, match="never ITERATES a collection"):
        Spec.model_validate(raw)


def test_recursive_descent_is_rejected_too_and_the_rule_says_so() -> None:
    """The NARROWING, made visible.

    `$..GroupName` compiles to `.. | objects | .GroupName?`, which iterates
    nothing, so the shape rule refuses it -- even though on this fixture it
    happens to resolve to zero nodes and would have been falsifiable. The rule
    is a conservative SHAPE test, not a decision procedure, and spec_model's
    comment and SCHEMA.md §2.7.1 both say exactly that. This test exists so
    that claim stays true rather than becoming the next thing a comment asserts
    and the code does not.
    """
    raw = _raw()
    a = raw["workspace_seed"]["deploy"]["live_asserts"][0]
    a["jsonpath"] = "$..GroupName"
    a["op"] = "exists"
    a.pop("expected", None)
    with pytest.raises(ValueError, match="never ITERATES a collection"):
        Spec.model_validate(raw)


def test_an_untranslatable_jsonpath_is_a_spec_error_not_a_generator_crash() -> None:
    """`$.Stacks[0].StackStatus` is NOT in generator/jsonpath_jq.py's grammar
    (there is no index segment). The compiled filter is baked into the emitted
    pre_invoke.sh, so the translator runs at generation time either way -- the
    only question is whether the author learns at `load_spec` or three commands
    later, from a traceback."""
    raw = _raw()
    raw["workspace_seed"]["deploy"]["live_asserts"][0]["jsonpath"] = (
        "$.Stacks[0].StackStatus"
    )
    with pytest.raises(ValueError, match="cannot be compiled"):
        Spec.model_validate(raw)


def test_every_shipped_live_assert_iterates_a_collection(spec: Spec) -> None:
    """The positive half, on the REAL spec."""
    seed = spec.workspace_seed
    assert seed is not None and seed.deploy is not None
    for a in seed.deploy.live_asserts:
        stages = [s.strip() for s in jsonpath_to_jq(a.jsonpath).split("|")]
        assert ".[]" in stages, f"{a.name}: {a.jsonpath} names a collection"


def test_gating_false_is_rejected_like_enabled_false() -> None:
    """Finding m1. `gating` is FALSE BY DEFAULT, so this is the "spend with no
    measurement" an author reaches by omission rather than by decision: the
    live oracle's verdict never reaches reward.txt without it."""
    raw = _raw()
    raw["verifier"]["live_check"]["gating"] = False
    with pytest.raises(ValueError, match="verifier.live_check.gating"):
        Spec.model_validate(raw)


# ---------------------------------------------------------------------------
# 5. FAIL CLOSED WHEN THE SCRIPT NEVER RAN (finding M3). aws_trial.py:303 is a
#    bare `if self.task.has_phase_script(ScriptType.PRE_INVOKE):` with no else
#    and no logging, and has_phase_script is pure file existence -- so a task
#    tree that lost pre_invoke/ skipped every anti-vacuity layer in silence.
# ---------------------------------------------------------------------------


def test_declaring_a_seed_deploy_and_shipping_one_are_the_same_thing() -> None:
    """THE BICONDITIONAL, over EVERY task dir in the repo.

    `[scenario].pre_invoke_role_name` is the task.toml half of the mechanism
    and `pre_invoke/pre_invoke.sh` is the on-disk half; aws-bench reads them
    from two different files and couples them nowhere. This is the repo-level
    gate that says they move together -- it runs under `make check`
    (mk/rails.mk's test-gates runs `pytest generator`), so a task tree that
    ships one without the other cannot stay green.

    NOTE the deliberate asymmetry: a task may carry pre_invoke/ for a
    `pre_invoke_random` placeholder instead (gen.py::generate_arm), which is a
    different mechanism with no seed and no role key. That form is recognised
    by the absence of the seed script's own generated header, not assumed away.
    """
    seen = 0
    for task in sorted(TASKS_DIR.glob("*/*/task.toml")):
        cfg = tomllib.loads(task.read_text())
        declares_role = "pre_invoke_role_name" in cfg.get("scenario", {})
        script = task.parent / "pre_invoke" / "pre_invoke.sh"
        is_seed_script = (
            script.is_file()
            and "build_seed_pre_invoke_sh" in script.read_text()
        )
        assert declares_role == is_seed_script, (
            f"{task.parent}: [scenario].pre_invoke_role_name={declares_role} but "
            f"a generated seed pre_invoke.sh present={is_seed_script}. "
            "aws_bench/task/aws_trial.py runs pre_invoke/pre_invoke.sh iff the "
            "FILE exists and reads the ROLE from task.toml; nothing else "
            "couples them, so a task carrying one without the other either "
            "deploys under the wrong role or skips the seed deploy entirely "
            "and grades an empty account (SCHEMA.md §2.7.1)"
        )
        if declares_role:
            assert (
                cfg["verifier"]["env"].get(SEED_DEPLOY_REQUIRED_ENV_KEY) == "true"
            ), (
                f"{task.parent}: declares a seed deploy but does not arm the "
                "verifier's fail-closed check"
            )
            seen += 1
    assert seen == len(ARMS), (
        f"expected exactly {len(ARMS)} seed-deploying task dirs "
        f"(named-resource-replacement's arms), found {seen}"
    )


def _run_test_sh_gate(
    tmp_path: Path, arm: str, receipt: dict | None, env: dict[str, str]
) -> tuple[int, Path]:
    """Execute the REAL emitted tests/test.sh with only its /logs ROOT moved.

    The gate reads absolute in-container paths, so the one substitution made
    here is `/logs` -> `<tmp>/logs`; everything else -- the condition, the jq
    filter, the exit, the deliberate absence of a reward write -- is the
    shipped text. `static_tiers.sh` is stubbed to a script that writes
    reward.txt, so "the gate let grading proceed" and "the gate refused" are
    distinguishable by the presence of that file, which is exactly what harbor
    keys on (harbor/verifier/verifier.py::verify raises RewardFileNotFoundError
    when it is absent).
    """
    root = tmp_path / arm
    tests = root / "tests"
    tests.mkdir(parents=True)
    logs = root / "logs"
    (logs / "verifier").mkdir(parents=True)

    src = (task_dir(load_spec(SPEC_PATH), arm) / "tests" / "test.sh").read_text()
    expected_moves = src.count("/logs/")
    assert expected_moves, "tests/test.sh names no /logs path -- rewrite this harness"
    body = src.replace("/logs/", f"{logs}/")
    assert body.count(f"{logs}/") == expected_moves, "the /logs rewrite lost a path"
    assert re.search(r'(?<![\w/])/logs/', body) is None, (
        "an absolute /logs path survived the rewrite; the test would read or "
        "write the real container paths"
    )
    (tests / "test.sh").write_text(body)
    (tests / "static_tiers.sh").write_text(
        "#!/usr/bin/env bash\n"
        f'echo "1.0" > "{logs}/verifier/reward.txt"\n'
        "exit 0\n"
    )
    for f in ("test.sh", "static_tiers.sh"):
        (tests / f).chmod(0o755)

    if receipt is not None:
        (logs / "seed-deploy-receipt.json").write_text(json.dumps(receipt))

    proc = subprocess.run(
        ["bash", str(tests / "test.sh")],
        capture_output=True,
        text=True,
        env={**os.environ, **env},
    )
    return proc.returncode, logs


@pytest.mark.parametrize("arm", ARMS)
def test_the_verifier_refuses_to_grade_when_the_seed_receipt_is_absent(
    tmp_path: Path, arm: str
) -> None:
    """THE M3 TEST. No receipt + SPEC_SEED_DEPLOY_REQUIRED=true must produce NO
    REWARD FILE -- not a 0.0.

    The distinction is the whole point. A 0.0 is a MEASUREMENT: it says the
    agent failed. A trial whose seed never deployed produced no measurement at
    all, and recording it as 0.0 would repeat the defect this mechanism fixes
    with the sign flipped.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc, logs = _run_test_sh_gate(
        tmp_path, arm, receipt=None, env={"SPEC_SEED_DEPLOY_REQUIRED": "true"}
    )
    assert rc != 0
    assert not (logs / "verifier" / "reward.txt").exists(), (
        "the gate wrote a reward file -- harbor would then record a SCORE for a "
        "trial that was never seeded, instead of RewardFileNotFoundError"
    )
    marker = json.loads((logs / "verifier" / "seed-deploy-missing.json").read_text())
    assert marker["outcome"] == "run_invalid"
    assert marker["status"] == "run_invalid"


@pytest.mark.parametrize(
    "receipt",
    [
        {"outcome": "seed_absent"},
        {"outcome": "seed_unverifiable"},
        {},
        {"outcome": ""},
    ],
)
def test_the_verifier_refuses_any_receipt_that_is_not_seed_deployed(
    tmp_path: Path, receipt: dict
) -> None:
    """A receipt that exists but does not say `seed_deployed` is not a pass.

    (These cannot be written by the shipped pre_invoke.sh -- it writes the
    receipt only on its success path -- but "the file is present" must never be
    the whole test, or a truncated/partial write becomes a free pass.)
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc, logs = _run_test_sh_gate(
        tmp_path, "hcl_raw", receipt=receipt,
        env={"SPEC_SEED_DEPLOY_REQUIRED": "true"},
    )
    assert rc != 0
    assert not (logs / "verifier" / "reward.txt").exists()


def test_a_proven_seed_lets_grading_proceed(tmp_path: Path) -> None:
    """The positive half -- otherwise the test above passes for a gate that
    refuses everything."""
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc, logs = _run_test_sh_gate(
        tmp_path,
        "hcl_raw",
        receipt={"outcome": "seed_deployed", "scenario": "named-resource-replacement"},
        env={"SPEC_SEED_DEPLOY_REQUIRED": "true"},
    )
    assert rc == 0
    assert (logs / "verifier" / "reward.txt").read_text().strip() == "1.0"


def test_a_spec_without_the_env_key_is_unaffected_by_the_gate(tmp_path: Path) -> None:
    """The block is emitted into EVERY task's tests/test.sh (one static
    template, runtime-gated -- the same discipline the live-check and
    idempotence blocks use), so it has to be a no-op wherever task.toml does
    not set the key. That is every non-brownfield scenario in this repo."""
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc, logs = _run_test_sh_gate(tmp_path, "hcl_raw", receipt=None, env={})
    assert rc == 0
    assert (logs / "verifier" / "reward.txt").read_text().strip() == "1.0"


def test_the_seed_script_writes_the_receipt_the_verifier_reads(spec: Spec) -> None:
    """ONE constant, two emitters -- the writer and the reader cannot drift."""
    for arm in ARMS:
        body = (task_dir(spec, arm) / "pre_invoke" / "pre_invoke.sh").read_text()
        assert f'> {SEED_DEPLOY_RECEIPT_PATH}' in body
        # ...and it is NOT under /logs/pre_invoke/, which ScriptRunner deletes
        # in step 7 before the agent phase (so the verifier could never see it).
        assert not SEED_DEPLOY_RECEIPT_PATH.startswith("/logs/pre_invoke/")
        test_sh = (task_dir(spec, arm) / "tests" / "test.sh").read_text()
        assert SEED_DEPLOY_RECEIPT_PATH in test_sh
        assert SEED_DEPLOY_REQUIRED_ENV_KEY in test_sh


# ---------------------------------------------------------------------------
# 6. `-refresh=false` ON THE EMITTED BYTES (finding M4, adversarial review
#    2026-08-25). Spec._brownfield_plan_must_not_refresh reads
#    output_contract.plan_command and `continue`s when it is empty -- which it
#    is on BOTH cdk-shaped arms. terraconstructs' `terraform plan` comes from a
#    HARDCODED generator template, so the validator was green while proving
#    nothing for that arm, and the guarantee was actually held by an unrelated
#    coupling (live_check.enabled) the validator does not check.
# ---------------------------------------------------------------------------

# THE PLAN SUBCOMMAND, not the literal two words (finding G, adversarial review
# round 3, 2026-08-25). Kept byte-identical to spec_model._TF_PLAN_RE, and
# `test_the_two_plan_matchers_are_the_same_rule` asserts that: the validator
# speaks for the spec FIELD, this speaks for the emitted BYTES, and the emitted
# bytes are the only cover for the arms whose plan command the spec never
# carries (terraconstructs' comes from a hardcoded generator template).
_TF_PLAN = re.compile(r"\bterraform\b(?:\s+-\S+)*\s+plan\b")


def _brownfield_specs() -> list[Path]:
    """Every shipped spec whose loaded model carries a `workspace_seed`.

    FINDING m4's emitted-bytes test took the module `spec` fixture, i.e.
    named-resource-replacement and nothing else, so a SECOND brownfield spec --
    and this change explicitly unblocks four of them -- would have shipped with
    no emitted-bytes assertion at all. The generator half is unconditional, so
    that was coverage narrowness rather than a live hole; this closes it by
    construction instead of by remembering.
    """
    out = []
    for path in sorted((REPO_ROOT / "specs").glob("*.yaml")):
        # split.yaml is train/holdout METADATA, not a scenario spec -- the same
        # exclusion generator/split.py and test_workspace_seed.py make.
        if path.name == "split.yaml":
            continue
        model = load_spec(path)
        if model.workspace_seed is not None:
            out.append(path)
    return out


BROWNFIELD_SPECS = _brownfield_specs()


def _executable_plan_lines(text: str) -> list[str]:
    """Lines that RUN `terraform plan`, excluding comments and prose.

    Deliberately not a parser: these are generated scripts whose plan
    invocations are single logical lines (a `\\`-continued chain keeps the flags
    on the same physical line as the command). Anything that stops being true
    should make this test noisy, not quietly empty -- which is why callers also
    assert the list is NON-empty where a plan is expected.
    """
    out = []
    for line in text.splitlines():
        if not _TF_PLAN.search(line):
            continue
        if line.lstrip().startswith("#"):
            continue
        if re.search(r'echo\s+"[^"]*terraform plan', line):
            continue
        out.append(line)
    return out


def test_there_is_at_least_one_brownfield_spec_to_check() -> None:
    """The parametrisation below is driven by a glob. If that glob ever comes
    back empty the emitted-bytes tests all pass by collecting nothing, which is
    the vacuity this file exists to refuse."""
    assert BROWNFIELD_SPECS, (
        "no specs/*.yaml declares workspace_seed -- the emitted-bytes refresh "
        "tests below would pass vacuously"
    )


def test_the_two_plan_matchers_are_the_same_rule() -> None:
    """Finding G. `Spec._brownfield_plan_must_not_refresh` reads the spec FIELD
    and this file reads the emitted BYTES. They are two halves of one guarantee
    and a drift between them reopens the hole from whichever side was left
    behind."""
    import spec_model  # noqa: PLC0415

    assert _TF_PLAN.pattern == spec_model._TF_PLAN_RE.pattern


@pytest.mark.parametrize(
    "spec_path", BROWNFIELD_SPECS, ids=lambda p: p.stem
)
@pytest.mark.parametrize("arm", ARMS)
def test_every_emitted_terraform_plan_of_a_brownfield_spec_is_refresh_free(
    spec_path: Path, arm: str
) -> None:
    """The SHIPPED bytes, per arm, for EVERY brownfield spec (finding E,
    adversarial review round 3, 2026-08-25 -- this used to take the module
    `spec` fixture and therefore spoke only for named-resource-replacement).

    MEASURED, not predicted: with deploy state in /app/project a refreshing
    plan re-contacts AWS through provider.tf's dummy credentials and dies
    (`Refreshing state... [id=vpc-05c33a26cbf19bef8]` then `PLAN FAILED`,
    jobs/rerun-named-resource-replacement/2026-08-25__01-43-17/
    named-resource-replacement-hcl-r__rtmpCyN/verifier/test-stdout.txt:42-46),
    scoring a PERFECT solution 0.0. `workspace_seed.deploy` puts that state
    there on purpose, on every trial.
    """
    model = load_spec(spec_path)
    if arm not in model.arms.enabled_arms():
        pytest.skip(f"{model.id}: {arm} is not enabled")
    root = task_dir(model, arm)
    found = 0
    for rel in ("tests/static_tiers.sh", "tests/test.sh"):
        lines = _executable_plan_lines((root / rel).read_text())
        found += len(lines)
        offenders = [ln for ln in lines if "-refresh=false" not in ln]
        assert not offenders, (
            f"{model.id}/{arm}/{rel}: refreshing terraform plan(s): {offenders}"
        )
    if arm == "awscdk":
        assert found == 0, "awscdk runs no terraform at all; this test drifted"
    else:
        # NON-EMPTY PER TF ARM, deliberately: without this the parametrised
        # case passes for any spec whose emitted scripts stopped containing a
        # plan at all -- which is how a matcher change would silently empty
        # this test rather than fail it.
        assert found, (
            f"{model.id}/{arm}: no executable `terraform plan` found in the "
            "emitted verifier scripts -- this test would pass vacuously"
        )


def test_a_chdir_style_plan_is_not_exempt_from_the_refresh_rule() -> None:
    """FINDING G's own case, at the validator.

    `terraform -chdir=. plan -input=false ...` is an ordinary, documented
    invocation. The rule used to be the literal substring "terraform plan", so
    this form passed spec load in silence and gen.py spliced it verbatim into
    hcl_raw's static_tiers.sh -- every hcl-raw brownfield trial 0.0 before the
    agent was judged.
    """
    raw = _raw()
    oc = raw["instruction"]["per_arm"]["hcl_raw"]["output_contract"]
    oc["plan_command"] = (
        "terraform init && terraform validate && terraform -chdir=. plan "
        "-input=false -out=plan.tfplan && terraform show -json plan.tfplan > plan.json"
    )
    with pytest.raises(ValueError, match="-refresh=false"):
        Spec.model_validate(raw)

    # ...and the same form WITH the flag still loads, so the rule is about the
    # flag and not about the shape of the command.
    oc["plan_command"] = oc["plan_command"].replace(
        "plan -input=false", "plan -input=false -refresh=false"
    )
    Spec.model_validate(raw)


def test_the_refresh_flag_no_longer_depends_on_live_check_alone(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """THE M4 CASE ITSELF: a brownfield spec with live_check DISABLED.

    Before the fix, terraconstructs' hardcoded `tf_plan_chain` keyed
    `refresh_flag` off `spec.verifier.live_check.enabled` alone, so this
    configuration silently lost the flag -- and
    Spec._brownfield_plan_must_not_refresh could not see it, because that arm's
    `output_contract.plan_command` is None.

    The spec model refuses `live_check.enabled: false` TOGETHER WITH
    `workspace_seed.deploy` (a seed with no live oracle is spend with no
    measurement), so the case is built by dropping `deploy` and keeping the
    `workspace_seed` -- which is exactly the shape the finding names: a
    brownfield spec whose agent applies for real without a harness-deployed
    seed.
    """
    import gen as gen_module

    raw = _raw()
    raw["workspace_seed"].pop("deploy")
    for arm in ARMS:
        raw["instruction"]["per_arm"][arm]["output_contract"].pop("deploy_command")
    raw["verifier"]["live_check"].update(
        {"enabled": False, "gating": False, "hand_authored": False}
    )
    raw["verifier"]["idempotence"] = {"enabled": False, "gating": False}
    greenfield_oracle_brownfield_workspace = Spec.model_validate(raw)

    monkeypatch.setattr(gen_module, "TASKS_DIR", tmp_path / "tasks")
    for arm in ("hcl_raw", "terraconstructs"):
        root = generate_arm(greenfield_oracle_brownfield_workspace, arm)
        lines = _executable_plan_lines((root / "tests" / "static_tiers.sh").read_text())
        assert lines, f"{arm}: no executable terraform plan emitted"
        for ln in lines:
            assert "-refresh=false" in ln, (
                f"{arm}: a brownfield spec emitted a REFRESHING plan because "
                "live_check is disabled -- the exact coupling finding M4 named"
            )


# ---------------------------------------------------------------------------
# 6b. THE SEED PROOF, EXECUTED END TO END in a sandbox (findings D, F and H,
#     adversarial review round 3, 2026-08-25).
#
#     The three findings are three different ways the shipped script told the
#     operator something that was not true, and all three are only visible by
#     RUNNING it: a definitive CloudFormation absence reported as "could not
#     verify" (D), a missing proof library reported as "the account is wrong"
#     (F), and a receipt that could not tell the agent's deployment from the
#     harness's (H). So this section executes the REAL emitted bytes against
#     stubbed `aws`/toolchain binaries, with only the absolute container paths
#     moved -- the same discipline `_run_test_sh_gate` uses one section above.
# ---------------------------------------------------------------------------

_AWS_STUB = """#!/usr/bin/env bash
# Test stub. Dispatches on "<service> <operation>" and replays a checked-in
# response, so the emitted proof runs against real AWS response SHAPES with no
# network and no credentials.
svc="$1"; shift
op="$1"; shift
case "$svc $op" in
  "cloudformation describe-stacks")
    if [ -f "$STUB_DIR/cfn.err" ]; then
      cat "$STUB_DIR/cfn.err" >&2
      exit "${STUB_CFN_RC:-255}"
    fi
    cat "$STUB_DIR/cfn.json"
    ;;
  "ec2 describe-security-groups") cat "$STUB_DIR/sg.json" ;;
  "ec2 describe-vpc-endpoints")   cat "$STUB_DIR/vpce.json" ;;
  *) echo "aws stub: unstubbed call '$svc $op'" >&2; exit 99 ;;
esac
"""

# `terraform`/`npx` stand in for the arm's real deploy_command. Each records
# that it ran (so a test can prove the deploy did NOT happen) and, for the TF
# apply, writes the state file the arm's own state proof then looks for.
_TOOLCHAIN_STUB = """#!/usr/bin/env bash
echo "$0 $*" >> "$STUB_DIR/deploy-ran.log"
for a in "$@"; do
  case "$a" in
    apply|deploy)
      printf '%s' "$STUB_STATE_JSON" > "$STUB_STATE_PATH"
      ;;
  esac
done
exit 0
"""

_SEED_STATE_JSON = '{"version": 4, "lineage": "1f3c0a5e-seed", "serial": 7}'


def _seed_sandbox(tmp_path: Path, arm: str) -> dict:
    """Copy the REAL emitted pre_invoke.sh into a sandbox with only its
    absolute container paths moved.

    The rewrite order matters: `/logs/pre_invoke` is a substring of neither
    `/pre_invoke/` nor `/logs/` once it has been parked behind a token first,
    and doing it in any other order silently mangles half the paths -- which is
    exactly the class of quiet wrongness this file exists to refuse, so the
    result is asserted rather than assumed.
    """
    root = tmp_path / arm
    # Deliberately NOT named logs/ , project/ or pre_invoke/: the survivor check
    # below looks for the container's absolute paths as substrings, and a
    # sandbox that reproduced those names would hide a failed rewrite behind its
    # own directory layout.
    pre = root / "box-pre-invoke"
    logs = root / "box-logs"
    project = root / "box-project"
    bins = root / "box-bin"
    stub = root / "box-stub"
    for d in (pre, logs / "pre_invoke", project, bins, stub):
        d.mkdir(parents=True, exist_ok=True)

    src = (task_dir(load_spec(SPEC_PATH), arm) / "pre_invoke" / "pre_invoke.sh").read_text()
    body = src.replace("/logs/pre_invoke", "@@LOGS_PRE@@")
    body = body.replace("/pre_invoke/", f"{pre}/")
    body = body.replace("/logs/", f"{logs}/")
    body = body.replace("@@LOGS_PRE@@", f"{logs}/pre_invoke")
    body = body.replace("/app/project", str(project))

    # Check for survivors with the SANDBOX ROOT blanked out first: on macOS the
    # tmp root is itself an absolute path containing "/logs/" once rewritten,
    # so a naive substring test flags the rewrite's own output.
    executable = [
        ln.replace(str(root), "@@BOX@@")
        for ln in body.splitlines()
        if ln.strip() and not ln.lstrip().startswith("#")
    ]
    for absolute in ("/logs/", "/app/project", " /pre_invoke/"):
        offenders = [ln for ln in executable if absolute in ln]
        assert not offenders, (
            f"{arm}: an absolute container path survived the sandbox rewrite "
            f"({absolute}): {offenders}"
        )

    script = root / "pre_invoke.sh"
    script.write_text(body)
    (bins / "aws").write_text(_AWS_STUB)
    for tool in ("terraform", "npx"):
        (bins / tool).write_text(_TOOLCHAIN_STUB)
    for f in bins.iterdir():
        f.chmod(0o755)

    # The happy-path responses. A test that wants a different account overwrites
    # one of these before running.
    (stub / "cfn.json").write_text(
        json.dumps(
            {
                "Stacks": [
                    {
                        "StackId": "arn:aws:cloudformation:us-east-1:111122223333:stack/ScenarioStack/abc",
                        "StackName": "ScenarioStack",
                        "StackStatus": "CREATE_COMPLETE",
                        "CreationTime": "2026-08-25T10:00:00.000Z",
                    }
                ]
            }
        )
    )
    shutil.copy(FIXTURES / "describe-security-groups.json", stub / "sg.json")
    shutil.copy(FIXTURES / "describe-vpc-endpoints.json", stub / "vpce.json")

    state_path = {
        "hcl_raw": project / "terraform.tfstate",
        "terraconstructs": project
        / f"terraform.{load_spec(SPEC_PATH).workspace_identity()}.tfstate",
        "awscdk": root / "unused.tfstate",
    }[arm]
    return {
        "root": root,
        "script": script,
        "pre": pre,
        "logs": logs,
        "project": project,
        "bins": bins,
        "stub": stub,
        "state_path": state_path,
    }


def _run_seed_pre_invoke(
    box: dict, *, assert_lib: str | None = ASSERT_LIB_SH, path_only_stubs: bool = False
) -> tuple[int, dict | None, str]:
    if assert_lib is not None:
        (box["pre"] / "_assert_lib.sh").write_text(assert_lib)
    env = {
        **os.environ,
        "STUB_DIR": str(box["stub"]),
        "STUB_STATE_PATH": str(box["state_path"]),
        "STUB_STATE_JSON": _SEED_STATE_JSON,
        "AWS_DEFAULT_REGION": "us-east-1",
    }
    if path_only_stubs:
        env["PATH"] = str(box["bins"])
    else:
        env["PATH"] = f"{box['bins']}{os.pathsep}{os.environ['PATH']}"
    # ABSOLUTE bash: `path_only_stubs` narrows PATH to the stub directory, and
    # subprocess resolves the executable through the env it is handed.
    bash = shutil.which("bash") or "bash"
    proc = subprocess.run(
        [bash, str(box["script"])], capture_output=True, text=True, env=env
    )
    proof_path = box["logs"] / "pre_invoke" / "seed-proof.json"
    proof = None
    if proof_path.is_file():
        try:
            proof = json.loads(proof_path.read_text())
        except json.JSONDecodeError:  # pragma: no cover - the fallback is flat JSON
            proof = {"raw": proof_path.read_text()}
    return proc.returncode, proof, proc.stdout + proc.stderr


def _needs_bash_and_jq() -> None:
    for tool in ("bash", "jq"):
        if shutil.which(tool) is None:  # pragma: no cover - both are assumed
            pytest.skip(f"{tool} not on PATH")


def test_the_sandbox_reaches_seed_deployed_on_every_arm(tmp_path: Path) -> None:
    """The harness's own control case.

    Without this, every negative test below could be passing because the
    sandbox is broken rather than because the guard fired -- the shape of
    vacuity this file exists to refuse.
    """
    _needs_bash_and_jq()
    for arm in ARMS:
        box = _seed_sandbox(tmp_path, arm)
        rc, proof, out = _run_seed_pre_invoke(box)
        assert rc == 0, f"{arm}: seed proof exited {rc}\n{out}"
        assert proof == {"outcome": "seed_deployed"}, f"{arm}: {proof}\n{out}"
        receipt = json.loads((box["logs"] / "seed-deploy-receipt.json").read_text())
        assert receipt["outcome"] == "seed_deployed"
        # FINDING H: the receipt must carry the identity of the state this run
        # deployed, or the idempotence tier cannot tell it from the agent's.
        assert receipt["state_identity"], f"{arm}: receipt has no state_identity"
        if arm == "awscdk":
            assert receipt["state_identity"] == (
                "stack_id=arn:aws:cloudformation:us-east-1:111122223333:stack/"
                "ScenarioStack/abc;last_update=2026-08-25T10:00:00.000Z"
            )
        else:
            assert receipt["state_identity"] == "lineage=1f3c0a5e-seed;serial=7"


@pytest.mark.parametrize(
    "stderr_body,want_rc,want_outcome,why",
    [
        (
            "\nAn error occurred (ValidationError) when calling the "
            "DescribeStacks operation: Stack with id ScenarioStack does not exist\n",
            2,
            "seed_absent",
            "FINDING D. `describe-stacks` on a nonexistent stack exits NON-ZERO "
            "with `ValidationError ... does not exist`. That is a RESOLVED FACT "
            "about the account and its truthful verdict is seed_absent -- the "
            "same three-valued mislabelling m4 was filed for, in the opposite "
            "direction, in the file m4's fix rewrote",
        ),
        (
            "\nUnable to locate credentials. You can configure credentials by "
            "running \"aws configure\".\n",
            3,
            "seed_unverifiable",
            "the question could not be ASKED -- no credentials is not evidence "
            "about the account, and a run that could not ask has no standing to "
            "say the seed is absent",
        ),
        (
            "\nAn error occurred (Throttling) when calling the DescribeStacks "
            "operation (reached max retries: 4): Rate exceeded\n",
            3,
            "seed_unverifiable",
            "throttling is the API refusing to answer, not an answer",
        ),
    ],
)
def test_the_awscdk_state_proof_separates_a_resolved_absence_from_an_unanswered_question(
    tmp_path: Path, stderr_body: str, want_rc: int, want_outcome: str, why: str
) -> None:
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, "awscdk")
    (box["stub"] / "cfn.err").write_text(stderr_body)
    rc, proof, out = _run_seed_pre_invoke(box)
    assert rc == want_rc, f"{why}\nexit {rc}, wanted {want_rc}\n{out}"
    assert proof is not None and proof["outcome"] == want_outcome, f"{why}\n{proof}"
    assert not (box["logs"] / "seed-deploy-receipt.json").exists()


def test_a_stack_in_a_bad_state_is_still_seed_absent(tmp_path: Path) -> None:
    """The other half of finding D's branch: `describe-stacks` ANSWERED, and
    the answer is a stack the agent cannot update. Unchanged behaviour, pinned
    beside the new branch so the rewrite cannot lose it."""
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, "awscdk")
    payload = json.loads((box["stub"] / "cfn.json").read_text())
    payload["Stacks"][0]["StackStatus"] = "ROLLBACK_COMPLETE"
    (box["stub"] / "cfn.json").write_text(json.dumps(payload))
    rc, proof, out = _run_seed_pre_invoke(box)
    assert rc == 2, out
    assert proof is not None and proof["outcome"] == "seed_absent"


def test_a_response_with_no_stack_status_is_unverifiable(tmp_path: Path) -> None:
    """`describe-stacks` exited 0 and said nothing this proof can read. The
    question was asked and NOT answered -- rc 3, never a claim about the
    account."""
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, "awscdk")
    (box["stub"] / "cfn.json").write_text('{"Stacks": []}')
    rc, proof, out = _run_seed_pre_invoke(box)
    assert rc == 3, out
    assert proof is not None and proof["outcome"] == "seed_unverifiable"


@pytest.mark.parametrize("arm", ARMS)
def test_a_missing_assert_lib_is_unverifiable_and_never_reaches_the_account(
    tmp_path: Path, arm: str
) -> None:
    """FINDING F, reproduced and closed.

    `. /pre_invoke/_assert_lib.sh` was sourced with no `set -e` and its result
    was never checked. With the library absent -- ScriptRunner uploads
    pre_invoke/ at RUN time, so a partial upload or a future rename reaches
    this -- the source failed silently, every `assert_check` became
    `command not found` (rc 127), and the emitted dispatch's `elif rc -ne 0`
    bucketed that as CONTRADICTED. The run then exited 2 with "the account does
    not hold EXACTLY the seed this workspace describes": a false statement
    about a real AWS account, in the one file whose job is to be believed.

    Two properties are asserted, and the second is the one that costs money:
    the verdict is seed_unverifiable (3), and the DEPLOY NEVER RAN.
    """
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, arm)
    rc, proof, out = _run_seed_pre_invoke(box, assert_lib=None)
    assert rc == 3, f"{arm}: exit {rc}, wanted 3 (seed_unverifiable)\n{out}"
    assert proof is not None and proof["outcome"] == "seed_unverifiable", proof
    assert "_assert_lib.sh" in proof["reason"]
    assert not (box["stub"] / "deploy-ran.log").exists(), (
        f"{arm}: the deploy ran even though the proof harness was already "
        "broken -- a seed that cannot be checked must never be spent against "
        "the account"
    )


@pytest.mark.parametrize("arm", ARMS)
def test_a_library_that_defines_no_assert_check_is_unverifiable(
    tmp_path: Path, arm: str
) -> None:
    """A library that sources cleanly and defines nothing is the truncated-upload
    case: `. file` succeeds, and every assert would still be `command not
    found`."""
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, arm)
    rc, proof, out = _run_seed_pre_invoke(
        box, assert_lib="#!/usr/bin/env bash\n# truncated upload\n"
    )
    assert rc == 3, f"{arm}: exit {rc}, wanted 3\n{out}"
    assert proof is not None and proof["outcome"] == "seed_unverifiable", proof
    assert "assert_check" in proof["reason"]
    assert not (box["stub"] / "deploy-ran.log").exists()


def test_an_assert_check_rc_outside_the_contract_is_unresolvable_not_contradicted(
    tmp_path: Path,
) -> None:
    """FINDING F's second half: the per-assert dispatch.

    `_assert_lib.sh`'s contract defines exactly three codes (0/1/2). Anything
    else is the harness, not the account, and the dispatch used to sweep it
    into the CONTRADICTED bucket. 127 is the value the missing-library case
    produced, which is why it is the one exercised here.
    """
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, "hcl_raw")
    rc, proof, out = _run_seed_pre_invoke(
        box,
        assert_lib="#!/usr/bin/env bash\nassert_check() { return 127; }\n",
    )
    assert rc == 3, f"exit {rc}, wanted 3 (seed_unverifiable)\n{out}"
    assert proof is not None and proof["outcome"] == "seed_unverifiable", proof
    assert "could not be resolved" in proof["reason"]
    assert "outside" in out and "127" in out, (
        "the operator must be told the rc was outside the documented set, not "
        "just that something was unresolvable"
    )


def test_a_contradicted_live_assert_is_still_seed_absent(tmp_path: Path) -> None:
    """The rc-1 path, kept beside the rc-127 path so finding F's fix cannot
    quietly reclassify a REAL contradiction as unverifiable."""
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, "hcl_raw")
    shutil.copy(FIXTURES / "describe-security-groups-empty.json", box["stub"] / "sg.json")
    rc, proof, out = _run_seed_pre_invoke(box)
    assert rc == 2, f"exit {rc}, wanted 2 (seed_absent)\n{out}"
    assert proof is not None and proof["outcome"] == "seed_absent"


def test_a_duplicated_group_now_aborts_the_trial(tmp_path: Path) -> None:
    """FINDING B, end to end through the SHIPPED script.

    This is the account that scored a perfect agent 0.0: the reset left the
    previous trial's group behind, this trial's seed deployed a second one with
    the same name, and `set_eq`'s `unique` made the proof pass. It must now
    abort in `_prepare` -- no agent phase, no verifier, no reward key.
    """
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, "hcl_raw")
    shutil.copy(
        FIXTURES / "describe-security-groups-duplicate-vpcs.json",
        box["stub"] / "sg.json",
    )
    rc, proof, out = _run_seed_pre_invoke(box)
    assert rc == 2, f"exit {rc}, wanted 2 (seed_absent)\n{out}"
    assert proof is not None and proof["outcome"] == "seed_absent"
    assert not (box["logs"] / "seed-deploy-receipt.json").exists()


def test_a_missing_jq_is_unverifiable_and_never_reaches_the_account(
    tmp_path: Path,
) -> None:
    """The guard that has to run FIRST, because everything after it -- the
    verdict file, the compiled asserts, `_assert_lib.sh` itself -- is written
    in jq. Without jq the old script sourced a library it could not use and
    then spent a real apply against the account before discovering it."""
    _needs_bash_and_jq()
    box = _seed_sandbox(tmp_path, "hcl_raw")
    # A PATH holding only the stubs plus the handful of coreutils the script
    # needs before its own verdict -- and deliberately NOT jq.
    needed = {}
    for tool in ("mkdir", "cat", "head", "grep", "rm", "printf", "echo"):
        found = shutil.which(tool)
        if found is None:  # pragma: no cover - coreutils are assumed
            pytest.skip(f"{tool} not on PATH")
        needed[tool] = found
    for name, target in needed.items():
        link = box["bins"] / name
        if not link.exists():
            link.symlink_to(target)
    rc, proof, out = _run_seed_pre_invoke(box, path_only_stubs=True)
    assert rc == 3, f"exit {rc}, wanted 3 (seed_unverifiable)\n{out}"
    assert "jq is not on PATH" in out
    assert not (box["stub"] / "deploy-ran.log").exists(), (
        "the deploy ran without jq -- the proof could never have been resolved, "
        "so the spend bought no measurement"
    )


# ---------------------------------------------------------------------------
# 6c. THE IDEMPOTENCE TIER'S SEED MOVEMENT GUARD (finding H, adversarial review
#     round 3, 2026-08-25).
#
#     `build_idempotence_block`'s state probe -- "nothing was applied (no
#     deploy state at ...)" -- was a LIVE guard until this mechanism started
#     writing that exact file before the agent's first token. After that a
#     `converged` verdict no longer distinguished "the agent deployed and
#     converged" from "the agent did nothing and the SEED is still converged":
#     a do-nothing agent INHERITS the harness's convergence, silently. These
#     tests execute the shipped tests/test.sh with only its absolute container
#     paths moved.
# ---------------------------------------------------------------------------

_AGENT_MOVED_STATE_JSON = '{"version": 4, "lineage": "1f3c0a5e-seed", "serial": 9}'


def _run_test_sh_idempotence(
    tmp_path: Path,
    arm: str,
    *,
    receipt: dict | None,
    state_json: str | None,
    cfn: dict | None = None,
) -> dict:
    """Execute the REAL emitted tests/test.sh idempotence tier in a sandbox.

    `/logs` and `/app/project` are the only substitutions; the arm's own
    idempotence command is satisfied by stub binaries that exit 0, i.e. by the
    CONVERGED answer -- so anything but `converged` in the result comes from a
    guard and not from the toolchain.
    """
    root = tmp_path / arm
    tests = root / "tests"
    logs = root / "box-logs"
    project = root / "box-project"
    bins = root / "box-bin"
    stub = root / "box-stub"
    for d in (tests, logs / "verifier", project, bins, stub):
        d.mkdir(parents=True, exist_ok=True)

    src = (task_dir(load_spec(SPEC_PATH), arm) / "tests" / "test.sh").read_text()
    body = src.replace("/logs/", f"{logs}/").replace("/app/project", str(project))
    survivors = [
        ln
        for ln in body.splitlines()
        if ln.strip()
        and not ln.lstrip().startswith("#")
        and ("/logs/" in ln.replace(str(root), "@@BOX@@")
             or "/app/project" in ln.replace(str(root), "@@BOX@@"))
    ]
    assert not survivors, f"{arm}: absolute path survived the rewrite: {survivors}"
    (tests / "test.sh").write_text(body)
    (tests / "static_tiers.sh").write_text(
        "#!/usr/bin/env bash\n" f'echo "1.0" > "{logs}/verifier/reward.txt"\n' "exit 0\n"
    )
    for f in ("test.sh", "static_tiers.sh"):
        (tests / f).chmod(0o755)

    (bins / "aws").write_text(_AWS_STUB)
    # Every toolchain the three arms' idempotence commands reach, all answering
    # CONVERGED (exit 0). `cd` inside the command still has to succeed, so the
    # terraconstructs synth directory is created too.
    for tool in ("terraform", "npx", "cdktn"):
        (bins / tool).write_text("#!/usr/bin/env bash\nexit 0\n")
    for f in bins.iterdir():
        f.chmod(0o755)
    (project / "cdktf.out" / "stacks" / load_spec(SPEC_PATH).workspace_identity()).mkdir(
        parents=True, exist_ok=True
    )
    if cfn is not None:
        (stub / "cfn.json").write_text(json.dumps(cfn))
    else:
        (stub / "cfn.err").write_text("stub: no stack response configured\n")

    if receipt is not None:
        (logs / "seed-deploy-receipt.json").write_text(json.dumps(receipt))
    if state_json is not None:
        state_path = {
            "hcl_raw": project / "terraform.tfstate",
            "terraconstructs": project
            / f"terraform.{load_spec(SPEC_PATH).workspace_identity()}.tfstate",
            "awscdk": project / "unused.tfstate",
        }[arm]
        state_path.write_text(state_json)

    subprocess.run(
        [shutil.which("bash") or "bash", str(tests / "test.sh")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bins}{os.pathsep}{os.environ['PATH']}",
            "STUB_DIR": str(stub),
            "SPEC_IDEMPOTENCE_ENABLED": "true",
            "SPEC_IDEMPOTENCE_GATING": "false",
            "SPEC_SEED_DEPLOY_REQUIRED": "false",
            "SPEC_LIVE_CHECK_ENABLED": "false",
        },
    )
    return json.loads((logs / "verifier" / "idempotence-result.json").read_text())


_SEED_CFN = {
    "Stacks": [
        {
            "StackId": "arn:aws:cloudformation:us-east-1:111122223333:stack/ScenarioStack/abc",
            "StackName": "ScenarioStack",
            "StackStatus": "CREATE_COMPLETE",
            "CreationTime": "2026-08-25T10:00:00.000Z",
        }
    ]
}
_SEED_CFN_IDENTITY = (
    "stack_id=arn:aws:cloudformation:us-east-1:111122223333:stack/ScenarioStack/abc"
    ";last_update=2026-08-25T10:00:00.000Z"
)


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs"))
def test_a_do_nothing_agent_cannot_inherit_the_seeds_convergence(
    tmp_path: Path, arm: str
) -> None:
    """FINDING H, on the TF arms.

    The state file is present (the SEED wrote it), the toolchain answers
    "converged" (exit 0), and the state identity has NOT moved. Before this
    guard that was reported `converged` -- crediting the agent with the
    harness's own deployment.
    """
    _needs_bash_and_jq()
    result = _run_test_sh_idempotence(
        tmp_path,
        arm,
        receipt={"outcome": "seed_deployed", "state_identity": "lineage=1f3c0a5e-seed;serial=7"},
        state_json=_SEED_STATE_JSON,
    )
    assert result["outcome"] == "not_verifiable", result
    assert "seeded before the agent" in result["reason"], result
    assert result["exit_code"] == "", (
        "the guard must fire BEFORE the idempotence command runs -- otherwise "
        "the tier spends a plan to reach a verdict it already knows"
    )


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs"))
def test_an_agent_that_actually_applied_still_reports_converged(
    tmp_path: Path, arm: str
) -> None:
    """The other half, and the one that stops this guard becoming a blanket
    `not_verifiable` on every brownfield trial: a MOVED serial passes straight
    through to the arm's own converged-state check."""
    _needs_bash_and_jq()
    result = _run_test_sh_idempotence(
        tmp_path,
        arm,
        receipt={"outcome": "seed_deployed", "state_identity": "lineage=1f3c0a5e-seed;serial=7"},
        state_json=_AGENT_MOVED_STATE_JSON,
    )
    assert result["outcome"] == "converged", result


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs"))
def test_a_recreated_state_at_the_same_serial_still_counts_as_moved(
    tmp_path: Path, arm: str
) -> None:
    """WHY `lineage` AND `serial`, not `serial` alone (which is what the finding
    suggested).

    `serial` is a counter that RESTARTS when the state is recreated from
    scratch, so an agent that destroyed and rebuilt could land back on the
    seed's own serial and read as "nothing moved" -- a false
    `not_verifiable` on a real deployment. `lineage` is the UUID Terraform
    stamps in at creation and never changes, so the PAIR moves under both
    "advanced" and "replaced".
    """
    _needs_bash_and_jq()
    result = _run_test_sh_idempotence(
        tmp_path,
        arm,
        receipt={"outcome": "seed_deployed", "state_identity": "lineage=1f3c0a5e-seed;serial=7"},
        state_json='{"version": 4, "lineage": "9e2b-agent-rebuilt", "serial": 7}',
    )
    assert result["outcome"] == "converged", result


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs"))
def test_a_receipt_without_a_state_identity_is_not_verifiable(
    tmp_path: Path, arm: str
) -> None:
    """FAIL CLOSED. A receipt this verifier cannot read an identity out of makes
    the question unanswerable, and an unanswerable question must not be
    answered `converged`."""
    _needs_bash_and_jq()
    result = _run_test_sh_idempotence(
        tmp_path,
        arm,
        receipt={"outcome": "seed_deployed"},
        state_json=_AGENT_MOVED_STATE_JSON,
    )
    assert result["outcome"] == "not_verifiable", result
    assert "carries no state_identity" in result["reason"], result


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs"))
def test_an_unreadable_state_file_is_not_verifiable(tmp_path: Path, arm: str) -> None:
    """The state file exists (so the old probe stays quiet) and carries no
    identity this tier can read. Local file, local fact: fail closed."""
    _needs_bash_and_jq()
    result = _run_test_sh_idempotence(
        tmp_path,
        arm,
        receipt={"outcome": "seed_deployed", "state_identity": "lineage=1f3c0a5e-seed;serial=7"},
        state_json="not json at all",
    )
    assert result["outcome"] == "not_verifiable", result
    assert "no readable state identity" in result["reason"], result


def test_awscdk_do_nothing_agent_cannot_inherit_the_seeds_convergence(
    tmp_path: Path,
) -> None:
    """FINDING H on the arm with NO local state.

    awscdk never had a file probe -- CloudFormation is the state -- and before
    the seed deploy a do-nothing agent was caught anyway, because `cdk diff`
    against a nonexistent stack reports the whole stack as new. With the seed
    deployed, the unmodified workspace matches the deployed stack exactly and
    `cdk diff` exits 0: the SAME free `converged` the TF arms got, reached by a
    different route.
    """
    _needs_bash_and_jq()
    result = _run_test_sh_idempotence(
        tmp_path,
        "awscdk",
        receipt={"outcome": "seed_deployed", "state_identity": _SEED_CFN_IDENTITY},
        state_json=None,
        cfn=_SEED_CFN,
    )
    assert result["outcome"] == "not_verifiable", result
    assert "seeded before the agent" in result["reason"], result


def test_awscdk_reports_converged_once_the_stack_has_been_updated(
    tmp_path: Path,
) -> None:
    """A `cdk deploy` that CFN actually performed advances `LastUpdatedTime`;
    one it answers "No updates are to be performed" does not. So the moved
    identity is the agent's own deployment."""
    _needs_bash_and_jq()
    updated = json.loads(json.dumps(_SEED_CFN))
    updated["Stacks"][0]["StackStatus"] = "UPDATE_COMPLETE"
    updated["Stacks"][0]["LastUpdatedTime"] = "2026-08-25T11:30:00.000Z"
    result = _run_test_sh_idempotence(
        tmp_path,
        "awscdk",
        receipt={"outcome": "seed_deployed", "state_identity": _SEED_CFN_IDENTITY},
        state_json=None,
        cfn=updated,
    )
    assert result["outcome"] == "converged", result


def test_awscdk_makes_no_claim_when_cloudformation_cannot_be_reached(
    tmp_path: Path,
) -> None:
    """THE DELIBERATE ASYMMETRY. The TF arms read a LOCAL file, so an unreadable
    identity is a broken artifact in this verifier's hand. awscdk has to ASK
    CloudFormation, and offline -- where `cdk diff` cannot resolve an AWS
    environment either -- an unanswered question is not evidence about the
    account. So the guard narrows its claim to "the answer arrived and matched",
    and the completion-marker guard below it catches the rest.
    """
    _needs_bash_and_jq()
    result = _run_test_sh_idempotence(
        tmp_path,
        "awscdk",
        receipt={"outcome": "seed_deployed", "state_identity": _SEED_CFN_IDENTITY},
        state_json=None,
        cfn=None,  # the stub answers with an error on stderr
    )
    # `npx cdk diff` is stubbed to exit 0, i.e. the arm's own check says
    # converged -- the point is that the movement guard did not invent a verdict
    # it had no evidence for.
    assert result["outcome"] == "converged", result


def test_only_a_seeded_spec_grows_the_movement_guard(tmp_path: Path) -> None:
    """The regression guarantee. Every other task's tests/test.sh must not move
    a byte, so the guard is emitted by the same `workspace_seed.deploy` branch
    that emits pre_invoke.sh -- and never by `verifier.idempotence` alone."""
    guard = "SEED MOVEMENT GUARD"
    for path in sorted(TASKS_DIR.rglob("tests/test.sh")):
        has_guard = guard in path.read_text()
        seeded = (path.parent.parent / "pre_invoke" / "pre_invoke.sh").is_file()
        assert has_guard == seeded, (
            f"{path}: movement guard present={has_guard} but a generated seed "
            f"pre_invoke.sh present={seeded} -- these are one branch"
        )


def test_the_receipt_writer_and_the_idempotence_reader_share_one_jq_program(
    spec: Spec,
) -> None:
    """ONE owner, TWO emitters. A drift between the identity pre_invoke.sh
    stamps and the one tests/test.sh recomputes would make every brownfield
    trial `not_verifiable` (or, worse, every one `converged`) with nothing
    recording why."""
    for arm in ARMS:
        program = SEED_STATE_IDENTITY_JQ[arm]
        assert program in build_seed_pre_invoke_sh(spec, arm), f"{arm}: writer"
        assert program in (task_dir(spec, arm) / "tests" / "test.sh").read_text(), (
            f"{arm}: reader"
        )


# ---------------------------------------------------------------------------
# 7. Three-valued assert_check (finding m4) and the tier-0 callers it must not
#    disturb.
# ---------------------------------------------------------------------------


def test_an_unresolvable_query_returns_2_not_1() -> None:
    """"could not run" is not "was contradicted".

    A malformed AWS response used to make the seed proof report `seed_absent`
    ("the account does not hold the seed this workspace describes") when the
    truthful verdict was `seed_unverifiable` -- a claim about a real AWS
    account that the run had no standing to make.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc = _run_assert_check(
        "unresolvable",
        jsonpath_to_jq("$.SecurityGroups[*].GroupName"),
        "set_eq",
        ["internal-services-ssm-endpoint"],
        FIXTURES / "malformed-response.txt",
    )
    assert rc == 2, "a jq query error must be UNRESOLVABLE (2), not contradicted (1)"


def test_a_contradicted_query_still_returns_1() -> None:
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc = _run_assert_check(
        "contradicted",
        jsonpath_to_jq("$.SecurityGroups[*].GroupName"),
        "set_eq",
        ["internal-services-ssm-endpoint"],
        FIXTURES / "describe-security-groups-empty.json",
    )
    assert rc == 1


def test_an_unknown_op_is_unresolvable_not_contradicted() -> None:
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    rc = _run_assert_check(
        "bad-op",
        jsonpath_to_jq("$.SecurityGroups[*].GroupName"),
        "no_such_op",
        "x",
        FIXTURES / "describe-security-groups.json",
    )
    assert rc == 2


@pytest.mark.parametrize(
    "artifact,why",
    [
        ("malformed-response.txt", "unresolvable (rc 2)"),
        ("describe-security-groups-empty.json", "contradicted (rc 1)"),
    ],
)
def test_tier0_still_treats_an_unresolvable_assert_as_a_failure(
    artifact: str, why: str
) -> None:
    """_assert_lib.sh is SHARED with tier-0, so rc 2 must behave there exactly
    as rc 1 did.

    Both existing callers test `!= 0` -- `assert_check ... || tier0_pass=0` in
    the generated static_tiers.sh, and `ok = proc.returncode == 0` in
    generator/check_reference_paths.py::_assert_check_via_bash. This runs the
    tier-0 call shape verbatim and pins that tier0_pass still goes to 0.
    """
    if shutil.which("jq") is None:  # pragma: no cover - jq is assumed
        pytest.skip("jq not on PATH")
    lib = REPO_ROOT / "generator" / "tests" / ".assert_lib_tier0_under_test.sh"
    lib.write_text(ASSERT_LIB_SH)
    try:
        jq_filter = jsonpath_to_jq("$.SecurityGroups[*].GroupName")
        script = (
            "set -uo pipefail\n"
            f". {lib}\n"
            "tier0_pass=1\n"
            f"assert_check n {json.dumps(jq_filter)} set_eq "
            f'{json.dumps(json.dumps(["internal-services-ssm-endpoint"]))} '
            f"{FIXTURES / artifact} || tier0_pass=0\n"
            'echo "tier0_pass=$tier0_pass"\n'
        )
        proc = subprocess.run(["bash", "-c", script], capture_output=True, text=True)
    finally:
        lib.unlink(missing_ok=True)
    assert "tier0_pass=0" in proc.stdout, (
        f"tier-0 must still fail on an assert that is {why}: {proc.stdout}"
    )


# ---------------------------------------------------------------------------
# 8. What the script leaves behind (finding m2) and who it runs as (finding m3)
# ---------------------------------------------------------------------------


def test_the_seed_proof_writes_no_probe_artifacts_the_agent_will_inherit(
    spec: Spec,
) -> None:
    """ScriptRunner's cleanup removes /pre_invoke and /logs/pre_invoke and
    NOTHING ELSE (aws_bench/task/script_runner.py step 7), so anything this
    script drops in /tmp survives into the container the agent then works in --
    and these probes are raw `aws` responses describing the seed the agent is
    supposed to discover for itself.
    """
    for arm in ARMS:
        body = build_seed_pre_invoke_sh(spec, arm)
        stray = sorted(
            {
                m.group(0)
                for m in re.finditer(r"/tmp/[\w.\-]+", body)
                if m.group(0) != "/tmp/assert-jq-err.txt"
            }
        )
        assert not stray, (
            f"{arm}: the seed proof writes {stray} under /tmp, which survives "
            "into the agent's own container"
        )
        # The one /tmp path that is NOT this generator's to move -- it is
        # written by the SHARED _assert_lib.sh, whose behaviour tier-0 depends
        # on -- must be removed explicitly instead.
        assert "rm -f /tmp/assert-jq-err.txt" in body
        assert "/tmp/assert-jq-err.txt" in ASSERT_LIB_SH


def test_the_header_claims_only_what_is_enforced(spec: Spec) -> None:
    """Finding m2's other half, and finding M1's shape: a comment must not
    assert a property the code does not have.

    The header used to say the agent "never sees this file, its output, or the
    fact that a harness deployed anything" while three probe files sat in /tmp
    -- and, after the M3 fix, while a receipt is left behind ON PURPOSE.
    """
    for arm in ARMS:
        body = build_seed_pre_invoke_sh(spec, arm)
        header = body.split("set -uo pipefail")[0]
        assert "never sees this file, its output, or the fact that a" not in header
        assert "DELIBERATELY LEFT BEHIND" in header
        assert SEED_DEPLOY_RECEIPT_PATH in header


def test_a_seed_deploying_task_toml_never_pins_an_agent_user(spec: Spec) -> None:
    """Finding m3. The knob that ACTUALLY diverges the two users is
    `[agent] user`, not a Dockerfile `USER`.

    aws_trial.py::_staged_credentials writes ~/.aws/credentials as
    `self.task.config.agent.user` while ScriptRunner.run execs the phase script
    with no `user=` at all -- set them apart and the seed deploy runs as a user
    whose $HOME holds no credentials file.
    """
    for arm in ARMS:
        cfg = tomllib.loads((task_dir(spec, arm) / "task.toml").read_text())
        assert "user" not in cfg.get("agent", {}), (
            f"{arm}: task.toml pins [agent].user on a workspace_seed.deploy spec"
        )


def test_the_agent_user_trip_wire_actually_fires() -> None:
    """The guard, exercised.

    No generator code path emits `[agent] user` today, so a test that only ever
    called build_task_toml could never reach this branch -- and a guard nothing
    can reach is a comment claiming a property, which is finding M1's own
    shape. So the guard is a named function and this calls it directly, on both
    a clean body and a poisoned one.
    """
    clean = "[agent]\ntimeout_sec = 3600.0\n\n[verifier]\ntimeout_sec = 900.0\n"
    assert_no_agent_user_for_seed_deploy(clean, "spec-id", "hcl_raw")  # no raise

    poisoned = (
        "[agent]\ntimeout_sec = 3600.0\nuser = \"agent\"\n\n"
        "[verifier]\ntimeout_sec = 900.0\n"
    )
    with pytest.raises(RuntimeError, match=r"\[agent\]"):
        assert_no_agent_user_for_seed_deploy(poisoned, "spec-id", "hcl_raw")

    # ...and it must not reach into a LATER table's `user =` key.
    later_table = (
        "[agent]\ntimeout_sec = 3600.0\n\n[verifier]\ntimeout_sec = 900.0\n"
        'user = "someone-else"\n'
    )
    assert_no_agent_user_for_seed_deploy(later_table, "spec-id", "hcl_raw")
