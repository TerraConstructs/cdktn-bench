"""generator/tests/test_workspace_seed.py — the BROWNFIELD (poisoned-workspace)
contract: specs/SCHEMA.md §2.7 + §5.1, DECISIONS.md Amendment 28.

These tests split into four groups, and each group exists because a specific
failure would otherwise be silent:

1. SCHEMA VALIDATORS — a seed that is really the empty stub, a seed whose
   comments leak the fix, a seed missing on an enabled arm, an `extra_files`
   entry fighting a `seeded_files` entry for the same path's permissions, a
   `seed_asserts` list with no `pins_catch` back-reference at all.
2. EMISSION — the seed lands verbatim (no generator banner, no `TODO(agent)`),
   WRITABLE, and the prompt says "change it" rather than "write your entire
   solution there".
3. THE MANDATORY DO-NOTHING FIXTURE — present, generator-owned, and a genuine
   no-op.
4. REGRESSION GUARANTEE — a spec with no `workspace_seed` and no
   `verifier.idempotence` generates byte-identically to before either field
   existed. This is the one that protects five already-published scenarios, so
   it is asserted against the real specs rather than a fixture.

They run offline, with no toolchain: everything here is generator-side. The
*behavioural* half (does each arm's seed actually build/plan green, do the
declared seed_asserts hold) is `make seed-parity`, which needs the real
toolchain and therefore lives in `make ci`, not in `make check`.
"""

from __future__ import annotations

import copy
import stat
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

import gen
from spec_model import Spec, load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
PILOT_SPEC = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
GREENFIELD_SPECS = [
    REPO_ROOT / "specs" / name
    for name in (
        "apigw-openapi.yaml",
        "apigw-redeploy.yaml",
        "ecs-swappiness.yaml",
        "s3-lambda-log-retention.yaml",
        "sfn-jsonata.yaml",
    )
]


@pytest.fixture(scope="module")
def pilot_raw() -> dict:
    return yaml.safe_load(PILOT_SPEC.read_text())


@pytest.fixture(scope="module")
def pilot() -> Spec:
    return load_spec(PILOT_SPEC)


def _mutated(raw: dict, mutate) -> Spec:
    """Validate a deep copy of `raw` after `mutate(copy)`. Raises ValidationError
    exactly as `load_spec` would (minus the filename-stem rule, which needs a
    real path)."""
    data = copy.deepcopy(raw)
    mutate(data)
    return Spec.model_validate(data)


# ---------------------------------------------------------------------------
# 1. schema validators
# ---------------------------------------------------------------------------


