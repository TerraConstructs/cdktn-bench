"""generator/tests/test_teardown_tier.py — the TEARDOWN tier: specs/SCHEMA.md
§5.2, DECISIONS.md Amendment 37 (the teardown tier).

The tier grades the agent's own destroy. Four failures would otherwise be
silent, and each group below exists for exactly one of them:

1. VALIDATORS — a teardown declared on a spec with no live phase (an offline
   destroy exits 0 having removed nothing and reads as `clean`), or a `gating`
   flag on a tier that never runs.
2. CONDITIONAL EMISSION + ORDERING — a spec that does not opt in must generate
   byte-identically, and the block must land AFTER the idempotence block:
   destroying first invalidates both the live check and idempotence.
3. FINAL STEP ONLY — a destroy after an intermediate step deletes the substrate
   the next step is about to change.
4. THE GATING COMPOSITION, executed — the emitted shell, run against stubbed
   toolchains, keeps 1.0 only for `clean`, writes 0.0 for `destroy_failed` and
   for `not_verifiable` under gating, and leaves the reward untouched when the
   tier is observational.

Everything here runs offline: the arms' real toolchains are never invoked.
"""

from __future__ import annotations

import copy
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import gen
from spec_model import Spec, load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PILOT_SPEC = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
MULTISTEP_SPEC = REPO_ROOT / "specs" / "apigw-redeploy.yaml"
# Every spec that does NOT opt in. Discovered, not listed, so a spec added later
# is covered by the regression guarantee automatically.
ALL_SPECS = [
    p for p in sorted((REPO_ROOT / "specs").glob("*.yaml")) if p.name != "split.yaml"
]


@pytest.fixture(scope="module")
def pilot() -> Spec:
    return load_spec(PILOT_SPEC)


def _mutated(raw: dict, mutate) -> Spec:
    d = copy.deepcopy(raw)
    mutate(d)
    return Spec.model_validate(d)


@pytest.fixture(scope="module")
def pilot_raw() -> dict:
    return yaml.safe_load(PILOT_SPEC.read_text())


# ---------------------------------------------------------------------------
# 1. validators
# ---------------------------------------------------------------------------


