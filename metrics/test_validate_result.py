"""Tests for metrics/validate_result.py — schema round-trip."""

from __future__ import annotations

import copy
import json
from pathlib import Path

import pytest
from validate_result import load_schema, main, validate_result

EXAMPLE_PATH = Path(__file__).with_name("examples") / "valid-result.json"

VALID_ROW = {
    "schema_version": "1.0",
    "equipping_hash": "a" * 64,
    "oracle_version": "oracles@0000000",
    "arm": "awscdk",
    "model": "claude-sonnet-5",
    "harness": "empty",
    "validity_class": "valid",
    "tokens_input": 1000,
    "tokens_output": 200,
    "tokens_total": 1200,
    "reward": 1.0,
    "censored": False,
    "tier1_not_verifiable": False,
}


def test_schema_itself_is_well_formed():
    # load_schema() calling validate_result() below already exercises
    # jsonschema's own check_schema(); this is a direct, explicit check.
    import jsonschema

    schema = load_schema()
    jsonschema.validators.validator_for(schema).check_schema(schema)


def test_valid_row_round_trips_clean():
    assert validate_result(VALID_ROW) == []


def test_checked_in_example_fixture_is_valid():
    row = json.loads(EXAMPLE_PATH.read_text(encoding="utf-8"))
    assert validate_result(row) == []


@pytest.mark.parametrize(
    "missing_field",
    [
        "equipping_hash",
        "oracle_version",
        "arm",
        "model",
        "harness",
        "validity_class",
        "tokens_input",
        "tokens_output",
        "tokens_total",
        "reward",
        "censored",
        "tier1_not_verifiable",
    ],
)
def test_missing_required_field_is_rejected(missing_field):
    row = copy.deepcopy(VALID_ROW)
    del row[missing_field]
    errors = validate_result(row)
    assert errors, f"expected an error when {missing_field!r} is missing"
    assert any(missing_field in e for e in errors)


def test_bad_equipping_hash_shape_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["equipping_hash"] = "not-a-hex-digest"
    errors = validate_result(row)
    assert errors
    assert any("equipping_hash" in e for e in errors)


def test_unknown_arm_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["arm"] = "pulumi"  # explicitly excluded arm, DECISIONS.md Amendment 2
    errors = validate_result(row)
    assert errors
    assert any("arm" in e for e in errors)


def test_unknown_harness_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["harness"] = "partially-tuned"
    errors = validate_result(row)
    assert errors


def test_unknown_validity_class_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["validity_class"] = "sort-of-valid"
    errors = validate_result(row)
    assert errors


def test_reward_out_of_range_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["reward"] = 1.5
    errors = validate_result(row)
    assert errors


def test_censored_must_be_boolean():
    row = copy.deepcopy(VALID_ROW)
    row["censored"] = "false"  # string, not bool
    errors = validate_result(row)
    assert errors


def test_tier1_not_verifiable_must_be_boolean():
    row = copy.deepcopy(VALID_ROW)
    row["tier1_not_verifiable"] = "true"  # string, not bool
    errors = validate_result(row)
    assert errors
    assert any("tier1_not_verifiable" in e for e in errors)


def test_tier1_not_verifiable_true_with_detail_accepted():
    row = copy.deepcopy(VALID_ROW)
    row["tier1_not_verifiable"] = True
    row["tier1_not_verifiable_detail"] = (
        "policy-actions-read-only: policy references the created parameter "
        "but its encoded value is plan-time-unknown"
    )
    assert validate_result(row) == []


def test_tier1_not_verifiable_detail_without_the_flag_is_still_schema_valid():
    # tier1_not_verifiable_detail is optional/informational-only, not
    # schema-coupled to tier1_not_verifiable being true -- see its own
    # description ("never schema-enforced").
    row = copy.deepcopy(VALID_ROW)
    row["tier1_not_verifiable_detail"] = "some detail"
    assert validate_result(row) == []


def test_negative_token_count_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["tokens_input"] = -1
    errors = validate_result(row)
    assert errors


def test_tokens_total_below_input_plus_output_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["tokens_total"] = 500  # less than tokens_input(1000) + tokens_output(200)
    errors = validate_result(row)
    assert errors
    assert any("tokens_total" in e for e in errors)


def test_tokens_total_may_exceed_input_plus_output_for_cached_tokens():
    row = copy.deepcopy(VALID_ROW)
    row["tokens_total"] = 5000  # e.g. folds in a large cached-token count
    assert validate_result(row) == []


def test_unknown_additional_property_is_rejected():
    row = copy.deepcopy(VALID_ROW)
    row["substrate"] = "real-aws"  # not in the schema's declared properties
    errors = validate_result(row)
    assert errors, "additionalProperties: false must reject undeclared fields"


def test_optional_fields_accepted_when_present():
    row = copy.deepcopy(VALID_ROW)
    row.update(
        {
            "scenario": "anchor",
            "task": "cdktn-smoke/anchor-write-file",
            "trial_id": "trial-0001",
            "job_id": "job-0001",
            "tokens_cached": 300,
            "cost_usd": 0.05,
            "n_llm_calls": 3,
            "wall_seconds": 12.5,
            "timestamp": "2026-08-06T00:00:00Z",
        }
    )
    assert validate_result(row) == []


def test_all_errors_collected_not_just_first():
    row = copy.deepcopy(VALID_ROW)
    del row["reward"]
    row["arm"] = "not-a-real-arm"
    errors = validate_result(row)
    assert len(errors) >= 2


class TestCli:
    def test_cli_accepts_valid_fixture(self, capsys):
        rc = main([str(EXAMPLE_PATH)])
        assert rc == 0
        out = capsys.readouterr().out
        assert "OK" in out

    def test_cli_rejects_invalid_row(self, tmp_path, capsys):
        row = copy.deepcopy(VALID_ROW)
        del row["reward"]
        bad_path = tmp_path / "bad-result.json"
        bad_path.write_text(json.dumps(row), encoding="utf-8")

        rc = main([str(bad_path)])
        assert rc == 1
        err = capsys.readouterr().err
        assert "FAIL" in err
        assert "reward" in err

    def test_cli_handles_ndjson(self, tmp_path):
        good = copy.deepcopy(VALID_ROW)
        also_good = copy.deepcopy(VALID_ROW)
        also_good["arm"] = "hcl-raw"
        ndjson_path = tmp_path / "results.ndjson"
        ndjson_path.write_text(
            "\n".join(json.dumps(r) for r in (good, also_good)) + "\n", encoding="utf-8"
        )

        rc = main([str(ndjson_path)])
        assert rc == 0

    def test_cli_handles_json_array(self, tmp_path):
        good = copy.deepcopy(VALID_ROW)
        bad = copy.deepcopy(VALID_ROW)
        del bad["censored"]
        array_path = tmp_path / "results.json"
        array_path.write_text(json.dumps([good, bad]), encoding="utf-8")

        rc = main([str(array_path)])
        assert rc == 1  # one of the two rows is invalid
