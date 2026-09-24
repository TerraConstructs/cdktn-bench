"""generator/tests/test_hcl_modules_arm.py — the `hcl_modules` arm's schema and
plumbing: specs/SCHEMA.md §1/§3, DECISIONS.md Amendment 46 (the arm reintroduced,
gated per spec, closing ROADMAP open decision 4).

1. THE DEFAULT — a spec that says nothing about the arm has it disabled, and
   its default `reason` states the gap, so no spec edit is what keeps the rest
   of the corpus generating byte-identically. `ARM_SPEC_IDS` below is the
   enumerated exception; a spec may also refuse the arm in writing.
2. ENABLING — the same shape terraconstructs takes (per-arm instruction entry
   required in both directions) PLUS a catch that applies there, since the
   default `applies_to` would leave the arm with no negative fixture; generates
   a task. A BROWNFIELD spec still cannot: no arm-specific seed body exists.
3. THE CLOSED ENUMS — one arm added to `Arm` and forgotten in one of the five
   places that key off it (`docs/design/tf-modules-arm.md` §3) is a KeyError deep
   in a generation run, so the coverage is asserted here instead.
4. THE TIER COLUMN — `predicted_tier_caught.hcl_modules_override` is validated
   like `terraconstructs_override`, including the teardown-tier rule.
"""

from __future__ import annotations

import copy
from pathlib import Path
from typing import get_args

import pytest
import yaml
from pydantic import ValidationError

import gen
from gates.audit import ARM_TOKEN_PATTERNS
from shards import ARM_ORDER
from spec_model import HCL_MODULES_DEFAULT_REASON, Arm, Spec, load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
# The GREENFIELD spec every mutation test below starts from. It must be one the
# arm is SILENT on, because the mutations are what add the arm block and the
# per-arm entry; a spec that already enables the arm cannot show the refusals.
# `workspace_seed.entry_file` has no `hcl_modules` field, so a brownfield spec
# cannot enable the arm until its per-arm seeds are authored --
# `test_a_brownfield_spec_cannot_enable_it_yet` pins that refusal.
GREENFIELD_SPEC = REPO_ROOT / "specs" / "ecr-repo-destroy-force-delete.yaml"
BROWNFIELD_SPEC = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
ALL_SPEC_PATHS = sorted(
    [p for p in (REPO_ROOT / "specs").glob("*.yaml") if p.name != "split.yaml"]
    + list((REPO_ROOT / "specs" / "_toy").glob("*.yaml"))
)


@pytest.fixture(scope="module")
def greenfield_raw() -> dict:
    return yaml.safe_load(GREENFIELD_SPEC.read_text())


def _mutated(raw: dict, mutate) -> Spec:
    d = copy.deepcopy(raw)
    mutate(d)
    return Spec.model_validate(d)


def _per_arm_block(raw: dict) -> dict:
    """A `per_arm.hcl_modules` entry copied from the spec's own hcl_raw entry:
    the arm authors the same `.tf` files, so the same output contract holds."""
    return copy.deepcopy(raw["instruction"]["per_arm"]["hcl_raw"])


def _enable(d: dict, *, with_a_catch: bool = True) -> None:
    """The three edits enabling the arm takes -- the arm block, the per-arm
    instruction entry, and at least one catch that can happen there. Omitting
    the third is `test_an_arm_with_no_catch_is_refused`'s subject."""
    d["arms"]["hcl_modules"] = {"enabled": True, "reason": "a composition trap"}
    d["instruction"]["per_arm"]["hcl_modules"] = _per_arm_block(d)
    if with_a_catch:
        d["catches"][0]["applies_to"] = ["hcl_raw", "hcl_modules"]


# ---------------------------------------------------------------------------
# 1. the default
# ---------------------------------------------------------------------------


# Every scenario admitted to the arm, enumerated rather than discovered: the
# admission is a decision per scenario (docs/adding-scenarios.md §6.3 -- a
# composition trap, a measured module fit, and a per-catch red-green verdict),
# so a spec that gained the arm by a copy-paste edit must turn this list red.
# The three phase-5 pilots first, then phase 6 slice A.
ARM_SPEC_IDS = frozenset({
    "acm-dns-validation-record-wiring",
    "iam-managed-policy-exclusive-vs-attachment",
    "s3-bucket-hardening-decomposition",
    "apigw-openapi",
    "apigwv2-route-settings-zero-vs-unset",
    "asg-launch-template-tag-propagation",
    "caller-identity-arn-as-principal",
    "ddb-gsi-attribute-definitions",
    "ecs-swappiness",
    "lambda-log-group-ownership-and-retention",
    "s3-lambda-log-retention",
    "s3-notification-custom-resource-tax",
    "sfn-jsonata",
})


@pytest.mark.parametrize("path", ALL_SPEC_PATHS, ids=lambda p: p.stem)
def test_only_the_admitted_specs_enable_the_arm(path: Path) -> None:
    spec = load_spec(path)
    expected = spec.id in ARM_SPEC_IDS
    assert spec.arms.hcl_modules.enabled is expected
    assert ("hcl_modules" in spec.arms.enabled_arms()) is expected


