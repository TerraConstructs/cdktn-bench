"""generator/tests/test_hcl_modules_verifier.py -- the two rules the SHARED
verifier gained when the hcl_modules arm started emitting tasks (DECISIONS.md
Amendment 46 (c), phase 5).

1. THE MODULE-SOURCE RULE. On this arm every call the ROOT module makes must
   resolve from the module registry the environment serves. The check reads
   `.terraform/modules/modules.json` -- the manifest `terraform init` writes,
   which records where each installed call actually came from -- and is scoped
   exactly as arms/hcl-modules/environment/preflight.sh scopes its own copy:
   the root entry and any call an INSTALLED module makes inside its own tree
   are exempt, or the vendored modules' own relative submodules (ecs ->
   ./modules/cluster) would trip it.

   Without the rule an agent copies /opt/terraform-modules into its workspace,
   calls it by path, and produces a plan indistinguishable from a composed one
   -- so the arm would no longer measure composing published modules.

2. THE allow_internet GUARD, which is generation-time rather than runtime: the
   module sources come from a SIDECAR the main container reaches over the
   compose network, and Harbor's no-network compose sets `network_mode: none`
   on the main container only. The sidecar would still run and be unreachable.

Offline and toolchain-free: the REAL emitted verifier, run with stub binaries
on PATH (generator/tests/verifier_harness.py).
"""

from __future__ import annotations

import copy
import json
import sys
from pathlib import Path

import pytest
import yaml
from pydantic import ValidationError

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
sys.path.insert(0, str(REPO_ROOT / "generator"))

from gen import build_verify_config  # noqa: E402
from spec_model import Arm, Spec, load_spec  # noqa: E402
from verifier_harness import stage  # noqa: E402

PILOT_SPEC = REPO_ROOT / "specs" / "acm-dns-validation-record-wiring.yaml"
REGISTRY_PREFIX = "registry.terraform.io/terraform-aws-modules/"


@pytest.fixture(scope="module")
def pilot() -> Spec:
    return load_spec(PILOT_SPEC)


def _manifest(box, *entries: dict) -> Path:
    """`.terraform/modules/modules.json` in the sandbox project, in the exact
    shape terraform writes it."""
    path = box.project / ".terraform" / "modules" / "modules.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"Modules": list(entries)}))
    return path


def _gradeable(box) -> None:
    """Everything BUT the module-source rule made to pass, so a verdict below is
    that rule's and not this spec's oracle."""
    box.static_tiers("1.0")


# ---------------------------------------------------------------------------
# 1. the rule is declared where it can be broken, and nowhere else
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("arm", ("awscdk", "hcl_raw", "terraconstructs"))
def test_no_other_arm_declares_the_rule(pilot: Spec, arm: Arm) -> None:
    """An arm that cannot install a module must not carry a rule it can neither
    break nor satisfy -- the same "present only where it is true" convention
    `normalise_plan` follows."""
    assert "module_sources" not in build_verify_config(pilot, arm)


def test_hcl_modules_declares_it(pilot: Spec) -> None:
    rule = build_verify_config(pilot, "hcl_modules")["module_sources"]
    assert rule == {
        "manifest": ".terraform/modules/modules.json",
        "registry_prefix": REGISTRY_PREFIX,
    }


# ---------------------------------------------------------------------------
# 2. what the rule does to a run
# ---------------------------------------------------------------------------


def test_a_local_path_root_call_is_denied(tmp_path: Path, pilot: Spec) -> None:
    """The signature abuse: a copy of the vendored tree called by path. Scores
    0.0, names the offending call, and leaves its own marker -- and does so on a
    run whose tiers would otherwise BOTH have passed, so the 0.0 is the rule's."""
    box = stage(tmp_path, pilot, "hcl_modules")
    _gradeable(box)
    _manifest(
        box,
        {"Key": "", "Source": "", "Dir": "."},
        {"Key": "certificate", "Source": "./vendor/acm", "Dir": "vendor/acm"},
    )
    result = box.run("static_tiers.sh")

    assert result.reward.strip() == "0.0"
    assert "MODULE SOURCES FAILED" in result.stdout
    assert "module 'certificate' -> source './vendor/acm'" in result.stdout
    marker = result.marker("module-source-denied")
    assert marker is not None
    assert "./vendor/acm" in marker
    # Denied BEFORE either tier: a run stopped here has no verdict to report.
    assert result.summary is None


