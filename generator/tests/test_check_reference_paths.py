"""generator/tests/test_check_reference_paths.py — the two things
generator/check_reference_paths.py must get right about the `hcl_modules` arm,
both of which it silently got wrong while every greenfield reference fixture on
that arm was still NOT_AUTHORED (docs/gates.md#check-reference-paths).

1. IT GRADES THE DOCUMENT A TIER GRADES. Every TF arm's verifier normalises the
   plan before any tier reads it, because the asserts address
   `planned_values.root_module.resources` and a module-shaped plan keeps its
   resources in `child_modules`. A gate resolving declared paths against the RAW
   plan reports `Cannot iterate over null` for paths every real trial resolves --
   the gate contradicting the thing it gates, and unfalsifiable in the direction
   that matters, since it can only ever be too strict.
2. IT RESOLVES MODULES FROM THE OFFLINE REGISTRY. `terraform init` with no
   `TF_CLI_CONFIG_FILE` override reaches registry.terraform.io, so the gate
   would grade against whatever the public registry serves today rather than
   against the bytes the arm's own image ships.

Offline: no docker, no terraform, no AWS. `_graded_artifact` shells out to the
generated `tests/tiers.py`, which is pure Python.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

import check_reference_paths as crp
import gen
import tf_registry
from spec_model import load_spec

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
MODULES_SPEC = REPO_ROOT / "specs" / "named-resource-replacement.yaml"


def _project(tmp_path: Path, arm: str) -> Path:
    """A scratch project carrying one real task's emitted `tests/`, which is all
    `_graded_artifact` reads: `verify.py` for the flag and `tiers.py` for the
    mechanism."""
    spec = load_spec(MODULES_SPEC)
    project = tmp_path / arm
    (project / "tests").mkdir(parents=True)
    for name in ("verify.py", "tiers.py"):
        shutil.copy2(gen.task_dir(spec, arm) / "tests" / name, project / "tests" / name)
    return project


# A plan with one resource inside one module call and nothing at the root -- the
# shape every hcl_modules solution produces, and the shape the raw-plan asserts
# see as an empty resource set.
MODULE_SHAPED_PLAN = {
    "format_version": "1.2",
    "planned_values": {
        "root_module": {
            "child_modules": [
                {
                    "address": "module.vpc",
                    "resources": [
                        {
                            "address": "module.vpc.aws_vpc.this",
                            "type": "aws_vpc",
                            "name": "this",
                            "values": {"cidr_block": "10.0.0.0/16"},
                        }
                    ],
                }
            ]
        }
    },
    "configuration": {"root_module": {"module_calls": {}}},
    "resource_changes": [],
}


def _addresses(doc: Path) -> list[str]:
    plan = json.loads(doc.read_text())
    return [r["address"] for r in plan["planned_values"]["root_module"].get("resources", [])]


def test_the_modules_arm_normalises_before_resolving(tmp_path: Path) -> None:
    project = _project(tmp_path, "hcl_modules")
    artifact = project / "plan.json"
    artifact.write_text(json.dumps(MODULE_SHAPED_PLAN))

    graded, err = crp._graded_artifact(project, artifact)

    assert not err, err
    assert graded != artifact, "the gate resolved paths against the RAW plan"
    # The hoist itself, not merely a different filename: this is the difference
    # between `Cannot iterate over null` and a resolvable path.
    assert _addresses(graded) == ["module.vpc.aws_vpc.this"]
    assert _addresses(artifact) == [], "the raw artifact must be left untouched"


def test_awscdk_is_handed_its_artifact_unchanged(tmp_path: Path) -> None:
    """The flag is read off the task's own config, so an arm that does not
    normalise is not normalised: a CFN template has no plan shape to hoist, and
    inventing one would be the same class of error in the other direction."""
    project = _project(tmp_path, "awscdk")
    artifact = project / "template.json"
    artifact.write_text(json.dumps({"Resources": {}}))

    assert crp._graded_artifact(project, artifact) == (artifact, "")


def test_an_unnormalisable_plan_is_a_failure_not_a_pass(tmp_path: Path) -> None:
    """Fail-closed, like the trial: a document no tier could grade must not be
    reported as a resolved path."""
    project = _project(tmp_path, "hcl_modules")
    artifact = project / "plan.json"
    artifact.write_text("{not json")

    graded, err = crp._graded_artifact(project, artifact)
    assert err
    assert graded == artifact


@pytest.mark.parametrize("arm", ["awscdk", "hcl_raw", "terraconstructs", "hcl_modules"])
def test_the_config_flag_matches_the_generator(tmp_path: Path, arm: str) -> None:
    """`_verifier_config` parses the emitted literal; this pins that the parse
    agrees with the generator's own decision for every arm."""
    expected = gen.build_verify_config(load_spec(MODULES_SPEC), arm, None).get(
        "normalise_plan", False
    )
    assert crp._verifier_config(_project(tmp_path, arm)).get(
        "normalise_plan", False
    ) == expected


def test_the_gate_uses_the_one_registry_environment() -> None:
    """Not a second copy of the arm gate: the same object every fixture-running
    gate uses, so this gate and `make falsifiability` cannot resolve a module
    from two different registries."""
    assert crp.arm_env is tf_registry.arm_env