class TestTeardownValidators:
    def test_the_pilot_opts_in_non_gating(self, pilot: Spec) -> None:
        """The promotion vehicle (Amendment 37): observed live before it gates.
        A change here is a decision, not a refactor."""
        assert pilot.verifier.teardown.enabled
        assert not pilot.verifier.teardown.gating

    def test_teardown_requires_live_check(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["verifier"]["live_check"] = {"enabled": False}
        with pytest.raises(
            ValidationError, match="requires\n?\\s*verifier.live_check.enabled=true"
        ):
            _mutated(pilot_raw, mutate)

    def test_gating_requires_enabled(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["verifier"]["teardown"] = {"enabled": False, "gating": True}
        with pytest.raises(ValidationError, match="gating=true requires enabled=true"):
            _mutated(pilot_raw, mutate)

    # `match=` names a phrase unique to THIS validator, not the "gating=true"
    # that `_teardown_gating_requires_enabled`'s message also carries: a
    # regression routing the failure to that other validator would otherwise
    # still pass these.
    CATCH_TIER_MESSAGE = "cannot be the tier that catches anything"

    def test_a_teardown_tier_catch_requires_a_gating_teardown(self, pilot_raw: dict) -> None:
        """`predicted_tier_caught: "teardown"` names the destroy as the tier
        that decides. The pilot's tier is observational, so naming it there
        would record a catch as graded while costing a trial nothing."""
        def mutate(d: dict) -> None:
            d["catches"][0]["predicted_tier_caught"]["hcl"] = "teardown"
        with pytest.raises(ValidationError, match=self.CATCH_TIER_MESSAGE):
            _mutated(pilot_raw, mutate)

    def test_a_teardown_tier_catch_requires_the_tier_to_run_at_all(
        self, pilot_raw: dict
    ) -> None:
        """The other half of the same condition: with no teardown block the
        tier is off, so no destroy runs and nothing can be caught by one."""
        def mutate(d: dict) -> None:
            d["verifier"].pop("teardown", None)
            d["catches"][0]["predicted_tier_caught"]["hcl"] = "teardown"
        with pytest.raises(ValidationError, match=self.CATCH_TIER_MESSAGE):
            _mutated(pilot_raw, mutate)

    def test_a_teardown_tier_catch_is_accepted_once_the_tier_gates(
        self, pilot_raw: dict
    ) -> None:
        def mutate(d: dict) -> None:
            d["verifier"]["teardown"] = {"enabled": True, "gating": True}
            d["catches"][0]["predicted_tier_caught"]["hcl"] = "teardown"
        spec = _mutated(pilot_raw, mutate)
        assert spec.catches[0].predicted_tier_caught.hcl == "teardown"

    def test_the_terraconstructs_override_is_checked_too(self, pilot_raw: dict) -> None:
        """The override is a third place the value can appear, and the arm it
        speaks for is the one whose destroy differs most from the others."""
        def mutate(d: dict) -> None:
            d["catches"][0]["predicted_tier_caught"]["terraconstructs_override"] = "teardown"
        with pytest.raises(ValidationError, match=self.CATCH_TIER_MESSAGE):
            _mutated(pilot_raw, mutate)

    def test_defaults_are_off(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["verifier"].pop("teardown", None)
        spec = _mutated(pilot_raw, mutate)
        assert not spec.verifier.teardown.enabled
        assert not spec.verifier.teardown.gating


# ---------------------------------------------------------------------------
# 2. conditional emission + ordering
# ---------------------------------------------------------------------------


NON_TEARDOWN_SPECS = [
    p for p in ALL_SPECS if not load_spec(p).verifier.teardown.enabled
]


class TestConditionalEmission:
    @pytest.mark.parametrize("path", NON_TEARDOWN_SPECS, ids=lambda p: p.stem)
    def test_a_spec_without_the_tier_emits_no_block(self, path: Path) -> None:
        """Generation-conditional, not a dead runtime branch: `build_test_sh` is
        one static template shared by every task, so an always-emitted block
        would move every existing task's bytes."""
        spec = load_spec(path)
        for arm in spec.arms.enabled_arms():
            assert gen.build_teardown_block(spec, arm) == ""
            assert "SPEC_TEARDOWN_ENABLED" not in gen.build_test_sh(spec, arm)

    @pytest.mark.parametrize("path", NON_TEARDOWN_SPECS, ids=lambda p: p.stem)
    def test_test_sh_is_byte_identical_with_the_tier_off(self, path: Path) -> None:
        """The claim stated as bytes: enabling teardown on the PILOT may not
        move one byte of any other spec's emitted test.sh. Compared against the
        same spec generated with the field forcibly cleared, which is what a
        spec predating the field validates to."""
        spec = load_spec(path)
        stripped = load_spec(path)
        stripped.verifier.teardown.enabled = False
        for arm in spec.arms.enabled_arms():
            assert gen.build_test_sh(spec, arm) == gen.build_test_sh(stripped, arm)

    def test_the_two_tiers_share_one_placeholder_line(self) -> None:
        """The mechanism behind the byte-identity claim. A SECOND placeholder
        line would add a blank line to every task that opts into neither tier,
        which is precisely what generation-conditional emission protects."""
        spec = load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")
        assert gen.build_test_sh(spec, "hcl_raw").endswith("fi\n\nexit $rc\n")

    @pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs"])
    def test_the_block_is_emitted_on_every_arm_of_the_opted_in_spec(
        self, pilot: Spec, arm: str
    ) -> None:
        text = (gen.task_dir(pilot, arm) / "tests" / "test.sh").read_text()
        assert "SPEC_TEARDOWN_ENABLED" in text
        assert "/logs/verifier/teardown-result.json" in text
        assert "/logs/verifier/teardown.log" in text
        assert gen.TEARDOWN_COMMAND[arm].replace(
            "__WORKSPACE_ID__", pilot.workspace_identity()
        ) in text

    @pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs"])
    def test_teardown_runs_after_idempotence(self, pilot: Spec, arm: str) -> None:
        """ORDERING IS LOAD-BEARING (SCHEMA.md §5.2): destroying first would
        invalidate the live check and the idempotence tier alike, so both
        earlier blocks must already have reached their verdicts."""
        text = (gen.task_dir(pilot, arm) / "tests" / "test.sh").read_text()
        live = text.index("SPEC_LIVE_CHECK_ENABLED")
        idem = text.index("idempotence tier (specs/SCHEMA.md §5.1)")
        down = text.index("teardown tier (specs/SCHEMA.md §5.2)")
        assert live < idem < down, (live, idem, down)

    @pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs"])
    def test_the_destroy_is_generator_injected_not_spec_declared(
        self, pilot: Spec, arm: str
    ) -> None:
        """The same "cannot go missing because a spec author forgot a YAML key"
        discipline IDEMPOTENCE_COMMAND uses: no spec key names a destroy, so no
        spec can ship the tier without one."""
        raw = yaml.safe_load(PILOT_SPEC.read_text())
        assert set(raw["verifier"]["teardown"]) == {"enabled", "gating"}
        assert "destroy" in gen.TEARDOWN_COMMAND[arm]

    def test_every_arm_has_exactly_one_never_deployed_guard(self, pilot: Spec) -> None:
        """Neither guard fails OPEN into a fake `clean` (an offline destroy with
        no state exits 0 having removed nothing); both would leave ownership
        ambiguous."""
        for arm in pilot.arms.enabled_arms():
            probe = bool(gen.TEARDOWN_STATE_PROBE[arm])
            marker = bool(gen.TEARDOWN_COMPLETION_MARKER[arm])
            assert probe != marker, f"{arm}: probe={probe}, marker={marker}"

    def test_the_probe_map_is_the_idempotence_one(self) -> None:
        """One never-deployed fact about each arm, read from one map. A second,
        forked copy is how the two tiers come to disagree about where an arm
        keeps its state."""
        assert gen.TEARDOWN_STATE_PROBE == gen.IDEMPOTENCE_STATE_PROBE

    def test_awscdk_exit_zero_alone_is_not_clean(self, pilot: Spec) -> None:
        """This arm keeps no local state to pre-flight probe, and `cdk destroy`
        exits 0 both for "CloudFormation deleted the stack" and for "there was
        nothing to delete". Exit 0 is believed only alongside the completion
        marker; without it the outcome is not_verifiable, never clean."""
        text = (gen.task_dir(pilot, "awscdk") / "tests" / "test.sh").read_text()
        marker = gen.TEARDOWN_COMPLETION_MARKER["awscdk"]
        assert marker
        assert (
            f'if [ "$down_rc" -eq 0 ] \\\n'
            f"               && grep -qF '{marker}' "
            f"/logs/verifier/teardown.log; then" in text
        ), text
        assert "without printing its own completion marker" in text

    def test_the_schema_text_says_it_is_not_a_cleanup_mechanism(self) -> None:
        """The sentence that keeps someone from later "improving" the tier into
        a cleanup mechanism, pinned where a reader of the emitted script meets
        it: the framework reset is what returns the account to baseline."""
        schema = (REPO_ROOT / "specs" / "SCHEMA.md").read_text()
        assert "not a cleanup mechanism" in schema.lower()
        spec = load_spec(PILOT_SPEC)
        block = gen.build_teardown_block(spec, "hcl_raw")
        assert "NOT a cleanup mechanism" in block
        assert "is NOT retried here" in block

    def test_no_new_file_is_emitted_into_tests(self, pilot: Spec) -> None:
        """The tier writes only under /logs, so `_GENERATED_TESTS_FILES` — the
        sweep list that removes a stale generated oracle — needs no entry. A
        future teardown file that skipped that list would survive a spec turning
        the tier back off."""
        for arm in pilot.arms.enabled_arms():
            names = {p.name for p in (gen.task_dir(pilot, arm) / "tests").iterdir()}
            assert names <= set(gen._GENERATED_TESTS_FILES), names
            assert not any(n.startswith("teardown") for n in names)


# ---------------------------------------------------------------------------
# 3. final step only
# ---------------------------------------------------------------------------


def test_a_multi_step_spec_arms_the_tier_on_the_final_step_only() -> None:
    """A destroy after an intermediate step deletes the substrate the next step
    is about to change, so every later step would grade an empty account.

    No current spec is both multi-step and teardown-enabled; the branch exists
    so the composition is defined rather than silently wrong the first time one
    is, and this test enables it in memory to exercise it.
    """
    spec = load_spec(MULTISTEP_SPEC)
    assert spec.is_multi_step() and len(spec.steps or []) > 1
    spec.verifier.teardown.enabled = True
    spec.verifier.teardown.gating = True
    lines = gen.build_steps_toml(spec, spec.verifier.live_check)
    armed = [ln for ln in lines if "SPEC_TEARDOWN_ENABLED" in ln]
    assert len(armed) == 1, lines
    assert 'SPEC_TEARDOWN_GATING = "true"' in armed[0]
    # ...and it is the LAST step's env line, not merely a single one.
    env_lines = [ln for ln in lines if ln.startswith("env = {")]
    assert env_lines[-1] == armed[0], env_lines


def test_a_multi_step_spec_without_the_tier_emits_no_step_flag() -> None:
    spec = load_spec(MULTISTEP_SPEC)
    assert not spec.verifier.teardown.enabled
    lines = gen.build_steps_toml(spec, spec.verifier.live_check)
    assert not [ln for ln in lines if "SPEC_TEARDOWN" in ln]


def test_the_single_step_pilot_carries_the_flag_in_task_toml(pilot: Spec) -> None:
    for arm in pilot.arms.enabled_arms():
        text = (gen.task_dir(pilot, arm) / "task.toml").read_text()
        assert 'SPEC_TEARDOWN_ENABLED = "true"' in text, arm
        # Non-gating today. Amendment 37 promotes the tier before it gates.
        assert "SPEC_TEARDOWN_GATING" not in text, arm


# ---------------------------------------------------------------------------
# 4. THE GATING COMPOSITION, executed
#
#     The emitted shell is run for real, with `/logs` and `/app/project` moved
#     and every toolchain stubbed. Only the destroy's exit code and the presence
#     of deploy state vary, so any reward in the result came from the block
#     under test and from nothing else.
# ---------------------------------------------------------------------------


def _needs_bash_and_jq() -> None:
    for tool in ("bash", "jq"):
        if shutil.which(tool) is None:  # pragma: no cover - CI has both
            pytest.skip(f"{tool} not on PATH")


# The seed receipt identity and the deployed identity the stubs answer with.
# They DIFFER by default: the pilot deploys a workspace seed, and the movement
# guard skips the destroy whenever they match, so a run that left them equal
# would exercise the guard rather than the branch under test. A case that wants
# the guard passes `seed_moved=False`.
_SEED_IDENTITY = {
    "hcl_raw": "lineage=11111111-2222-3333-4444-555555555555;serial=1",
    "terraconstructs": "lineage=11111111-2222-3333-4444-555555555555;serial=1",
    "awscdk": "stack_id=arn:aws:cloudformation:eu-west-1:1:stack/ScenarioStack/seed"
    ";last_update=2026-09-10T00:00:00Z",
}
_STATE_JSON = (
    '{"version": 4, "serial": 3, '
    '"lineage": "11111111-2222-3333-4444-555555555555"}'
)
_SEED_STATE_JSON = (
    '{"version": 4, "serial": 1, '
    '"lineage": "11111111-2222-3333-4444-555555555555"}'
)
_CFN_JSON = (
    '{"Stacks": [{"StackId": "arn:aws:cloudformation:eu-west-1:1:stack/'
    'ScenarioStack/agent", "LastUpdatedTime": "2026-09-10T01:00:00Z"}]}'
)
# describe-stacks answering with the identity the receipt already carries: the
# stack the harness seeded, untouched by the agent.
_SEED_CFN_JSON = (
    '{"Stacks": [{"StackId": "arn:aws:cloudformation:eu-west-1:1:stack/'
    'ScenarioStack/seed", "LastUpdatedTime": "2026-09-10T00:00:00Z"}]}'
)


def _run_teardown(
    tmp_path: Path,
    arm: str,
    *,
    destroy_rc: int,
    state: bool,
    gating: bool,
    destroy_stdout: str = "",
    seed_moved: bool = True,
    synth_removes_state: bool = False,
    no_receipt: bool = False,
) -> tuple[dict | None, str]:
    """Execute the REAL emitted tests/test.sh teardown tier in a sandbox.

    Returns the parsed teardown-result.json (None when the block wrote none)
    and the reward file's contents. `static_tiers.sh` is stubbed to the PASSING
    static verdict (1.0), so a 0.0 in the result is the gating block's doing.
    """
    spec = load_spec(PILOT_SPEC)
    case = f"{arm}-{destroy_rc}-{state}-{gating}"
    root = tmp_path / f"{case}-{seed_moved}-{synth_removes_state}-{no_receipt}"
    tests, logs, project, bins = (
        root / "tests",
        root / "box-logs",
        root / "box-project",
        root / "box-bin",
    )
    for d in (tests, logs / "verifier", project, bins):
        d.mkdir(parents=True, exist_ok=True)

    src = (gen.task_dir(spec, arm) / "tests" / "test.sh").read_text()
    body = src.replace("/logs/", f"{logs}/").replace("/app/project", str(project))
    (tests / "test.sh").write_text(body)
    (tests / "static_tiers.sh").write_text(
        "#!/usr/bin/env bash\n" f'echo "1.0" > "{logs}/verifier/reward.txt"\n' "exit 0\n"
    )
    for f in ("test.sh", "static_tiers.sh"):
        (tests / f).chmod(0o755)

    # Every binary the three arms' destroy commands reach, all answering with
    # the requested exit code; `cd` into the synth dir still has to succeed.
    # `describe-stacks` is answered separately, with exit 0: it is the awscdk
    # movement guard's question, not the destroy, and letting the destroy's exit
    # code answer it would make every awscdk case abstain.
    tf_state = project / f"terraform.{spec.workspace_identity()}.tfstate"
    synth = f"rm -f '{tf_state}'; exit 0" if synth_removes_state else "exit 0"
    for tool in ("terraform", "npx", "cdktn", "cdk", "aws"):
        (bins / tool).write_text(
            "#!/usr/bin/env bash\n"
            f'case " $* " in *" synth "*) {synth} ;; *" init "*) exit 0 ;; esac\n'
            "case \" $* \" in *describe-stacks*) "
            f"printf '%s' \"$TEARDOWN_CFN_OUT\"; exit 0 ;; esac\n"
            f"printf '%s' \"$TEARDOWN_STUB_OUT\"\n"
            f"exit {destroy_rc}\n"
        )
    for f in bins.iterdir():
        f.chmod(0o755)
    (project / "cdktf.out" / "stacks" / spec.workspace_identity()).mkdir(
        parents=True, exist_ok=True
    )
    if state:
        for name in ("terraform.tfstate", tf_state.name):
            (project / name).write_text(
                _STATE_JSON if seed_moved else _SEED_STATE_JSON
            )
    # The pilot deploys a workspace seed, so the emitted block carries the SEED
    # MOVEMENT GUARD and reads this receipt before it will spend a destroy.
    if not no_receipt:
        (logs / "seed-deploy-receipt.json").write_text(
            json.dumps(
                {"outcome": "seed_deployed", "state_identity": _SEED_IDENTITY[arm]}
            )
        )

    subprocess.run(
        [shutil.which("bash") or "bash", str(tests / "test.sh")],
        capture_output=True,
        text=True,
        env={
            **os.environ,
            "PATH": f"{bins}{os.pathsep}{os.environ['PATH']}",
            "TEARDOWN_STUB_OUT": destroy_stdout,
            "TEARDOWN_CFN_OUT": _CFN_JSON if seed_moved else _SEED_CFN_JSON,
            "SPEC_TEARDOWN_ENABLED": "true",
            "SPEC_TEARDOWN_GATING": "true" if gating else "false",
            "SPEC_IDEMPOTENCE_ENABLED": "false",
            "SPEC_SEED_DEPLOY_REQUIRED": "false",
            "SPEC_LIVE_CHECK_ENABLED": "false",
        },
    )
    result_path = logs / "verifier" / "teardown-result.json"
    result = json.loads(result_path.read_text()) if result_path.exists() else None
    reward = (logs / "verifier" / "reward.txt").read_text().strip()
    return result, reward


_CLEAN_STDOUT = {
    "hcl_raw": "",
    "terraconstructs": "",
    "awscdk": "\n ✅  ScenarioStack: destroyed\n",
}


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs", "awscdk"))
@pytest.mark.parametrize("gating", (True, False))
def test_a_clean_destroy_keeps_the_static_reward(
    tmp_path: Path, arm: str, gating: bool
) -> None:
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path,
        arm,
        destroy_rc=0,
        state=True,
        gating=gating,
        destroy_stdout=_CLEAN_STDOUT[arm],
    )
    assert result["outcome"] == "clean", result
    assert reward == "1.0", (result, reward)


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs", "awscdk"))
def test_a_failed_destroy_gates_the_reward_to_zero(tmp_path: Path, arm: str) -> None:
    """The verdict the tier exists to produce: everything applied green, the
    live check passed, and the agent's own destroy will not run."""
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path, arm, destroy_rc=1, state=True, gating=True
    )
    assert result["outcome"] == "destroy_failed", result
    assert reward == "0.0", (result, reward)


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs", "awscdk"))
def test_a_failed_destroy_is_recorded_but_not_gating_when_observational(
    tmp_path: Path, arm: str
) -> None:
    """Non-gating is the pilot's own configuration (Amendment 37's promotion
    vehicle): the verdict is still written whether gating or not, and the reward
    is untouched."""
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path, arm, destroy_rc=1, state=True, gating=False
    )
    assert result["outcome"] == "destroy_failed", result
    assert reward == "1.0", (result, reward)


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs"))
def test_never_deployed_is_skipped_with_a_reason_and_no_destroy(
    tmp_path: Path, arm: str
) -> None:
    """THE NEVER-DEPLOYED PROBE PATH, on the arms that keep local state. An
    offline `terraform destroy` with no state exits 0 having removed nothing,
    which would read as `clean` — so no destroy is attempted at all."""
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path, arm, destroy_rc=0, state=False, gating=True
    )
    assert result["outcome"] == "not_verifiable", result
    assert "nothing was applied" in result["reason"], result
    assert result["exit_code"] == "", (
        "the probe must fire BEFORE the destroy runs -- otherwise the tier "
        "spends a destroy to reach a verdict it already knows"
    )
    assert reward == "0.0", (result, reward)


