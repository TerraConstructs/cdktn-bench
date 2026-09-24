"""The blast-radius read: what each artifact source can and cannot answer."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

REPO_ROOT = Path(__file__).resolve().parent.parent.parent
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from gates.blast_radius import (  # noqa: E402
    BUCKETS,
    BlastRadiusUnavailable,
    bucket_for,
    from_artifacts_dir,
    from_changeset,
    from_plan,
    from_template,
)
from gates.emit_result import read_blast_radius  # noqa: E402
from gates.tests.conftest import ARMS, FIXTURES_DIR  # noqa: E402


def change(address, actions, module_address=None):
    entry = {"address": address, "change": {"actions": actions}}
    if module_address:
        entry["module_address"] = module_address
    return entry


@pytest.mark.parametrize(
    "actions,expected",
    [
        (["no-op"], "no_op"),
        (["create"], "create"),
        (["read"], "read"),
        (["update"], "update"),
        (["delete"], "delete"),
        (["create", "delete"], "replace"),
        (["delete", "create"], "replace"),
        (["forget"], "other"),
        (["create", "update"], "other"),
        ("create", "other"),
        (None, "other"),
    ],
)
def test_every_action_list_lands_in_exactly_one_bucket(actions, expected):
    assert bucket_for(actions) == expected


def test_buckets_sum_to_total_and_split_root_from_module():
    plan = {
        "resource_changes": [
            change("aws_s3_bucket.a", ["create"]),
            change("aws_s3_bucket.b", ["update"]),
            change("aws_iam_role.c", ["delete", "create"]),
            change("module.net.aws_subnet.d", ["create"], "module.net"),
            change('module.net["b"].aws_subnet.e[1]', ["create", "delete"], 'module.net["b"]'),
        ]
    }
    radius = from_plan(plan)
    assert radius["source"] == "terraform-plan"
    assert radius["total"] == 5
    assert radius["root"] == 3
    assert radius["module"] == 2
    assert radius["root"] + radius["module"] == radius["total"]
    assert sum(radius["counts"].values()) == radius["total"]
    assert radius["counts"]["replace"] == 2
    assert radius["counts"]["create"] == 2
    assert radius["counts"]["update"] == 1
    assert set(radius["counts"]) == set(BUCKETS)
    assert "unclassified_actions" not in radius


def test_an_unnamed_action_is_counted_and_named_not_absorbed():
    radius = from_plan({"resource_changes": [change("aws_s3_bucket.a", ["forget"])]})
    assert radius["counts"]["other"] == 1
    assert radius["unclassified_actions"] == [["forget"]]
    assert sum(radius["counts"].values()) == radius["total"] == 1


def test_planned_values_alone_is_refused_rather_than_guessed():
    # The whole point of reading resource_changes[]: a desired-state tree has no
    # actions in it, so it must not silently produce a zero-replace answer.
    with pytest.raises(BlastRadiusUnavailable, match="resource_changes"):
        from_plan({"planned_values": {"root_module": {"resources": [{"address": "aws_s3_bucket.a"}]}}})


def test_template_carries_a_count_and_no_action_breakdown():
    radius = from_template({"Resources": {"A": {}, "B": {}}})
    assert radius == {
        "source": "cloudformation-template",
        "total": 2,
        "root": None,
        "module": None,
        "counts": None,
    }


def test_template_without_resources_is_unavailable():
    with pytest.raises(BlastRadiusUnavailable, match="Resources"):
        from_template({"Outputs": {}})


def test_changeset_fills_the_same_buckets_as_a_plan():
    radius = from_changeset(
        {
            "Changes": [
                {"ResourceChange": {"Action": "Add"}},
                {"ResourceChange": {"Action": "Modify", "Replacement": "False"}},
                {"ResourceChange": {"Action": "Modify", "Replacement": "True"}},
                {"ResourceChange": {"Action": "Modify", "Replacement": "Conditional"}},
                {"ResourceChange": {"Action": "Remove"}},
            ]
        }
    )
    assert radius["source"] == "cloudformation-changeset"
    assert radius["counts"]["create"] == 1
    assert radius["counts"]["update"] == 1
    # Conditional is CloudFormation declining to promise in-place, so it counts
    # with the replaces rather than flattering the update column.
    assert radius["counts"]["replace"] == 2
    assert radius["counts"]["delete"] == 1
    assert radius["root"] is None and radius["module"] is None


def test_artifacts_dir_prefers_the_raw_plan_over_the_normalised_copy(tmp_path):
    (tmp_path / "plan.json").write_text(json.dumps({"resource_changes": [change("a.b", ["create"])]}))
    (tmp_path / "plan.normalised.json").write_text(json.dumps({"resource_changes": []}))
    radius, path = from_artifacts_dir(tmp_path)
    assert path.name == "plan.json"
    assert radius["total"] == 1


def test_two_templates_are_refused_rather_than_picked_arbitrarily(tmp_path):
    for name in ("A.template.json", "B.template.json"):
        (tmp_path / name).write_text(json.dumps({"Resources": {}}))
    with pytest.raises(BlastRadiusUnavailable, match="not decidable"):
        from_artifacts_dir(tmp_path)


def test_empty_artifacts_dir_names_what_it_looked_for(tmp_path):
    with pytest.raises(BlastRadiusUnavailable, match="plan.json"):
        from_artifacts_dir(tmp_path)


def test_unreadable_plan_is_unavailable_not_a_crash(tmp_path):
    (tmp_path / "plan.json").write_text("{not json")
    with pytest.raises(BlastRadiusUnavailable, match="unreadable"):
        from_artifacts_dir(tmp_path)


# --- the trial-dir reader ---------------------------------------------------


@pytest.mark.parametrize("arm", ARMS)
def test_every_arms_genuine_fixture_yields_a_non_null_radius(arm):
    radius, reason = read_blast_radius(FIXTURES_DIR / arm / "genuine")
    assert reason is None
    assert radius["total"] > 0
    assert radius["artifact"].startswith("artifacts/")


@pytest.mark.parametrize("arm", ARMS)
def test_a_trial_with_no_persisted_artifact_reads_null_with_a_reason(arm):
    radius, reason = read_blast_radius(FIXTURES_DIR / arm / "bypass")
    assert radius is None
    assert "artifacts" in reason


def test_multistep_reads_the_final_steps_artifact(tmp_path):
    trial = tmp_path / "trial"
    for name, n in (("01-initial", 1), ("02-change-request", 4)):
        d = trial / "steps" / name / "artifacts"
        d.mkdir(parents=True)
        (d / "plan.json").write_text(
            json.dumps({"resource_changes": [change(f"aws_s3_bucket.b{i}", ["create"]) for i in range(n)]})
        )
    (trial / "result.json").write_text(
        json.dumps({"step_results": [{"step_name": "01-initial"}, {"step_name": "02-change-request"}]})
    )
    radius, reason = read_blast_radius(trial)
    assert reason is None
    assert radius["total"] == 4
    assert radius["artifact"] == "steps/02-change-request/artifacts/plan.json"


def test_multistep_falls_back_to_an_earlier_step_and_never_to_nothing(tmp_path):
    trial = tmp_path / "trial"
    (trial / "steps" / "02-change-request" / "artifacts").mkdir(parents=True)
    d = trial / "steps" / "01-initial" / "artifacts"
    d.mkdir(parents=True)
    (d / "plan.json").write_text(json.dumps({"resource_changes": [change("aws_s3_bucket.b", ["update"])]}))
    radius, reason = read_blast_radius(trial)
    assert reason is None
    assert radius["artifact"] == "steps/01-initial/artifacts/plan.json"