@pytest.mark.parametrize("path", ALL_SPEC_PATHS, ids=lambda p: p.stem)
def test_the_reason_holds_in_both_directions(path: Path) -> None:
    """SCHEMA.md §1's rule is a reason either way, so the assertion keys off
    PRESENCE of the block, not off admission: a spec that WRITES
    `enabled: false` states why the arm was considered and refused (the trap is
    not a composition trap), which is a different and more useful fact than the
    silence `HCL_MODULES_DEFAULT_REASON` stands in for."""
    raw = yaml.safe_load(path.read_text())
    spec = load_spec(path)
    if "hcl_modules" in raw["arms"]:
        assert raw["arms"]["hcl_modules"]["reason"].strip()
        assert spec.arms.hcl_modules.reason != HCL_MODULES_DEFAULT_REASON
        return
    assert spec.id not in ARM_SPEC_IDS
    assert spec.arms.hcl_modules.reason == HCL_MODULES_DEFAULT_REASON


def test_a_refusal_states_its_own_reason(greenfield_raw: dict) -> None:
    """The one shape the presence-keyed rule above admits that the old
    membership-keyed one refused: `enabled: false` WITH a reason, which is a
    different and more useful fact than silence. No shipped spec carries that
    shape right now, so it is pinned as a mutation rather than by name."""
    spec = _mutated(greenfield_raw, lambda d: d["arms"].update(
        {"hcl_modules": {"enabled": False, "reason": "the trap has no module path"}}
    ))
    assert spec.arms.hcl_modules.enabled is False
    assert spec.arms.hcl_modules.reason != HCL_MODULES_DEFAULT_REASON


def test_default_reason_names_the_gap() -> None:
    assert "docs/design/tf-modules-arm.md" in HCL_MODULES_DEFAULT_REASON


def test_an_empty_reason_is_refused(greenfield_raw: dict) -> None:
    with pytest.raises(ValidationError, match="reason is required in both directions"):
        _mutated(greenfield_raw, lambda d: d["arms"].update(
            {"hcl_modules": {"enabled": False, "reason": "  "}}
        ))


# ---------------------------------------------------------------------------
# 2. enabling
# ---------------------------------------------------------------------------