def test_awscdk_never_deployed_is_skipped_with_a_reason(tmp_path: Path) -> None:
    """The same guarantee on the arm with no local state, via the completion
    marker: `cdk destroy` exits 0 having deleted nothing when the environment
    cannot be resolved, and that is not_verifiable, never clean."""
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path, "awscdk", destroy_rc=0, state=False, gating=True
    )
    assert result["outcome"] == "not_verifiable", result
    assert "without printing its own completion marker" in result["reason"], result
    assert reward == "0.0", (result, reward)


def test_not_verifiable_leaves_the_reward_alone_when_not_gating(
    tmp_path: Path,
) -> None:
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path, "hcl_raw", destroy_rc=0, state=False, gating=False
    )
    assert result["outcome"] == "not_verifiable", result
    assert reward == "1.0", (result, reward)


# ---------------------------------------------------------------------------
# 5. THE SEED MOVEMENT GUARD, on the one spec that opts in
#
#     The pilot is a `workspace_seed.deploy` spec, so the pre-flight file probe
#     above CANNOT fire: pre_invoke.sh writes that state before the agent's
#     first token. Without the guard the tier would destroy the HARNESS's seed
#     and record it as the agent's clean teardown.
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs", "awscdk"))
def test_the_seed_movement_guard_is_emitted_on_every_arm(
    pilot: Spec, arm: str
) -> None:
    """§5.2 claims the never-deployed case is caught by "the same per-arm
    mechanisms §5.1 already defines", and the guard is one of them. The two
    tiers emit it from ONE function, so their per-arm mechanics cannot drift."""
    block = gen.build_teardown_block(pilot, arm)
    assert "SEED MOVEMENT GUARD" in block
    assert gen.SEED_STATE_IDENTITY_JQ[arm] in block
    assert gen.SEED_DEPLOY_RECEIPT_PATH in block
    assert 'down_outcome="not_verifiable"' in block


