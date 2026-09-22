"""generator/tests/test_hcl_modules_arm.py — the `hcl_modules` arm's schema and
plumbing: specs/SCHEMA.md §1/§3, DECISIONS.md Amendment 46 (the arm reintroduced,
gated per spec, closing ROADMAP open decision 4).

The arm has no image yet, so what is testable is exactly the surface that exists:

1. THE DEFAULT — every spec has it disabled, and the default `reason` states the
   gap, so no spec edit is what keeps the corpus generating byte-identically.
2. ENABLING — takes the same shape terraconstructs takes (per-arm instruction
   entry required in both directions), and still refuses to generate, because a
   task whose image does not exist would be a trial nothing can run.
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
# A GREENFIELD spec: `workspace_seed.entry_file` has no `hcl_modules` field, so a
# brownfield spec cannot enable the arm until its per-arm seeds are authored
# (phase 5). `test_a_brownfield_spec_cannot_enable_it_yet` pins that refusal.
PILOT_SPEC = REPO_ROOT / "specs" / "ecs-swappiness.yaml"
BROWNFIELD_SPEC = REPO_ROOT / "specs" / "named-resource-replacement.yaml"
ALL_SPEC_PATHS = sorted(
    [p for p in (REPO_ROOT / "specs").glob("*.yaml") if p.name != "split.yaml"]
    + list((REPO_ROOT / "specs" / "_toy").glob("*.yaml"))
)


@pytest.fixture(scope="module")
def pilot_raw() -> dict:
    return yaml.safe_load(PILOT_SPEC.read_text())


def _mutated(raw: dict, mutate) -> Spec:
    d = copy.deepcopy(raw)
    mutate(d)
    return Spec.model_validate(d)


def _per_arm_block(raw: dict) -> dict:
    """A `per_arm.hcl_modules` entry copied from the spec's own hcl_raw entry:
    the arm authors the same `.tf` files, so the same output contract holds."""
    return copy.deepcopy(raw["instruction"]["per_arm"]["hcl_raw"])


# ---------------------------------------------------------------------------
# 1. the default
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("path", ALL_SPEC_PATHS, ids=lambda p: p.stem)
def test_every_spec_has_the_arm_disabled(path: Path) -> None:
    """No spec enables it, which is why `make gen-all` is byte-identical to
    before the arm existed. Enabling one is a decision (Amendment 46 promotes
    from DRAFT on the phase-5 live run), never a refactor."""
    spec = load_spec(path)
    assert spec.arms.hcl_modules.enabled is False
    assert "hcl_modules" not in spec.arms.enabled_arms()


@pytest.mark.parametrize("path", ALL_SPEC_PATHS, ids=lambda p: p.stem)
def test_no_spec_writes_the_block(path: Path) -> None:
    """The omitted block carries `HCL_MODULES_DEFAULT_REASON`, so the §1 rule
    "a reason in both directions" holds for a spec that never mentions the arm."""
    raw = yaml.safe_load(path.read_text())
    assert "hcl_modules" not in raw["arms"]
    assert load_spec(path).arms.hcl_modules.reason == HCL_MODULES_DEFAULT_REASON


def test_default_reason_names_the_gap() -> None:
    assert "docs/design/tf-modules-arm.md" in HCL_MODULES_DEFAULT_REASON


def test_an_empty_reason_is_refused(pilot_raw: dict) -> None:
    with pytest.raises(ValidationError, match="reason is required in both directions"):
        _mutated(pilot_raw, lambda d: d["arms"].update(
            {"hcl_modules": {"enabled": False, "reason": "  "}}
        ))


# ---------------------------------------------------------------------------
# 2. enabling
# ---------------------------------------------------------------------------


class TestEnabling:
    def test_enabled_requires_a_per_arm_entry(self, pilot_raw: dict) -> None:
        with pytest.raises(ValidationError, match="instruction.per_arm.hcl_modules is missing"):
            _mutated(pilot_raw, lambda d: d["arms"].update(
                {"hcl_modules": {"enabled": True, "reason": "pilot composition trap"}}
            ))

    def test_a_per_arm_entry_without_the_arm_is_refused(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["instruction"]["per_arm"]["hcl_modules"] = _per_arm_block(d)

        with pytest.raises(ValidationError, match="arms.hcl_modules.enabled is false"):
            _mutated(pilot_raw, mutate)

    def test_the_full_shape_validates_and_enables(self, pilot_raw: dict) -> None:
        def mutate(d: dict) -> None:
            d["arms"]["hcl_modules"] = {"enabled": True, "reason": "pilot composition trap"}
            d["instruction"]["per_arm"]["hcl_modules"] = _per_arm_block(d)

        spec = _mutated(pilot_raw, mutate)
        assert spec.arms.enabled_arms()[-1] == "hcl_modules"

    def test_a_brownfield_spec_cannot_enable_it_yet(self) -> None:
        """A seed body per enabled arm is mandatory (SCHEMA.md §2.7), and the arm
        has no hand-authored, plan-green module-based seed — so the refusal names
        the missing seed rather than generating a greenfield workspace whose
        siblings start from working config."""
        raw = yaml.safe_load(BROWNFIELD_SPEC.read_text())

        def mutate(d: dict) -> None:
            d["arms"]["hcl_modules"] = {"enabled": True, "reason": "pilot composition trap"}
            d["instruction"]["per_arm"]["hcl_modules"] = _per_arm_block(d)

        with pytest.raises(ValidationError, match=r"missing \['hcl_modules'\]"):
            _mutated(raw, mutate)

    def test_generation_refuses_until_the_image_lands(self, pilot_raw: dict) -> None:
        """The refusal is a sentence, not a KeyError from a half-populated arm
        map: the module delivery, the sidecar and the plan normaliser are what
        make a task runnable (docs/design/tf-modules-arm.md milestones 4-5)."""
        def mutate(d: dict) -> None:
            d["arms"]["hcl_modules"] = {"enabled": True, "reason": "pilot composition trap"}
            d["instruction"]["per_arm"]["hcl_modules"] = _per_arm_block(d)

        spec = _mutated(pilot_raw, mutate)
        with pytest.raises(NotImplementedError, match="no environment/Dockerfile"):
            gen.generate_arm(spec, "hcl_modules")


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

    def test_pending_arms_are_exactly_the_ones_without_an_image(self) -> None:
        """Keeps `ARMS_PENDING_IMAGE` honest in both directions, so the
        Makefile's "skip an arm with an empty environment/" cannot hide a
        DELETED Dockerfile on a shipped arm."""
        for arm in get_args(Arm):
            dockerfile = REPO_ROOT / "arms" / gen.ARM_DIRNAME[arm] / "environment" / "Dockerfile"
            assert dockerfile.is_file() is (arm not in gen.ARMS_PENDING_IMAGE), arm

    def test_the_arm_directory_carries_its_identity(self) -> None:
        readme = (REPO_ROOT / "arms" / "hcl-modules" / "README.md").read_text()
        assert "terraform-aws-modules" in readme
        assert (REPO_ROOT / "arms" / "hcl-modules" / "environment" / ".gitkeep").is_file()


# ---------------------------------------------------------------------------
# 4. the tier column
# ---------------------------------------------------------------------------


class TestTierOverride:
    def test_no_catch_declares_one_yet(self) -> None:
        """A non-null override names the tier that decides the catch on THIS
        arm, which cannot be evidence-checked before a module-based reference
        exists (SCHEMA.md §3's "verify it by reading the source" rule)."""
        for path in ALL_SPEC_PATHS:
            for catch in load_spec(path).catches:
                assert catch.predicted_tier_caught.hcl_modules_override is None

    def test_the_column_accepts_every_catch_tier(self, pilot_raw: dict) -> None:
        for tier in ("0", "1", "live"):
            spec = _mutated(
                pilot_raw,
                lambda d, tier=tier: d["catches"][0]["predicted_tier_caught"].update(
                    {"hcl_modules_override": tier}
                ),
            )
            assert spec.catches[0].predicted_tier_caught.hcl_modules_override == tier

    def test_an_unknown_tier_is_refused(self, pilot_raw: dict) -> None:
        with pytest.raises(ValidationError):
            _mutated(
                pilot_raw,
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