class TestSchemaValidators:
    def test_pilot_validates(self, pilot: Spec) -> None:
        assert pilot.is_brownfield()
        assert pilot.workspace_seed is not None
        for arm in pilot.arms.enabled_arms():
            assert pilot.workspace_seed.body_for(arm)

    def test_seed_body_required_for_every_enabled_arm(self, pilot_raw: dict) -> None:
        with pytest.raises(ValidationError, match="exactly one seed body per ENABLED arm"):
            _mutated(pilot_raw, lambda d: d["workspace_seed"]["entry_file"].pop("terraconstructs"))

    def test_seed_body_rejected_for_a_disabled_arm(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["arms"]["terraconstructs"] = {"enabled": False, "reason": "test"}
            d["instruction"]["per_arm"].pop("terraconstructs")
        with pytest.raises(ValidationError, match="declared-but-disabled"):
            _mutated(pilot_raw, mutate)

    def test_empty_seed_body_rejected(self, pilot_raw: dict) -> None:
        with pytest.raises(ValidationError, match="seed body must be non-empty"):
            _mutated(pilot_raw, lambda d: d["workspace_seed"]["entry_file"].update({"hcl_raw": "   \n"}))

    @pytest.mark.parametrize(
        "comment",
        [
            "# TODO(agent): rename the group\n",
            "# FIXME later\n",
            "// NOTE: watch out here\n",
            "# be careful with this one\n",
            "# gotcha: this bites\n",
            "# add create_before_destroy if you rename it\n",
            "# Generated skeleton -- generator/gen.py\n",
            "# Empty on purpose: the agent fills this in\n",
        ],
    )
    def test_seed_comment_leak_lint(self, pilot_raw: dict, comment: str) -> None:
        """A seed must read like ordinary production config. The generator's own
        skeleton banners are in the deny-list too, which is how "a workspace_seed
        spec must not ALSO ship the empty stub" is enforced mechanically."""
        with pytest.raises(ValidationError, match="comment line"):
            _mutated(
                pilot_raw,
                lambda d: d["workspace_seed"]["entry_file"].update(
                    {"hcl_raw": comment + d["workspace_seed"]["entry_file"]["hcl_raw"]}
                ),
            )

    def test_banned_token_in_real_code_is_allowed(self, pilot_raw: dict) -> None:
        """The lint is COMMENT-scoped on purpose. `create_before_destroy` as real
        HCL is what a reference solution contains; only a comment mentioning it
        leaks. A whole-file substring ban would make the fix unwritable."""
        seed = _mutated(
            pilot_raw,
            lambda d: d["workspace_seed"]["entry_file"].update(
                {
                    "hcl_raw": d["workspace_seed"]["entry_file"]["hcl_raw"]
                    + '\nresource "aws_x" "y" {\n  lifecycle {\n    create_before_destroy = true\n  }\n}\n'
                }
            ),
        )
        assert "create_before_destroy" in (seed.workspace_seed.body_for("hcl_raw") or "")

    def test_premise_required_nonempty(self, pilot_raw: dict) -> None:
        with pytest.raises(ValidationError, match="premise must be non-empty"):
            _mutated(pilot_raw, lambda d: d["workspace_seed"].update({"premise": "  "}))

    def test_at_least_one_seed_assert_pins_a_catch(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            for a in d["workspace_seed"]["seed_asserts"]:
                a.pop("pins_catch", None)
        with pytest.raises(ValidationError, match="must set `pins_catch`"):
            _mutated(pilot_raw, mutate)

    def test_pins_catch_must_name_a_declared_catch(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["workspace_seed"]["seed_asserts"][0]["pins_catch"] = "no-such-catch"
        with pytest.raises(ValidationError, match="names no declared catch"):
            _mutated(pilot_raw, mutate)

    def test_seed_assert_needs_the_jsonpath_for_every_arm_it_applies_to(
        self, pilot_raw: dict
    ) -> None:
        def mutate(d: dict) -> None:
            a = d["workspace_seed"]["seed_asserts"][0]
            a.pop("cfn_jsonpath")
        with pytest.raises(ValidationError, match="cfn_jsonpath required"):
            _mutated(pilot_raw, mutate)

    def test_extra_file_may_not_collide_with_entry_file(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["workspace_seed"]["extra_files"] = {
                "hcl_raw": [{"path": "main.tf", "content": "x = 1\n"}]
            }
        with pytest.raises(ValidationError, match="output_contract.entry_file"):
            _mutated(pilot_raw, mutate)

    def test_extra_file_may_not_collide_with_a_seeded_file(self, pilot_raw: dict) -> None:
        """0o644 vs 0o444 -- a collision is a silent permission fight, not a
        merge."""
        def mutate(d: dict) -> None:
            d["seeded_files"] = [{"path": "reference/notes.md", "content": "read me\n"}]
            d["workspace_seed"]["extra_files"] = {
                "hcl_raw": [{"path": "reference/notes.md", "content": "edit me\n"}]
            }
        with pytest.raises(ValidationError, match="collides with a seeded_files path"):
            _mutated(pilot_raw, mutate)

    @pytest.mark.parametrize("bad_path", ["/etc/passwd", "../escape.tf", "provider.tf"])
    def test_extra_file_path_rules(self, pilot_raw: dict, bad_path: str) -> None:
        def mutate(d: dict) -> None:
            d["workspace_seed"]["extra_files"] = {
                "hcl_raw": [{"path": bad_path, "content": "x = 1\n"}]
            }
        with pytest.raises(ValidationError):
            _mutated(pilot_raw, mutate)


class TestIdempotenceValidators:
    def test_pilot_opts_in(self, pilot: Spec) -> None:
        assert pilot.verifier.idempotence.enabled
        assert pilot.verifier.idempotence.gating

    def test_idempotence_requires_live_check(self, pilot_raw: dict) -> None:
        """No apply => no state => `terraform plan -detailed-exitcode` is always
        2, i.e. the tier could only ever fail every trial including a perfect
        one."""
        def mutate(d: dict) -> None:
            d["verifier"]["live_check"] = {"enabled": False}
        with pytest.raises(ValidationError, match="requires\n?\\s*verifier.live_check.enabled=true"):
            _mutated(pilot_raw, mutate)

    def test_gating_requires_enabled(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["verifier"]["idempotence"] = {"enabled": False, "gating": True}
        with pytest.raises(ValidationError, match="gating=true requires enabled=true"):
            _mutated(pilot_raw, mutate)

    def test_every_greenfield_spec_leaves_it_off(self) -> None:
        for path in GREENFIELD_SPECS:
            spec = load_spec(path)
            assert not spec.verifier.idempotence.enabled, path.name


# ---------------------------------------------------------------------------
# 2. emission
# ---------------------------------------------------------------------------


class TestSeedEmission:
    def test_entry_file_is_the_seed_body_verbatim(self, pilot: Spec) -> None:
        for arm in pilot.arms.enabled_arms():
            per_arm = getattr(pilot.instruction.per_arm, arm)
            written = (
                gen.task_dir(pilot, arm)
                / "environment"
                / gen.ARM_WORKSPACE_SUBDIR[arm]
                / per_arm.output_contract.entry_file
            ).read_text()
            expected = (pilot.workspace_seed.body_for(arm) or "").rstrip("\n") + "\n"
            assert written == expected, arm

    def test_no_generator_banner_and_no_todo_in_a_seeded_entry_file(self, pilot: Spec) -> None:
        """Design memo §7 rule 3 / Amendment 28 §3.5: those headers tell the
        agent the file is bench scaffolding, which invites meta-reasoning about
        planted traps."""
        banned = ("TODO(agent)", "Empty on purpose", "Generated skeleton", "make gen SPEC=")
        for arm in pilot.arms.enabled_arms():
            per_arm = getattr(pilot.instruction.per_arm, arm)
            text = (
                gen.task_dir(pilot, arm)
                / "environment"
                / gen.ARM_WORKSPACE_SUBDIR[arm]
                / per_arm.output_contract.entry_file
            ).read_text()
            for phrase in banned:
                assert phrase not in text, f"{arm}: {phrase!r} leaked into a seeded entry file"

    def test_seed_is_agent_writable(self, pilot: Spec) -> None:
        """0o444 here would make a legitimate agent edit fail with EACCES and
        score a CORRECT solution 0.0. This is the inverse of `seeded_files`."""
        for arm in pilot.arms.enabled_arms():
            per_arm = getattr(pilot.instruction.per_arm, arm)
            path = (
                gen.task_dir(pilot, arm)
                / "environment"
                / gen.ARM_WORKSPACE_SUBDIR[arm]
                / per_arm.output_contract.entry_file
            )
            assert path.stat().st_mode & stat.S_IWUSR, f"{arm}: seed must stay writable"

    def test_ownership_note_is_brownfield_wording(self, pilot: Spec) -> None:
        for arm in pilot.arms.enabled_arms():
            text = (gen.task_dir(pilot, arm) / "instruction.md").read_text()
            assert "holds this project's existing configuration" in text, arm
            assert "write your entire solution there" not in text, arm
            # the don't-touch clause for the bootstrap file is finding G1 and
            # must survive the rewording
            assert gen.ARM_BOOTSTRAP_FILE[arm] in text, arm

    def test_premise_sits_in_the_parity_checked_shared_prefix(self, pilot: Spec) -> None:
        """`premise` is spec-level and arm-agnostic, and is emitted BEFORE the
        per-arm language line -- so it cannot break prompt parity even in
        principle (SCHEMA.md §2.7)."""
        premise_first_line = pilot.workspace_seed.premise.strip().splitlines()[0]
        for arm in pilot.arms.enabled_arms():
            text = (gen.task_dir(pilot, arm) / "instruction.md").read_text()
            lang = getattr(pilot.instruction.per_arm, arm).language_line.strip()
            prefix = gen.shared_prefix(text, lang)
            assert premise_first_line in prefix, arm

    def test_seed_body_structural_contract_is_checked_at_generation_time(
        self, pilot_raw: dict
    ) -> None:
        no_class = _mutated(
            pilot_raw,
            lambda d: d["workspace_seed"]["entry_file"].update(
                {"awscdk": "const x = 1;\n"}
            ),
        )
        with pytest.raises(gen.SeedContractError, match="export class ScenarioStack"):
            gen.seed_entry_body(no_class, "awscdk")

        with_provider = _mutated(
            pilot_raw,
            lambda d: d["workspace_seed"]["entry_file"].update(
                {"hcl_raw": 'provider "aws" {\n  region = "us-east-1"\n}\n'}
            ),
        )
        with pytest.raises(gen.SeedContractError, match="provider"):
            gen.seed_entry_body(with_provider, "hcl_raw")

    def test_greenfield_specs_still_get_the_empty_skeleton(self) -> None:
        spec = load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")
        assert gen.seed_entry_body(spec, "hcl_raw") is None
        assert "TODO(agent)" in gen.hcl_raw_main_tf(spec)


# ---------------------------------------------------------------------------
# 3. the mandatory do-nothing fixture
# ---------------------------------------------------------------------------


class TestSeedUnchangedFixture:
    def test_present_and_executable_on_every_arm(self, pilot: Spec) -> None:
        for arm in pilot.arms.enabled_arms():
            path = (
                gen.task_dir(pilot, arm)
                / "solution"
                / "broken"
                / gen.SEED_UNCHANGED_FIXTURE
                / "solve.sh"
            )
            assert path.is_file(), f"{arm}: the do-nothing negative is MANDATORY"
            assert path.stat().st_mode & stat.S_IXUSR, arm

    def test_it_is_a_genuine_no_op(self, pilot: Spec) -> None:
        """It must not write the entry file -- the whole point is to submit the
        seed exactly as the workspace shipped it."""
        for arm in pilot.arms.enabled_arms():
            entry = getattr(pilot.instruction.per_arm, arm).output_contract.entry_file
            text = (
                gen.task_dir(pilot, arm)
                / "solution"
                / "broken"
                / gen.SEED_UNCHANGED_FIXTURE
                / "solve.sh"
            ).read_text()
            assert f"cat > {entry}" not in text, arm
            assert "tests/static_tiers.sh" in text, arm

    def test_generator_owned_so_it_cannot_be_weakened(self, pilot: Spec) -> None:
        """Unlike every other solution/** file it is OVERWRITTEN on every run.
        Rewriting it to something that passes must not survive `make gen`."""
        arm = "hcl_raw"
        path = (
            gen.task_dir(pilot, arm)
            / "solution"
            / "broken"
            / gen.SEED_UNCHANGED_FIXTURE
            / "solve.sh"
        )
        original = path.read_text()
        path.write_text("#!/usr/bin/env bash\nexit 0\n")
        try:
            gen.generate(PILOT_SPEC)
            assert path.read_text() == original
        finally:
            if path.read_text() != original:
                path.write_text(original)

    def test_absent_for_a_greenfield_spec(self) -> None:
        spec = load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")
        for arm in spec.arms.enabled_arms():
            path = (
                gen.task_dir(spec, arm)
                / "solution"
                / "broken"
                / gen.SEED_UNCHANGED_FIXTURE
            )
            assert not path.exists(), f"{arm}: greenfield specs have no seed to leave unchanged"


# ---------------------------------------------------------------------------
# 4. equipping
# ---------------------------------------------------------------------------


class TestEquippingHash:
    def test_digest_published_in_task_toml(self, pilot: Spec) -> None:
        import tomllib

        expected = gen.workspace_seed_sha256(pilot)
        assert expected is not None
        for arm in pilot.arms.enabled_arms():
            data = tomllib.loads((gen.task_dir(pilot, arm) / "task.toml").read_text())
            assert data["metadata"]["workspace_seed_sha256"] == expected, arm

    def test_digest_is_spec_wide_not_per_arm(self, pilot: Spec) -> None:
        """The three seeds are ONE equivalence claim, so editing any one must
        invalidate every arm's rows."""
        import tomllib

        digests = {
            arm: tomllib.loads((gen.task_dir(pilot, arm) / "task.toml").read_text())[
                "metadata"
            ]["workspace_seed_sha256"]
            for arm in pilot.arms.enabled_arms()
        }
        assert len(set(digests.values())) == 1, digests

    def test_digest_moves_when_any_arm_seed_changes(self, pilot_raw: dict) -> None:
        base = gen.workspace_seed_sha256(Spec.model_validate(copy.deepcopy(pilot_raw)))
        changed = gen.workspace_seed_sha256(
            _mutated(
                pilot_raw,
                lambda d: d["workspace_seed"]["entry_file"].update(
                    {"awscdk": d["workspace_seed"]["entry_file"]["awscdk"] + "\n// x\n"}
                ),
            )
        )
        assert base != changed

    def test_folded_into_extra_cfg_by_compute_equipping_hash(self, pilot: Spec) -> None:
        """The channel a caller can forget is the channel that WILL be forgotten
        -- so equipping.py reads task.toml itself rather than trusting callers.
        Proven by hashing the same task dir with and without the key present."""
        from gates.equipping import WORKSPACE_SEED_KEY, compute_equipping_hash

        task = gen.task_dir(pilot, "hcl_raw")
        image = "cdktn-bench/hcl-raw@sha256:" + "0" * 64
        with_key = compute_equipping_hash(task, image, {})
        # Passing the same value explicitly must be a no-op (not a conflict).
        digest = gen.workspace_seed_sha256(pilot)
        assert compute_equipping_hash(task, image, {WORKSPACE_SEED_KEY: digest}) == with_key
        # A caller claiming a DIFFERENT seed is a refusal, never a guess.
        with pytest.raises(ValueError, match="refusing to guess"):
            compute_equipping_hash(task, image, {WORKSPACE_SEED_KEY: "deadbeef"})

    def test_greenfield_task_hash_is_untouched(self) -> None:
        """No HASH_SCHEME_VERSION bump, no already-published hash moves: a
        greenfield task.toml simply has no such key, so the manifest is
        byte-identical to what it was."""
        import hashlib
        import json

        from gates.equipping import HASH_SCHEME_VERSION, compute_equipping_hash

        spec = load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")
        task = gen.task_dir(spec, "hcl_raw")
        image = "cdktn-bench/hcl-raw@sha256:" + "1" * 64
        manifest = {
            "hash_scheme_version": HASH_SCHEME_VERSION,
            "equipping_files": [],
            "image_ref": image,
            "image_digest": image,
            "extra_cfg": {},
            "instruction_md_sha256": hashlib.sha256(
                (task / "instruction.md").read_bytes()
            ).hexdigest(),
        }
        expected = hashlib.sha256(
            json.dumps(manifest, sort_keys=True, separators=(",", ":")).encode()
        ).hexdigest()
        assert compute_equipping_hash(task, image, {}) == expected


# ---------------------------------------------------------------------------
# 5. regression guarantee for every spec that predates this feature
# ---------------------------------------------------------------------------


class TestGreenfieldRegressionGuarantee:
    @pytest.mark.parametrize("path", GREENFIELD_SPECS, ids=lambda p: p.stem)
    def test_no_workspace_seed_and_no_idempotence(self, path: Path) -> None:
        spec = load_spec(path)
        assert not spec.is_brownfield()
        assert not spec.verifier.idempotence.enabled

    @pytest.mark.parametrize("path", GREENFIELD_SPECS, ids=lambda p: p.stem)
    def test_test_sh_carries_no_idempotence_block(self, path: Path) -> None:
        """`build_test_sh` is one static template shared by every task. The
        idempotence tier is GENERATION-conditional (not a dead runtime branch)
        precisely so an always-emitted block cannot move these bytes."""
        spec = load_spec(path)
        for arm in spec.arms.enabled_arms():
            text = gen.build_test_sh(spec, arm)
            assert "SPEC_IDEMPOTENCE_ENABLED" not in text, f"{path.stem}/{arm}"
            assert gen.build_idempotence_block(spec, arm) == ""

    @pytest.mark.parametrize("path", GREENFIELD_SPECS, ids=lambda p: p.stem)
    def test_task_toml_carries_no_seed_digest(self, path: Path) -> None:
        spec = load_spec(path)
        assert gen.workspace_seed_sha256(spec) is None
        for arm in spec.arms.enabled_arms():
            assert "workspace_seed_sha256" not in (
                gen.task_dir(spec, arm) / "task.toml"
            ).read_text()

    def test_idempotence_block_replaces_exactly_one_blank_line(self) -> None:
        """The mechanism behind the byte-identity claim, pinned directly: the
        placeholder occupies the blank line that separates the live-check block
        from `exit $rc`, and an empty replacement restores it."""
        spec = load_spec(REPO_ROOT / "specs" / "ecs-swappiness.yaml")
        text = gen.build_test_sh(spec, "hcl_raw")
        assert text.endswith("fi\n\nexit $rc\n")


class TestIdempotenceEmission:
    @pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs"])
    def test_block_emitted_for_the_opted_in_spec(self, pilot: Spec, arm: str) -> None:
        text = (gen.task_dir(pilot, arm) / "tests" / "test.sh").read_text()
        assert "SPEC_IDEMPOTENCE_ENABLED" in text
        assert "SPEC_IDEMPOTENCE_GATING" in text
        assert "/logs/verifier/idempotence-result.json" in text
        assert gen.IDEMPOTENCE_COMMAND[arm].replace(
            "__WORKSPACE_ID__", pilot.workspace_identity()
        ) in text

    def test_awscdk_uses_cdk_diff_not_a_second_synth(self, pilot: Spec) -> None:
        """A second synth + template self-diff is vacuous by construction (CDK
        synth is deterministic) and would silently hand this arm a free pass."""
        text = (gen.task_dir(pilot, "awscdk") / "tests" / "test.sh").read_text()
        assert "cdk diff --fail" in text
        assert "cdk synth" not in gen.IDEMPOTENCE_COMMAND["awscdk"]

    @pytest.mark.parametrize("arm", ["hcl_raw", "terraconstructs"])
    def test_no_state_is_skipped_with_a_reason_never_fake_passed(
        self, pilot: Spec, arm: str
    ) -> None:
        """OFFLINE (and for an agent that never deployed) an unconditional plan
        would exit 2 and read as a genuine `pending_changes` verdict. The probe
        makes it `not_verifiable` WITH a reason instead.

        TF arms only, and deliberately so: `awscdk` keeps no local state, so it
        cannot have a file probe. Its half of the SAME guarantee is
        `test_awscdk_never_deployed_is_skipped_with_a_reason` below — and the
        two together are what SCHEMA.md §5.1 / Amendment 28 §4 promise. An
        earlier revision of this class parametrized only these two arms and
        stopped there, which is exactly how `awscdk` came to record an
        unresolvable AWS environment as a genuine `pending_changes` verdict.
        """
        text = (gen.task_dir(pilot, arm) / "tests" / "test.sh").read_text()
        probe = gen.IDEMPOTENCE_STATE_PROBE[arm].replace(
            "__WORKSPACE_ID__", pilot.workspace_identity()
        )
        assert f'[ ! -s "/app/project/{probe}" ]' in text
        assert "An offline plan with no state ALWAYS reports pending changes" in text
        assert 'idem_outcome="not_verifiable"' in text

    def test_awscdk_never_deployed_is_skipped_with_a_reason(self, pilot: Spec) -> None:
        """The `awscdk` half of the same guarantee, via a different mechanism.

        `cdk diff --fail` exits 1 BOTH for "the diff found changes" and for "the
        CLI failed before diffing anything", and this arm keeps no local state
        file to pre-flight probe. Believing the bare exit code reports "the
        deployed state still differs from the configuration" for a run that
        never reached AWS.

        MEASURED against the arm's exact pin (aws-cdk 2.1135.0, an exact
        version in arms/awscdk/environment/workspace/package.json) with
        credentials unresolvable: exit 1, "no credentials have been
        configured", and NO marker on stdout. `cdk-toolkit.js` prints the
        marker unconditionally on the line before
        `return diffs && options.fail ? 1 : 0`, so it is present on every
        completed diff and absent on every early error exit.

        The exit code is therefore believed ONLY when the marker is also
        present; every other exit-1 falls through to not_verifiable.
        """
        text = (gen.task_dir(pilot, "awscdk") / "tests" / "test.sh").read_text()
        marker = gen.IDEMPOTENCE_COMPLETION_MARKER["awscdk"]
        assert marker, "the awscdk arm has no other never-deployed guard"
        assert gen.IDEMPOTENCE_STATE_PROBE["awscdk"] == "", (
            "this arm keeps no local state; a file probe here would be a "
            "guard that can never fire"
        )
        # The pending verdict is gated on the marker, not on the exit code alone.
        pending_rc = gen.IDEMPOTENCE_PENDING_RC["awscdk"]
        assert (
            f'elif [ "$idem_rc" -eq {pending_rc} ] \\\n'
            f"               && grep -qF '{marker}' "
            f"/logs/verifier/idempotence.log; then" in text
        ), text
        # ...and the fall-through says WHY, rather than silently mapping to a
        # verdict about deployed reality that was never observed.
        assert "without printing its own completion marker" in text
        assert "Offline this is ALWAYS the outcome" in text

    def test_every_arm_has_exactly_one_never_deployed_guard(self, pilot: Spec) -> None:
        """The invariant behind the two tests above, stated once so a future arm
        cannot be added with neither guard (which fails open into a fake
        `pending_changes`) or with both (ambiguous ownership)."""
        for arm in pilot.arms.enabled_arms():
            probe = bool(gen.IDEMPOTENCE_STATE_PROBE[arm])
            marker = bool(gen.IDEMPOTENCE_COMPLETION_MARKER[arm])
            assert probe != marker, (
                f"{arm}: exactly one never-deployed guard is required "
                f"(pre-flight state probe XOR post-flight completion marker); "
                f"got probe={probe}, marker={marker}"
            )

    def test_gating_is_fail_closed(self, pilot: Spec) -> None:
        text = (gen.task_dir(pilot, "hcl_raw") / "tests" / "test.sh").read_text()
        assert '[ "$idem_outcome" != "converged" ]' in text
        assert 'echo "0.0" > /logs/verifier/reward.txt' in text

    def test_task_toml_env_carries_both_flags(self, pilot: Spec) -> None:
        for arm in pilot.arms.enabled_arms():
            text = (gen.task_dir(pilot, arm) / "task.toml").read_text()
            assert 'SPEC_IDEMPOTENCE_ENABLED = "true"' in text, arm
            assert 'SPEC_IDEMPOTENCE_GATING = "true"' in text, arm
            assert 'SPEC_LIVE_CHECK_ENABLED = "true"' in text, arm


# ---------------------------------------------------------------------------
# 5. BROWNFIELD PROMPT SURFACE — the hostile read, done mechanically
#
# Added after a verifier found the pilot's scenario `title` ("Rename an
# explicitly-named, in-use security group and roll it out") stamped into
# `bin/app.ts`'s CFN description and `main.ts`'s header comment -- naming BOTH
# halves of the poison this spec's own seed_asserts declare, on two of three
# arms, while hcl_raw's workspace (whose entry file IS the seed, so it carries
# no generator header) stayed clean. An ARM-ASYMMETRIC hint does not just make
# the task easier; it biases the cross-arm number the scenario exists to
# produce.
#
# The author's hostile self-check covered "the seeds and the instruction" and
# the leak was in neither -- it was in a generator-stamped skeleton. So the unit
# scanned here is EVERY BYTE THE DOCKERFILE COPYs, plus the prompt, for EVERY
# brownfield spec -- not the files an author remembers writing.
# ---------------------------------------------------------------------------

# Discovered, not listed: a brownfield spec added later is scanned automatically.
# `split.yaml` is train/holdout metadata, not a spec (mk/gen.mk skips it the
# same way).
ALL_SPECS = [
    p for p in sorted((REPO_ROOT / "specs").glob("*.yaml")) if p.name != "split.yaml"
]
BROWNFIELD_SPECS = [p for p in ALL_SPECS if load_spec(p).is_brownfield()]
# The stepless GREENFIELD control used to prove an allowlist entry is really
# shared arm-image boilerplate (same discipline as
# test_multistep_emission.py::test_environment_boilerplate_is_really_boilerplate).
CONTROL_SPEC = REPO_ROOT / "specs" / "sfn-jsonata.yaml"

# Vocabulary that NAMES THE MECHANISM rather than asking for the change
# (SCHEMA.md §2.7 prompt rules 3-5, Amendment 28 §3). Regexes, so word
# boundaries can keep "bootstrap" from matching "trap" and "named-resource-
# replacement" from matching "replacement".
#
# NOTE what is deliberately ABSENT: "rename", "security group", "naming
# convention", "deploy". Those are the CHANGE REQUEST, which the prompt is
# supposed to state plainly. Banning them would ban the scenario.
MECHANISM_PATTERNS = (
    r"create[ _-]?before[ _-]?destroy",
    r"\blifecycle\b",
    r"\bperpetual\b",
    r"flip[ -]?flop",
    r"\breplacements?\b",
    r"\breplaced?\b",
    r"\breplacing\b",
    r"\bre-?creat(e|es|ed|ing|ion)\b",
    r"\bin[- ]use\b",
    r"\bexplicitly[- ]named\b",
    r"\bname (collision|conflict)\b",
    r"\balready exists\b",
    r"\bfind the bug\b",
    r"\bfix the (bug|mistake)\b",
    r"\breview this (config|configuration)\b",
    r"\bpitfalls?\b",
    r"\bgotchas?\b",
    r"\btraps?\b",
    r"\blatent\b",
    r"\bpoisoned?\b",
    r"\bbrownfield\b",
    r"\bseed_asserts?\b",
    r"\bworkspace_seed\b",
)

# Phrases scrubbed before scanning, each of which must be PROVEN boilerplate by
# `test_brownfield_allowlist_is_really_boilerplate` below -- i.e. it must also
# appear under a stepless greenfield task's environment/, which makes it text
# written before this scenario existed and therefore incapable of encoding its
# trap. Keep this list minimal: it is the one place a real leak could hide.
# Empty is the correct state whenever no arm ships text that trips
# MECHANISM_PATTERNS: an entry earns its place only by appearing in a
# greenfield control's own environment/, and one that no longer does is a
# scenario-specific scrub in disguise, so it is deleted rather than kept.
BROWNFIELD_BOILERPLATE: tuple[str, ...] = ()

# Machine-generated; package names/versions are not authored text.
BROWNFIELD_SCAN_EXCLUDE = {"package-lock.json"}


def _brownfield_scrub(text: str, spec: Spec) -> str:
    """Remove the strings that contain a banned substring for reasons unrelated
    to the trap.

    THE SPEC ID IS NOT ONE OF THEM -- and used to be. This function opened with

        out = out.replace(spec.id, "<scenario-id>")

    on the reasoning that "every generated header cites the id and a `make gen`
    invocation needs it", which sounds procedural and is in fact a hole the
    exact size of the leak this whole module exists to catch: the pilot's id is
    `named-resource-replacement`, `MECHANISM_PATTERNS` bans `\\breplacements?\\b`,
    and the id was stamped into `main.ts`'s ScenarioStack id + gridUUID and into
    `bin/app.ts`'s header on two of three arms. The scrub deleted it before the
    deny-list ever saw it, and `test_the_leak_is_symmetric_across_arms` then
    compared three empty sets.

    The exemption is now an ASSERTION instead (Amendment 28 addendum): the
    agent-visible identity is `Spec.workspace_identity()` (§0.1), it is
    deny-list-checked by
    `spec_model.Spec._agent_visible_identity_is_deny_list_clean` at load time,
    and it -- not `id` -- is what the generator stamps. So the scrub removes
    `workspace_id`, whose cleanliness is guaranteed by a validator, and lets
    every `id` byte through to the deny-list.
    """
    out = text.lower()
    wid = spec.workspace_identity().lower()
    out = out.replace(wid, "<workspace-id>")
    out = out.replace(wid.replace("-", "_"), "<workspace-id>")
    for phrase in BROWNFIELD_BOILERPLATE:
        out = out.replace(phrase, "<arm-boilerplate>")
    return out


def _mechanism_leaks(text: str, spec: Spec) -> list[str]:
    import re

    scrubbed = _brownfield_scrub(text, spec)
    return [p for p in MECHANISM_PATTERNS if re.search(p, scrubbed)]


def _agent_readable_files(spec: Spec, arm: str):
    """Every file the agent can read on turn one: the whole `environment/` tree
    (the arm Dockerfile COPYs it into the image) plus the prompt."""
    root = gen.task_dir(spec, arm)
    for path in sorted((root / "environment").rglob("*")):
        if path.is_file() and path.name not in BROWNFIELD_SCAN_EXCLUDE:
            yield path
    for name in ("instruction.md",):
        if (root / name).is_file():
            yield root / name
    for path in sorted(root.glob("steps/*/instruction.md")):
        yield path


@pytest.mark.skipif(not BROWNFIELD_SPECS, reason="no brownfield spec in the corpus")
class TestBrownfieldPromptSurface:
    @pytest.mark.parametrize("path", BROWNFIELD_SPECS, ids=lambda p: p.stem)
    def test_title_never_reaches_the_agent(self, path: Path) -> None:
        """THE regression pin for the leak that was found.

        Verbatim, not vocabulary: this fails on the literal `title` string
        appearing anywhere the agent can read, whatever words that title
        happens to contain. It therefore cannot rot as later brownfield specs
        invent new ways to describe their change -- unlike a deny-list, which
        only ever knows the leaks someone already thought of.
        """
        spec = load_spec(path)
        title = spec.title.strip()
        for arm in spec.arms.enabled_arms():
            for file in _agent_readable_files(spec, arm):
                assert title.lower() not in file.read_text(errors="ignore").lower(), (
                    f"{file.relative_to(REPO_ROOT)} contains the scenario title "
                    f"{title!r} verbatim. A brownfield title describes the CHANGE "
                    f"and usually names the trapped property with it; everything "
                    f"under environment/ is COPY'd into the agent image "
                    f"(SCHEMA.md §0.1). Declare a neutral `workspace_title` that "
                    f"says only what the workspace already IS."
                )

    @pytest.mark.parametrize("path", BROWNFIELD_SPECS, ids=lambda p: p.stem)
    def test_agent_readable_files_name_no_mechanism(self, path: Path) -> None:
        """The deny-list half: no file the agent reads may name the mechanism
        that fixes the trap, nor the properties of the config that carry it
        (SCHEMA.md §2.7 prompt rules 3-5).

        Scans `environment/` AND the prompt for every enabled arm, so a leak
        cannot hide in the arm the author did not open.
        """
        spec = load_spec(path)
        for arm in spec.arms.enabled_arms():
            for file in _agent_readable_files(spec, arm):
                leaked = _mechanism_leaks(file.read_text(errors="ignore"), spec)
                assert not leaked, (
                    f"{file.relative_to(REPO_ROOT)} names the pitfall mechanism "
                    f"{leaked}. The prompt asks for the CHANGE; the trap must be "
                    f"discovered from the configuration, not announced "
                    f"(SCHEMA.md §2.7, Amendment 28 §3)."
                )

    @pytest.mark.parametrize("path", BROWNFIELD_SPECS, ids=lambda p: p.stem)
    def test_the_leak_is_symmetric_across_arms(self, path: Path) -> None:
        """Arm asymmetry is the part that corrupts the MEASUREMENT, so it gets
        its own assertion rather than riding on the two above.

        The original leak reached awscdk and terraconstructs but not hcl_raw --
        precisely because hcl_raw's entry file is the seed and carries no
        generator header. Two arms handed a hint the third lacks does not just
        make the task easier; it biases the cross-arm comparison this whole
        benchmark produces. Checked as a set equality so it fails loudly even
        if a future deny-list gap lets the same token through on all three.
        """
        spec = load_spec(path)
        per_arm = {}
        for arm in spec.arms.enabled_arms():
            found: set[str] = set()
            for file in _agent_readable_files(spec, arm):
                found.update(_mechanism_leaks(file.read_text(errors="ignore"), spec))
            per_arm[arm] = found
        distinct = {frozenset(v) for v in per_arm.values()}
        assert len(distinct) == 1, (
            f"mechanism vocabulary differs per arm: "
            f"{ {a: sorted(v) for a, v in per_arm.items()} }. An arm-asymmetric "
            f"hint biases the cross-arm comparison (Amendment 28 §3 rule 7)."
        )

    @pytest.mark.parametrize("path", BROWNFIELD_SPECS, ids=lambda p: p.stem)
    def test_workspace_title_is_declared_and_is_not_the_title(self, path: Path) -> None:
        """The schema-side half, pinned against the real spec: a brownfield spec
        must OVERRIDE the header rather than inherit `title` by omission
        (`Spec._workspace_title_required_where_header_is_prompt_surface`)."""
        spec = load_spec(path)
        assert (spec.workspace_title or "").strip()
        assert spec.workspace_header() == spec.workspace_title
        assert spec.workspace_header() != spec.title

    def test_brownfield_allowlist_is_really_boilerplate(self) -> None:
        """Keeps BROWNFIELD_BOILERPLATE honest.

        Every allowlisted phrase must also occur under a stepless GREENFIELD
        task's `environment/`, which proves it is shared arm-image text rather
        than this scenario's own words smuggled onto the allowlist to silence
        the scan above.
        """
        control = load_spec(CONTROL_SPEC)
        assert not control.is_brownfield(), "control spec must be greenfield"
        corpus = "\n".join(
            p.read_text(errors="ignore")
            for arm in control.arms.enabled_arms()
            for p in (gen.task_dir(control, arm) / "environment").rglob("*")
            if p.is_file() and p.name not in BROWNFIELD_SCAN_EXCLUDE
        ).lower()
        for phrase in BROWNFIELD_BOILERPLATE:
            assert phrase in corpus, (
                f"{phrase!r} is allowlisted as arm boilerplate but does not "
                f"appear in the greenfield control spec {control.id!r}'s "
                f"environment/ — it is scenario-specific text and must not be "
                f"scrubbed"
            )

    def test_the_scan_would_have_caught_the_original_leak(self) -> None:
        """A deny-list nobody ever saw fail is a deny-list nobody can trust.

        Replays the exact bytes the verifier found -- the CFN `description` line
        emitted into `bin/app.ts` from the pilot's original title -- and
        requires the scan to reject them.
        """
        spec = load_spec(BROWNFIELD_SPECS[0])
        original = (
            '    description: "Rename an explicitly-named, in-use security '
            'group and roll it out",'
        )
        assert _mechanism_leaks(original, spec), (
            "the mechanism deny-list no longer rejects the leak it was written "
            "for — it has been weakened"
        )

    @staticmethod
    def _brownfield_spec_whose_id_names_a_mechanism() -> Spec:
        """A brownfield spec whose own `id` carries deny-listed vocabulary.

        Prefers a real corpus spec (today: `named-resource-replacement`). Falls
        back to overriding the pilot's id onto whatever brownfield spec is
        available, so the scrub is always exercised with an id that HAS
        something to leak — never skipped, never index-dependent.
        """
        for path in BROWNFIELD_SPECS:
            candidate = load_spec(path)
            if _mechanism_leaks(candidate.id, candidate):
                return candidate
        return load_spec(BROWNFIELD_SPECS[0]).model_copy(
            update={"id": "named-resource-replacement"}
        )

    def test_the_scan_would_have_caught_the_spec_id_stamping(self) -> None:
        """The SECOND leak of the same shape, and the reason `_brownfield_scrub`
        no longer exempts the scenario id.

        The first version of this class scrubbed `spec.id` before scanning, so
        the pilot's `named-resource-replacement` -- which contains the banned
        `replacement` outright -- was invisible to it even while sitting in the
        agent's own `main.ts` on two of three arms. Reconstructed here as the
        exact pre-fix bytes `terraconstructs_main_ts()` used to emit, plus the
        awscdk header line, and required to FAIL the scan.

        This is the regression test the verifier asked for: it fails against
        the old scrub and passes against the new one, so the fix cannot be
        undone silently.

        THE SPEC IS CHOSEN, NOT INDEXED (fixed 2026-08-26, when the second
        brownfield spec `lambda-alias-tracks-unpublished-latest` landed). This
        used to read `load_spec(BROWNFIELD_SPECS[0])` on the unstated assumption
        that entry 0 is the pilot, whose id `named-resource-replacement`
        contains the banned `replacement` outright. `BROWNFIELD_SPECS` is
        sorted, so a later spec with a DENY-CLEAN id took position 0 and this
        test began failing for a reason that had nothing to do with the scrub:
        an id with nothing to leak cannot demonstrate that the scrub stopped
        hiding leaks. The observable being pinned needs a spec whose `.id`
        would leak, so one is selected by that property — and synthesised from
        the pilot's id if the corpus ever stops containing one, because a
        regression test that quietly becomes unrunnable is the same defect this
        module exists to catch.
        """
        spec = self._brownfield_spec_whose_id_names_a_mechanism()
        pre_fix_stamping = (
            f'new ScenarioStack(app, "{spec.id}", {{\n'
            f'  environmentName: "cdktn-bench",\n'
            f'  gridUUID: "{spec.id}",\n'
            f" * Generated entrypoint -- generator/gen.py, from "
            f"specs/{spec.id}.yaml."
        )
        assert _mechanism_leaks(pre_fix_stamping, spec), (
            "the scan no longer rejects the scenario id stamped into "
            "environment/. `_brownfield_scrub` has re-acquired an id exemption "
            "— which is exactly how this leak survived the first fix "
            "(SCHEMA.md §0.1 workspace_id, Amendment 28 addendum)."
        )
        # ...and the identity that REPLACED it must be clean, or the fix merely
        # moved the leak into a new field.
        assert not _mechanism_leaks(spec.workspace_identity(), spec)

    @pytest.mark.parametrize("path", BROWNFIELD_SPECS, ids=lambda p: p.stem)
    def test_task_toml_splits_the_safe_header_from_the_full_title(
        self, path: Path
    ) -> None:
        """Defence in depth, on the one non-`environment/` copy of the title.

        `task.toml` is host-side (Harbor uploads no task file into the agent
        environment), so this is not a live leak -- but "it's only metadata" is
        exactly the reasoning that put the arc into the agent's own `main.tf`
        once already. `[task] description` therefore carries `workspace_header()`
        and the full title lives in `[metadata] scenario_title`, where a
        results viewer can still find it.
        """
        import tomllib

        spec = load_spec(path)
        for arm in spec.arms.enabled_arms():
            raw = (gen.task_dir(spec, arm) / "task.toml").read_text()
            cfg = tomllib.loads(raw)
            assert spec.workspace_header() in cfg["task"]["description"], arm
            assert spec.title not in cfg["task"]["description"], arm
            assert cfg["metadata"]["scenario_title"] == spec.title, arm