class TestEnabling:
    def test_enabled_requires_a_per_arm_entry(self, greenfield_raw: dict) -> None:
        with pytest.raises(ValidationError, match="instruction.per_arm.hcl_modules is missing"):
            _mutated(greenfield_raw, lambda d: d["arms"].update(
                {"hcl_modules": {"enabled": True, "reason": "pilot composition trap"}}
            ))

    def test_a_per_arm_entry_without_the_arm_is_refused(self, greenfield_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["instruction"]["per_arm"]["hcl_modules"] = _per_arm_block(d)

        with pytest.raises(ValidationError, match="arms.hcl_modules.enabled is false"):
            _mutated(greenfield_raw, mutate)

    def test_the_full_shape_validates_and_enables(self, greenfield_raw: dict) -> None:
        spec = _mutated(greenfield_raw, _enable)
        assert spec.arms.enabled_arms()[-1] == "hcl_modules"

    def test_an_arm_with_no_catch_is_refused(self, greenfield_raw: dict) -> None:
        """`Catch.applies_to` defaults to the three ORIGINAL arms, so enabling a
        fourth and stopping there produces a task whose only graded fixture is
        its own reference: `gates/oracle_falsifiability.py` reports every catch
        `N/A` for that arm and exits 0. Refused at spec load instead."""
        with pytest.raises(ValidationError, match="no catch lists it in applies_to"):
            _mutated(greenfield_raw, lambda d: _enable(d, with_a_catch=False))

    def test_a_brownfield_spec_cannot_enable_it_yet(self) -> None:
        """A seed body per enabled arm is mandatory (SCHEMA.md §2.7), and the arm
        has no hand-authored, plan-green module-based seed — so the refusal names
        the missing seed rather than generating a greenfield workspace whose
        siblings start from working config."""
        raw = yaml.safe_load(BROWNFIELD_SPEC.read_text())

        with pytest.raises(ValidationError, match=r"missing \['hcl_modules'\]"):
            _mutated(raw, _enable)

    def test_a_pending_arm_refuses_with_a_sentence(self, greenfield_raw: dict) -> None:
        """`ARMS_PENDING_IMAGE` is empty now that every arm has its writers, but
        it stays the shape a FIFTH arm is introduced through: listed there, it
        refuses with a sentence instead of failing as a KeyError halfway through
        a generation run that has already written half a task dir."""
        spec = _mutated(greenfield_raw, _enable)
        monkeypatched = frozenset({"hcl_modules"})
        original, gen.ARMS_PENDING_IMAGE = gen.ARMS_PENDING_IMAGE, monkeypatched
        try:
            with pytest.raises(NotImplementedError, match="no per-arm writers"):
                gen.generate_arm(spec, "hcl_modules")
        finally:
            gen.ARMS_PENDING_IMAGE = original


# ---------------------------------------------------------------------------
# 3. the closed enums
# ---------------------------------------------------------------------------


class TestEnumSites:
    def test_every_arm_has_an_entry_at_every_enum_site(self) -> None:
        """The five sites `docs/design/tf-modules-arm.md` §3 names. The remaining
        `dict[Arm, ...]` maps in gen.py describe an arm's toolchain commands and
        are filled when its image exists (phase 4), which the generation refusal
        above is what protects."""
        arms = set(get_args(Arm))
        assert set(gen.ARM_DIRNAME) == arms
        assert set(gen.ARM_WORKSPACE_SUBDIR) == arms
        assert set(ARM_ORDER) == arms
        assert {gen.ARM_DIRNAME[a] for a in arms} == set(ARM_TOKEN_PATTERNS)

    def test_the_arm_is_appended_to_the_shard_order(self) -> None:
        """`ARM_ORDER.index(arm)` is the shard offset: inserting an arm anywhere
        but the end moves every later arm's task to a different AWS account."""
        assert ARM_ORDER[:3] == ("awscdk", "hcl_raw", "terraconstructs")
        assert ARM_ORDER[-1] == "hcl_modules"

    def test_the_audit_patterns_are_the_terraform_ones(self) -> None:
        assert ARM_TOKEN_PATTERNS["hcl-modules"] == ARM_TOKEN_PATTERNS["hcl-raw"]

    def test_pending_arms_are_exactly_the_ones_the_generator_cannot_write(self) -> None:
        """Keeps `ARMS_PENDING_IMAGE` honest in both directions. An arm the
        generator DOES emit must have every per-arm map filled or the failure is
        a KeyError in the middle of a generation run; an arm it refuses must be
        missing one, or the refusal is hiding code that already works.
        `ARM_MEMORY_MB` is the check because it is the map build_task_toml reads
        unconditionally."""
        for arm in get_args(Arm):
            assert (arm in gen.ARM_MEMORY_MB) is (arm not in gen.ARMS_PENDING_IMAGE), arm

    def test_every_arm_has_an_image(self) -> None:
        """`make build-arms` and `make preflight` SKIP an arm whose environment/
        holds nothing but .gitkeep; this is what stops that skip from hiding a
        DELETED Dockerfile. It is now required of every arm without exception:
        hcl-modules ships an image from phase 4 (DECISIONS.md Amendment 46
        (a)-(b)) even though its task emission waits on the phase-5 pilot, so no
        arm's environment/ is empty any more and the skip covers nothing."""
        for arm in get_args(Arm):
            dockerfile = REPO_ROOT / "arms" / gen.ARM_DIRNAME[arm] / "environment" / "Dockerfile"
            assert dockerfile.is_file(), arm

    def test_the_arm_directory_carries_its_identity(self) -> None:
        readme = (REPO_ROOT / "arms" / "hcl-modules" / "README.md").read_text()
        assert "terraform-aws-modules" in readme
        assert (REPO_ROOT / "arms" / "hcl-modules" / "environment" / ".gitkeep").is_file()


# ---------------------------------------------------------------------------
# 4. the tier column
# ---------------------------------------------------------------------------


class TestTierOverride:
    def test_only_a_spec_that_enables_the_arm_may_declare_one(self) -> None:
        """A non-null override names the tier that decides the catch on THIS
        arm, and SCHEMA.md §3 requires that be evidence-checked against a real
        module-based plan -- which a spec that does not generate the arm has
        not got."""
        for path in ALL_SPEC_PATHS:
            spec = load_spec(path)
            if spec.arms.hcl_modules.enabled:
                continue
            for catch in spec.catches:
                assert catch.predicted_tier_caught.hcl_modules_override is None

    def test_the_column_accepts_every_catch_tier(self, greenfield_raw: dict) -> None:
        for tier in ("0", "1", "live"):
            spec = _mutated(
                greenfield_raw,
                lambda d, tier=tier: d["catches"][0]["predicted_tier_caught"].update(
                    {"hcl_modules_override": tier}
                ),
            )
            assert spec.catches[0].predicted_tier_caught.hcl_modules_override == tier

    def test_an_unknown_tier_is_refused(self, greenfield_raw: dict) -> None:
        with pytest.raises(ValidationError):
            _mutated(
                greenfield_raw,
                lambda d: d["catches"][0]["predicted_tier_caught"].update(
                    {"hcl_modules_override": "2"}
                ),
            )

    def test_the_teardown_tier_still_requires_a_gating_teardown(self) -> None:
        """Same rule the other two columns obey (Amendment 41): a tier that does
        not run, or runs without gating, cannot be the tier that catches anything.
        Read off the spec that HAS a teardown tier — a teardown needs a live phase
        (SCHEMA.md §5.2), which the greenfield pilot has not got."""
        raw = yaml.safe_load(BROWNFIELD_SPEC.read_text())

        def mutate(d: dict) -> None:
            d["catches"][0]["predicted_tier_caught"]["hcl_modules_override"] = "teardown"
            d["verifier"]["teardown"]["gating"] = False

        with pytest.raises(ValidationError, match="requires verifier.teardown.enabled=true"):
            _mutated(raw, mutate)