def test_the_guard_speaks_for_the_teardown_tier_not_the_idempotence_one() -> None:
    """One mechanism, two consequences. The teardown copy must say what it
    withholds — the destroy — rather than repeating §5.1's `converged` wording,
    which would describe a check this tier does not run."""
    texts = gen.TEARDOWN_SEED_MOVEMENT_TEXTS
    assert texts.var_prefix == "down"
    for reason in (texts.no_identity, texts.unreadable, texts.unmoved):
        assert "no destroy is attempted" in reason.lower(), reason
        assert "converged" not in reason, reason


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs", "awscdk"))
def test_an_unmoved_seed_identity_spends_no_destroy(tmp_path: Path, arm: str) -> None:
    """THE GUARD, EXECUTED. The deployed identity is still the receipt's, so
    there is no agent-produced deployment to tear down: not_verifiable, and no
    destroy is run — destroying here would remove the seed and, with the stubs
    exiting 0, record `clean` for an agent that deployed nothing."""
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path,
        arm,
        destroy_rc=0,
        state=True,
        gating=True,
        seed_moved=False,
        destroy_stdout=_CLEAN_STDOUT[arm],
    )
    assert result["outcome"] == "not_verifiable", result
    assert "still EXACTLY the one the harness seeded" in result["reason"], result
    assert result["exit_code"] == "", (
        "the guard must fire BEFORE the destroy -- a destroy here tears down "
        "the harness's own seed"
    )
    assert reward == "0.0", (result, reward)