def test_a_registry_root_call_passes(tmp_path: Path, pilot: Spec) -> None:
    box = stage(tmp_path, pilot, "hcl_modules")
    _gradeable(box)
    _manifest(
        box,
        {"Key": "", "Source": "", "Dir": "."},
        {
            "Key": "certificate",
            "Source": REGISTRY_PREFIX + "acm/aws",
            "Version": "6.3.1",
            "Dir": ".terraform/modules/certificate",
        },
    )
    result = box.run("static_tiers.sh")

    assert result.reward.strip() == "1.0"
    assert "MODULE SOURCES FAILED" not in result.stdout
    assert result.marker("module-source-denied") is None


def test_a_submodule_called_by_relative_path_is_exempt(
    tmp_path: Path, pilot: Spec
) -> None:
    """A `Key` with a dot in it is a call an INSTALLED module makes inside its
    own tree (ecs -> ./modules/cluster). Applied to every entry the rule would
    refuse the vendored modules the image itself installs, which is why
    arms/hcl-modules/environment/preflight.sh carries a fixture that installs
    three of them."""
    box = stage(tmp_path, pilot, "hcl_modules")
    _gradeable(box)
    _manifest(
        box,
        {"Key": "", "Source": "", "Dir": "."},
        {
            "Key": "service",
            "Source": REGISTRY_PREFIX + "ecs/aws",
            "Version": "7.6.1",
            "Dir": ".terraform/modules/service",
        },
        {
            "Key": "service.cluster",
            "Source": "./modules/cluster",
            "Dir": ".terraform/modules/service/modules/cluster",
        },
    )
    result = box.run("static_tiers.sh")

    assert result.reward.strip() == "1.0"
    assert result.marker("module-source-denied") is None


def test_no_manifest_is_no_module_call(tmp_path: Path, pilot: Spec) -> None:
    """A configuration with no `module` block installs nothing, so there is no
    manifest and nothing to deny. The rule must not turn that into a 0.0: a
    module-free solution on this arm is graded by the tiers like any other."""
    box = stage(tmp_path, pilot, "hcl_modules")
    _gradeable(box)
    assert not (box.project / ".terraform").exists()
    result = box.run("static_tiers.sh")

    assert result.reward.strip() == "1.0"
    assert result.marker("module-source-denied") is None


def test_the_denial_is_attributed_to_the_toolchain_tier(
    tmp_path: Path, pilot: Spec
) -> None:
    """`gates/oracle_falsifiability.py::observed_tier` reads `<LABEL> FAILED`
    off a run's stdout and calls it tier "0" -- caught before any assert, like a
    failed `terraform plan`. The deny line has to match that shape or a fixture
    proving the rule would report an unattributable tier."""
    sys.path.insert(0, str(REPO_ROOT / "gates"))
    from oracle_falsifiability import observed_tier  # noqa: PLC0415

    box = stage(tmp_path, pilot, "hcl_modules")
    _gradeable(box)
    _manifest(box, {"Key": "certificate", "Source": "../shared/acm", "Dir": "x"})
    result = box.run("static_tiers.sh")

    assert observed_tier(result.stdout) == "0"


# ---------------------------------------------------------------------------
# 3. the allow_internet guard
# ---------------------------------------------------------------------------


class TestAllowInternet:
    @staticmethod
    @pytest.fixture(scope="class")
    def raw() -> dict:
        return yaml.safe_load(PILOT_SPEC.read_text())

    def test_the_combination_is_refused(self, raw: dict) -> None:
        d = copy.deepcopy(raw)
        d["allow_internet"] = False
        with pytest.raises(ValidationError, match="network_mode: none on the MAIN"):
            Spec.model_validate(d)

    def test_it_is_allowed_without_the_arm(self, raw: dict) -> None:
        d = copy.deepcopy(raw)
        d["allow_internet"] = False
        d["arms"].pop("hcl_modules")
        d["instruction"]["per_arm"].pop("hcl_modules")
        for catch in d["catches"]:
            catch["applies_to"] = [
                a for a in catch.get("applies_to", []) if a != "hcl_modules"
            ]
        for entry in d["oracle"]["structural_asserts"]:
            entry["applies_to"] = [
                a for a in entry.get("applies_to", []) if a != "hcl_modules"
            ]
        assert Spec.model_validate(d).allow_internet is False

    def test_the_default_emits_nothing(self, pilot: Spec) -> None:
        """Harbor's own default is true, so the corpus's task.toml files stay
        byte-identical to ones written before the field existed."""
        from gen import build_task_toml  # noqa: PLC0415

        assert pilot.allow_internet is True
        assert "allow_internet" not in build_task_toml(pilot, "hcl_raw", "uuid")