def test_a_receipt_without_an_identity_spends_no_destroy(tmp_path: Path) -> None:
    """FAIL-CLOSED on the missing receipt field: the verifier cannot tell the
    agent's deployment from the seed's, so it withholds the destroy rather than
    guessing."""
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path, "hcl_raw", destroy_rc=0, state=True, gating=True, no_receipt=True
    )
    assert result["outcome"] == "not_verifiable", result
    assert "carries no state_identity" in result["reason"], result
    assert result["exit_code"] == "", result


def test_the_post_synth_re_probe_aborts_the_terraconstructs_destroy(
    tmp_path: Path,
) -> None:
    """RESERVED RC 9 (§5.1's post-synth re-probe, reused here). This arm's
    state lives at /app/project/terraform.<workspace_id>.tfstate, not under
    cdktf.out/, so a synth that cleaned the stack directory would leave the
    destroy with no state at all — and an offline destroy with no state exits 0
    having removed nothing, i.e. `clean` for a trial that destroyed nothing."""
    _needs_bash_and_jq()
    result, reward = _run_teardown(
        tmp_path,
        "terraconstructs",
        destroy_rc=0,
        state=True,
        gating=True,
        synth_removes_state=True,
    )
    assert result["outcome"] == "not_verifiable", result
    assert "disappeared when the command re-synthesized" in result["reason"], result
    assert result["exit_code"] == str(gen.IDEMPOTENCE_STATE_VANISHED_RC), result
    assert reward == "0.0", (result, reward)


@pytest.mark.parametrize("arm", ("hcl_raw", "terraconstructs", "awscdk"))
def test_only_terraconstructs_carries_the_rc_9_branch(pilot: Spec, arm: str) -> None:
    """The branch rides the ONE arm whose command can raise the code, so no
    other arm's tests/test.sh moves a byte for a case it cannot reach."""
    block = gen.build_teardown_block(pilot, arm)
    branch = f'elif [ "$down_rc" -eq {gen.IDEMPOTENCE_STATE_VANISHED_RC} ]; then'
    assert (branch in block) == (arm == "terraconstructs"), block
