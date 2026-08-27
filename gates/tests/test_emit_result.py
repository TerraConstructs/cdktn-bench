"""Gate 3 (gates/emit_result.py) proven against the synthetic per-arm fixtures.

Each arm contributes three trial-dir fixtures:

- genuine/       toolchain invoked, no infra signal      -> validity_class="valid", score emitted
- bypass/        toolchain never invoked, no infra signal -> validity_class="invalid-bypass", refused
- infra-failure/ an infra-failure log signal is present   -> validity_class="invalid-infra", refused
                 (regardless of what the trajectory itself would otherwise
                 audit to — infra takes priority, proven below)
"""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path

import pytest

from gates.emit_result import (
    _extract_score_fields,
    INVALID_BYPASS,
    INVALID_INFRA,
    VALID,
    build_result_record,
    classify_infra_failure,
    extract_n_llm_calls,
    read_budget,
    read_tier1_not_verifiable,
    read_tier_evidence,
    resolve_split_group,
    to_result_row,
)
from gates.tests.conftest import ARMS, REPO_ROOT, SCENARIOS, trial_dir
from metrics.validate_result import validate_result
from oracles.tests.toolcheck import find_tool

# @sha256: short-circuits compute_equipping_hash's docker-inspect fallback
# path (gates/equipping.py `_resolve_image_digest`) so these tests never
# shell out to docker and stay fast/deterministic without a daemon.
FAKE_DIGEST_IMAGE_REF = "cdktn-bench/fixture@sha256:" + "0" * 64


@pytest.mark.parametrize("arm", ARMS)
def test_genuine_use_is_valid_and_emits_score(arm: str, task_dir) -> None:
    record = build_result_record(
        trial_dir(arm, "genuine"),
        arm,
        task_dir,
        FAKE_DIGEST_IMAGE_REF,
        {"model": "claude-sonnet-5"},
    )
    assert record["validity_class"] == VALID
    assert record["valid"] is True
    assert record["score_emitted"] is True
    assert record["audit"]["valid"] is True
    assert record["infra"] is None
    assert record["reward"] == 1.0
    assert record["cost_usd"] is not None
    assert record["equipping_hash"] is not None
    assert len(record["equipping_hash"]) == 64
    int(record["equipping_hash"], 16)  # must be valid hex


@pytest.mark.parametrize("arm", ARMS)
def test_bypass_is_refused(arm: str, task_dir) -> None:
    record = build_result_record(
        trial_dir(arm, "bypass"),
        arm,
        task_dir,
        FAKE_DIGEST_IMAGE_REF,
        {"model": "claude-sonnet-5"},
    )
    assert record["validity_class"] == INVALID_BYPASS
    assert record["valid"] is False
    assert record["score_emitted"] is False
    assert "reward" not in record, "an invalid trial must never carry a score/reward field"
    assert record["audit"]["valid"] is False
    assert record["infra"] is None
    # Still gets an equipping hash: even a refused row is traceable to its equipping.
    assert record["equipping_hash"] is not None


@pytest.mark.parametrize("arm", ARMS)
def test_infra_failure_is_refused_and_takes_priority_over_bypass(arm: str, task_dir) -> None:
    d = trial_dir(arm, "infra-failure")
    # Sanity: the audit gate alone, run on this same trajectory, would also
    # say invalid (no toolchain evidence) -- proving emit_result's
    # invalid-infra verdict isn't just re-deriving invalid-bypass by luck.
    infra = classify_infra_failure(d)
    assert infra is not None, "fixture must contain a detectable infra-failure signal"

    record = build_result_record(d, arm, task_dir, FAKE_DIGEST_IMAGE_REF, {})
    assert record["validity_class"] == INVALID_INFRA
    assert record["valid"] is False
    assert record["score_emitted"] is False
    assert "reward" not in record
    assert record["infra"]["kind"] == infra["kind"]


def test_infra_kinds_are_distinct_across_arm_fixtures() -> None:
    """The three infra-failure fixtures were deliberately authored to hit
    three different infra-failure kinds (oom / docker-daemon / env-auth) so
    the classifier's pattern table is exercised, not just its first entry."""
    kinds = {arm: classify_infra_failure(trial_dir(arm, "infra-failure"))["kind"] for arm in ARMS}
    assert kinds == {
        "awscdk": "docker-daemon",
        "hcl-raw": "env-auth",
        "terraconstructs": "oom",
    }


def test_classify_infra_failure_returns_none_for_clean_trial(task_dir) -> None:
    assert classify_infra_failure(trial_dir("awscdk", "genuine")) is None
    assert classify_infra_failure(trial_dir("awscdk", "bypass")) is None


def test_agent_authored_output_cannot_self_void_a_genuine_trial(task_dir) -> None:
    """Regression test for the "self-void / censoring vector" finding: an
    infra-failure phrase written into the AGENT's own output file
    (agent/agent-output.txt) must never flip a genuine trial to
    invalid-infra -- only harness-owned logs (trial.log/exception.txt/
    result.json) may drive that classification."""
    import shutil

    src = trial_dir("awscdk", "genuine")
    tmp = Path(__file__).resolve().parent / "fixtures" / "awscdk" / "_tmp-self-void-proof"
    if tmp.exists():
        shutil.rmtree(tmp)
    shutil.copytree(src, tmp)
    try:
        (tmp / "agent" / "agent-output.txt").write_text(
            "Note: the build was slow, probably out of memory pressure.\n"
        )
        (tmp / "agent" / "claude-code.txt").write_text(
            "authentication_error: invalid api key, just mentioning it in passing\n"
        )
        record = build_result_record(tmp, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {"model": "claude-sonnet-5"})
        assert record["validity_class"] == VALID, (
            "an infra-failure phrase in agent-authored output must not void a genuine trial"
        )
        assert record["score_emitted"] is True
        assert record["reward"] == 1.0
    finally:
        shutil.rmtree(tmp)


def test_agent_cannot_self_void_via_its_own_bash_observation_text(task_dir) -> None:
    """Regression test for the round-2 "self-void relocated to observation
    text" finding: an agent that chains a real toolchain invocation with its
    own `echo 'command not found'` (or otherwise produces an observation
    containing an unanchored infra-failure phrase) must not have that call
    degraded/voided -- only a "command not found" anchored to THIS call's
    own matched tool name, or a genuine terminal exit-code/status line,
    may do that."""
    trajectory = {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {
                        "tool_call_id": "c1",
                        "function_name": "Bash",
                        "arguments": {"command": "npx --no-install cdk synth; echo 'command not found'"},
                    }
                ],
                "observation": {
                    "results": [
                        {
                            "source_call_id": "c1",
                            "content": "Stack failed to synthesize: TypeError …\ncommand not found",
                        }
                    ]
                },
            }
        ]
    }
    trial = Path(__file__).resolve().parent / "fixtures" / "awscdk" / "_tmp-self-void-observation-proof"
    if trial.exists():
        import shutil

        shutil.rmtree(trial)
    (trial / "agent").mkdir(parents=True)
    (trial / "agent" / "trajectory.json").write_text(json.dumps(trajectory))
    try:
        record = build_result_record(trial, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["validity_class"] == VALID, (
            "an unanchored infra-failure phrase in the agent's own observation text must not void the trial"
        )
        assert record["audit"]["degraded"] is False
    finally:
        import shutil

        shutil.rmtree(trial)


def test_genuine_enoent_observation_is_not_routed_to_invalid_infra(task_dir) -> None:
    """A real Node/cdk ENOENT (missing project file) must count as a live,
    valid toolchain invocation -- not a degraded/missing-toolchain arm."""
    trajectory = {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {
                        "tool_call_id": "c1",
                        "function_name": "Bash",
                        "arguments": {"command": "npx --no-install cdk synth"},
                    }
                ],
                "observation": {
                    "results": [
                        {
                            "source_call_id": "c1",
                            "content": "Error: ENOENT: no such file or directory, open '/app/project/cdk.json'",
                        }
                    ]
                },
            }
        ]
    }
    trial = Path(__file__).resolve().parent / "fixtures" / "awscdk" / "_tmp-enoent-proof"
    if trial.exists():
        import shutil

        shutil.rmtree(trial)
    (trial / "agent").mkdir(parents=True)
    (trial / "agent" / "trajectory.json").write_text(json.dumps(trajectory))
    try:
        record = build_result_record(trial, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["validity_class"] == VALID
        assert record["audit"]["degraded"] is False
    finally:
        import shutil

        shutil.rmtree(trial)


@pytest.mark.parametrize("arm", ARMS)
def test_toolchain_command_not_found_is_invalid_infra_not_bypass(arm: str, task_dir) -> None:
    """Regression test: a matched toolchain command whose observation shows
    "command not found" (the tool was never installed/available) must be
    invalid-infra, not invalid-bypass and not valid -- the audit gate DID
    find the agent trying the tool; the tool just wasn't there."""
    tool_by_arm = {
        "awscdk": ("npx --no-install cdk synth", "bash: cdk: command not found\nExit code 127"),
        "hcl-raw": ("terraform validate", "bash: terraform: command not found\nExit code 127"),
        "terraconstructs": ("npx --no-install cdktn synth", "bash: cdktn: command not found\nExit code 127"),
    }
    command, observation_text = tool_by_arm[arm]
    trial = Path(__file__).resolve().parent / "fixtures" / arm / "_tmp-degraded-proof"
    if trial.exists():
        import shutil

        shutil.rmtree(trial)
    (trial / "agent").mkdir(parents=True)
    trajectory = {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {"tool_call_id": "c1", "function_name": "Bash", "arguments": {"command": command}}
                ],
                "observation": {"results": [{"source_call_id": "c1", "content": observation_text}]},
            }
        ]
    }
    (trial / "agent" / "trajectory.json").write_text(json.dumps(trajectory))
    try:
        record = build_result_record(trial, arm, task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["validity_class"] == INVALID_INFRA
        assert record["valid"] is False
        assert record["score_emitted"] is False
        assert "reward" not in record
        assert record["infra"]["kind"] == "toolchain-missing"
    finally:
        import shutil

        shutil.rmtree(trial)


class TestToResultRowIsARealSchemaProducer:
    """Regression tests for the finding: metrics/result_schema.json had no
    producer -- build_result_record()'s own records don't validate against
    it as-is (missing schema_version/tokens_total/..., extra gate-internal
    keys like `audit`/`infra`). to_result_row() is that producer; these
    tests prove real gate output round-trips through the schema for all
    three validity classes, not just a hand-authored example."""

    @pytest.mark.parametrize("arm", ARMS)
    @pytest.mark.parametrize("scenario", SCENARIOS)
    def test_every_fixture_record_produces_a_schema_valid_row(self, arm: str, scenario: str, task_dir) -> None:
        record = build_result_record(
            trial_dir(arm, scenario),
            arm,
            task_dir,
            FAKE_DIGEST_IMAGE_REF,
            {"model": "claude-sonnet-5"},
        )
        row = to_result_row(
            record,
            model="claude-sonnet-5",
            harness="empty",
            oracle_version="oracles@fixture",
        )
        errors = validate_result(row)
        assert errors == [], f"{arm}/{scenario} row failed schema validation: {errors}"

    def test_valid_row_carries_real_reward_and_tokens(self, task_dir) -> None:
        record = build_result_record(
            trial_dir("awscdk", "genuine"), "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert row["validity_class"] == "valid"
        assert row["reward"] == 1.0
        assert row["tokens_input"] == 5211
        assert row["tokens_output"] == 812
        assert row["tokens_cached"] == 3980
        assert row["tokens_total"] == 5211 + 812 + 3980
        assert "validity_reason" not in row

    def test_invalid_row_gets_zeroed_score_fields_and_a_reason(self, task_dir) -> None:
        record = build_result_record(
            trial_dir("awscdk", "bypass"), "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert row["validity_class"] == "invalid-bypass"
        assert row["reward"] == 0.0
        assert row["tokens_total"] == 0
        assert "validity_reason" in row and row["validity_reason"]

    def test_missing_equipping_hash_refuses_to_produce_a_row(self, tmp_path) -> None:
        empty_task_dir = tmp_path / "task-with-no-instruction"
        empty_task_dir.mkdir()
        record = build_result_record(
            trial_dir("awscdk", "genuine"), "awscdk", empty_task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        assert record["equipping_hash"] is None
        with pytest.raises(ValueError, match="equipping_hash"):
            to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")

    def test_real_harbor_rewards_dict_shape_maps_to_a_numeric_reward(self, task_dir) -> None:
        """Regression test for the round-2 finding: Harbor's real
        VerifierResult.rewards is `dict[str, float | int] | None`
        (harbor/models/verifier/result.py), read by upstream aws-bench as
        `rewards.get("reward")` (aws_bench/metrics/run_data.py ~465-470) --
        not the bare scalar the fixtures used to hand-author. A record built
        from that real shape must still produce a schema-valid numeric
        `reward`, not a dict that fails `type: number` validation."""
        import shutil
        import tempfile

        src = trial_dir("awscdk", "genuine")
        tmp = Path(tempfile.mkdtemp()) / "trial"
        shutil.copytree(src, tmp)
        (tmp / "result.json").write_text(
            json.dumps(
                {
                    "verifier_result": {"rewards": {"reward": 1.0}},
                    "agent_result": {
                        "cost_usd": 0.01,
                        "n_input_tokens": 100,
                        "n_output_tokens": 50,
                        "n_cache_tokens": 10,
                    },
                }
            )
        )
        try:
            record = build_result_record(tmp, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
            assert record["reward"] == 1.0
            assert isinstance(record["reward"], float)
            row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
            assert row["reward"] == 1.0
            assert validate_result(row) == []
        finally:
            shutil.rmtree(tmp.parent)

    def test_rewards_dict_without_reward_key_falls_back_to_first_numeric_value(self, task_dir) -> None:
        """Mirrors aws_bench/metrics/run_data.py's own fallback: a rewards
        dict that doesn't use the "reward" key still yields a numeric score
        from whatever numeric value it does carry."""
        import shutil
        import tempfile

        src = trial_dir("awscdk", "genuine")
        tmp = Path(tempfile.mkdtemp()) / "trial"
        shutil.copytree(src, tmp)
        (tmp / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"custom_metric": 0.42}}}))
        try:
            record = build_result_record(tmp, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
            assert record["reward"] == 0.42
        finally:
            shutil.rmtree(tmp.parent)

    def test_multistep_trial_aggregates_tokens_across_step_results(self, task_dir) -> None:
        """Regression test for the round-2 finding: multi-step trials record
        tokens per-step on `step_results[i].agent_result`, never on a
        top-level `agent_result` (TrialResult.compute_token_cost_totals()) --
        `_extract_score_fields` must aggregate across steps in that case
        instead of silently reporting 0 tokens for a real multi-step trial."""
        import shutil
        import tempfile

        src = trial_dir("awscdk", "genuine")
        tmp = Path(tempfile.mkdtemp()) / "trial"
        shutil.copytree(src, tmp)
        (tmp / "result.json").write_text(
            json.dumps(
                {
                    "verifier_result": {"rewards": {"reward": 0.75}},
                    "step_results": [
                        {
                            "step_name": "s1",
                            "agent_result": {
                                "n_input_tokens": 100,
                                "n_output_tokens": 20,
                                "n_cache_tokens": 5,
                                "cost_usd": 0.01,
                            },
                        },
                        {
                            "step_name": "s2",
                            "agent_result": {
                                "n_input_tokens": 200,
                                "n_output_tokens": 40,
                                "n_cache_tokens": 15,
                                "cost_usd": 0.02,
                            },
                        },
                    ],
                }
            )
        )
        try:
            record = build_result_record(tmp, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
            assert record["reward"] == 0.75
            assert record["n_input_tokens"] == 300
            assert record["n_output_tokens"] == 60
            assert record["n_cache_tokens"] == 20
            assert record["cost_usd"] == pytest.approx(0.03)
            row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
            assert row["tokens_input"] == 300
            assert row["tokens_output"] == 60
            assert row["tokens_total"] == 380
            assert validate_result(row) == []
        finally:
            shutil.rmtree(tmp.parent)

    def test_optional_run_identifiers_are_passed_through(self, task_dir) -> None:
        record = build_result_record(
            trial_dir("hcl-raw", "genuine"), "hcl-raw", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        row = to_result_row(
            record,
            model="claude-sonnet-5",
            harness="tuned",
            oracle_version="oracles@abc123",
            censored=True,
            scenario="anchor",
            task="cdktn-smoke/anchor-write-file",
            trial_id="trial-0007",
            job_id="job-0001",
        )
        assert row["scenario"] == "anchor"
        assert row["task"] == "cdktn-smoke/anchor-write-file"
        assert row["trial_id"] == "trial-0007"
        assert row["job_id"] == "job-0001"
        assert row["censored"] is True
        assert row["harness"] == "tuned"
        assert validate_result(row) == []

    def test_spec_id_is_persisted_on_the_row_distinct_from_scenario(self, task_dir) -> None:
        # 2026-08-06 fix round 2: spec_id (the cdktn-bench BENCHMARK
        # scenario id, e.g. "apigw-openapi") used to be consumed only
        # transiently to resolve split_group and then discarded -- never
        # actually persisted on the row. scenario is the aws-bench AWS
        # scenario ("anchor" for every task in this repo) and must not be
        # conflated with it; downstream per-scenario grouping
        # (metrics/tokens_to_green.py) needs spec_id on the row itself.
        record = build_result_record(
            trial_dir("hcl-raw", "genuine"), "hcl-raw", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        row = to_result_row(
            record,
            model="claude-sonnet-5",
            harness="tuned",
            oracle_version="oracles@abc123",
            scenario="anchor",
            spec_id="apigw-openapi",
        )
        assert row["scenario"] == "anchor"
        assert row["spec_id"] == "apigw-openapi"
        assert row["spec_id"] != row["scenario"]
        assert validate_result(row) == []

    def test_spec_id_absent_when_not_passed(self, task_dir) -> None:
        record = build_result_record(
            trial_dir("hcl-raw", "genuine"), "hcl-raw", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert "spec_id" not in row
        assert validate_result(row) == []


def test_missing_trial_dir_raises() -> None:
    with pytest.raises(FileNotFoundError):
        build_result_record("/nonexistent/trial/dir", "awscdk", "/nonexistent/task", FAKE_DIGEST_IMAGE_REF, {})


def test_missing_instruction_md_degrades_equipping_hash_to_null_not_a_crash(tmp_path) -> None:
    empty_task_dir = tmp_path / "task-with-no-instruction"
    empty_task_dir.mkdir()
    record = build_result_record(
        trial_dir("awscdk", "genuine"),
        "awscdk",
        empty_task_dir,
        FAKE_DIGEST_IMAGE_REF,
        {},
    )
    assert record["validity_class"] == VALID
    assert record["equipping_hash"] is None
    assert "equipping_hash_error" in record


class TestTier1NotVerifiableMarker:
    """Residual finding (2026-08-06): a trial whose tier-1 policy declared a
    fact "not independently verifiable from plan JSON" (specs/SCHEMA.md
    §4.2.1) writes /logs/verifier/tier1-not-verifiable, but nothing read it
    back -- so that trial's row looked identical to one where tier-1 was
    fully checked and passed. gates/emit_result.py now reads the marker
    (host path <trial_dir>/verifier/tier1-not-verifiable, mirroring
    /logs/agent's own bind-mount convention) and surfaces it as
    tier1_not_verifiable (+ optional _detail) on the emitted row. These
    tests prove both directions: marker present -> True on the row; marker
    absent -> False (the schema's REQUIRED-with-default-false field).
    """

    def _trial_with_marker(self, tmp_path: Path, arm: str, detail: str | None) -> Path:
        """Copy the checked-in `genuine` fixture for `arm` into `tmp_path`
        and add a /logs/verifier/tier1-not-verifiable marker (host path
        verifier/tier1-not-verifiable) -- never mutates the checked-in
        fixture itself."""
        trial = tmp_path / "trial"
        shutil.copytree(trial_dir(arm, "genuine"), trial)
        verifier_dir = trial / "verifier"
        verifier_dir.mkdir(parents=True, exist_ok=True)
        marker = verifier_dir / "tier1-not-verifiable"
        marker.write_text(detail if detail is not None else "")
        return trial

    @pytest.mark.parametrize("arm", ARMS)
    def test_marker_absent_reads_false_with_no_detail(self, arm: str) -> None:
        # The checked-in genuine/ fixtures carry no verifier/ dir at all.
        present, detail = read_tier1_not_verifiable(trial_dir(arm, "genuine"))
        assert present is False
        assert detail is None

    @pytest.mark.parametrize("arm", ARMS)
    def test_marker_present_reads_true_with_detail(self, arm: str, tmp_path: Path) -> None:
        trial = self._trial_with_marker(
            tmp_path / arm,
            arm,
            "policy-actions-read-only: value unresolved, not independently verifiable",
        )
        present, detail = read_tier1_not_verifiable(trial)
        assert present is True
        assert detail == "policy-actions-read-only: value unresolved, not independently verifiable"

    def test_marker_present_but_empty_reads_true_with_no_detail(self, tmp_path: Path) -> None:
        trial = self._trial_with_marker(tmp_path, "awscdk", "")
        present, detail = read_tier1_not_verifiable(trial)
        assert present is True
        assert detail is None

    def test_absent_marker_yields_false_field_on_row(self, task_dir) -> None:
        record = build_result_record(
            trial_dir("awscdk", "genuine"), "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        assert record["tier1_not_verifiable"] is False
        assert record["tier1_not_verifiable_detail"] is None
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert row["tier1_not_verifiable"] is False
        assert "tier1_not_verifiable_detail" not in row
        assert validate_result(row) == []

    def test_present_marker_yields_true_field_and_detail_on_row(self, task_dir, tmp_path: Path) -> None:
        detail = "policy-actions-read-only: value unresolved, not independently verifiable"
        trial = self._trial_with_marker(tmp_path, "hcl-raw", detail)
        record = build_result_record(trial, "hcl-raw", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["tier1_not_verifiable"] is True
        assert record["tier1_not_verifiable_detail"] == detail
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert row["tier1_not_verifiable"] is True
        assert row["tier1_not_verifiable_detail"] == detail
        assert validate_result(row) == []

    def test_marker_does_not_affect_validity_or_reward(self, task_dir, tmp_path: Path) -> None:
        # tier1_not_verifiable is orthogonal to validity_class/reward -- the
        # marker is non-gating by construction (generator/gen.py's own
        # build_static_tiers_sh never lets it touch tier1_status or
        # reward.txt); this is the emit_result.py-side half of that
        # contract.
        trial = self._trial_with_marker(tmp_path, "awscdk", "some detail")
        record = build_result_record(trial, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["validity_class"] == VALID
        assert record["reward"] == 1.0
        assert record["tier1_not_verifiable"] is True

    def test_marker_present_on_an_invalid_trial_is_still_recorded(self, task_dir, tmp_path: Path) -> None:
        # A bypass trial still has the field on its record (always
        # attached, same as audit/infra) even though the row's own
        # score fields are zeroed -- read_tier1_not_verifiable() only
        # looks at the marker file, not validity_class.
        trial = tmp_path / "trial"
        shutil.copytree(trial_dir("awscdk", "bypass"), trial)
        (trial / "verifier").mkdir(parents=True, exist_ok=True)
        (trial / "verifier" / "tier1-not-verifiable").write_text("some detail")
        record = build_result_record(trial, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["validity_class"] == INVALID_BYPASS
        assert record["tier1_not_verifiable"] is True
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert row["tier1_not_verifiable"] is True
        assert validate_result(row) == []


class TestTierEvidence:
    """docs/iac-abstraction-aws-bench-plan.md Phase 2 item 3's per-catch
    tier-attribution table needs per-assert PASS/FAIL evidence from
    verifier/test-stdout.txt. See read_tier_evidence's own docstring for
    the tier-0-real / tier-1-bundle-only distinction these tests pin.
    """

    _REALISTIC_STDOUT = (
        "== build: npm run build ==\n"
        "== synth: npx cdk synth --no-lookups --quiet -o cdk.out ==\n"
        "\n"
        "== tier-0: structural asserts (2 applicable) ==\n"
        "  PASS [taskdef-exists]\n"
        "  FAIL [swappiness-value-correct]: op=eq expected=42 resolved=[41]\n"
        "\n"
        "== tier-1: cfn-guard ==\n"
        "# tier-1 (Rego/cfn-guard-graded) structural_asserts for this arm: (none)\n"
        "\n"
        "== summary: tier0_pass=0 tier1_status=SKIPPED_NO_ASSERTS ==\n"
    )

    def _trial_with_stdout(self, tmp_path: Path, arm: str, stdout: str) -> Path:
        trial = tmp_path / "trial"
        shutil.copytree(trial_dir(arm, "genuine"), trial)
        verifier_dir = trial / "verifier"
        verifier_dir.mkdir(parents=True, exist_ok=True)
        (verifier_dir / "test-stdout.txt").write_text(stdout)
        return trial

    def test_absent_file_returns_none(self) -> None:
        # The checked-in genuine/ fixtures carry no verifier/ dir at all.
        assert read_tier_evidence(trial_dir("awscdk", "genuine")) is None

    def test_realistic_output_parses_tier0_and_tier1_summary(self, tmp_path: Path) -> None:
        trial = self._trial_with_stdout(tmp_path, "awscdk", self._REALISTIC_STDOUT)
        evidence = read_tier_evidence(trial)
        assert evidence == {
            "tier0": {"taskdef-exists": "PASS", "swappiness-value-correct": "FAIL"},
            "tier1_status": "SKIPPED_NO_ASSERTS",
        }

    @pytest.mark.skipif(
        find_tool("terraform") is None or find_tool("jq") is None,
        reason="terraform and/or jq not found on PATH -- see oracles.tests.toolcheck.find_tool",
    )
    def test_real_generated_output_round_trips_through_read_tier_evidence(self) -> None:
        """Producer/consumer pinning (residual finding, 2026-08-06: "the
        per-catch tier-attribution pipeline rests on text-scraping ...
        with no producer<->consumer test" -- `_REALISTIC_STDOUT` above is a
        frozen, hand-written literal, never output captured from a real
        generated `tests/static_tiers.sh` run, so a format change in
        `generator/gen.py`'s PASS/FAIL echoes or its `== summary: ... ==`
        template would silently yield `tier0: {}` with nothing going red).

        Runs the REAL generated `tests/static_tiers.sh` for the toy spec's
        hcl_raw arm (smallest toolchain footprint -- same precedent as
        `gates/tests/test_oracle_falsifiability.py`, which needs neither
        `npm ci` nor a cdktn synth step) via
        `gates.oracle_falsifiability._run_solve`, and feeds its ACTUAL
        stdout through `read_tier_evidence()` -- not a hand-frozen
        literal. A future change to `generator/gen.py`'s echo/summary
        format now has to break THIS test too, not just the fixture above.
        """
        sys.path.insert(0, str(REPO_ROOT / "generator"))
        from gen import task_dir as _task_dir  # noqa: PLC0415
        from spec_model import load_spec  # noqa: PLC0415

        from gates.oracle_falsifiability import SOLVE_STUB_MARKER, _run_solve

        spec = load_spec(REPO_ROOT / "specs" / "_toy" / "toy-ssm-parameter.yaml")
        arm = "hcl_raw"
        task = _task_dir(spec, arm)
        solve_sh = task / "solution" / "solve.sh"
        if not solve_sh.exists() or SOLVE_STUB_MARKER in solve_sh.read_text():
            pytest.skip("toy hcl_raw solve.sh is still a generator stub")

        result = _run_solve(task, arm, solve_sh, "real-round-trip")
        assert result.reward == 1.0, f"reference solution should score 1.0: {result.detail[-2000:]}"

        import tempfile

        with tempfile.TemporaryDirectory() as tmp_s:
            trial = Path(tmp_s) / "trial"
            verifier_dir = trial / "verifier"
            verifier_dir.mkdir(parents=True)
            (verifier_dir / "test-stdout.txt").write_text(result.detail)

            evidence = read_tier_evidence(trial)

        assert evidence is not None
        assert evidence["tier0"], "expected at least one real tier-0 PASS/FAIL line"
        assert set(evidence["tier0"].values()) <= {"PASS", "FAIL"}
        assert evidence["tier1_status"] in (
            "PASS",
            "FAIL",
            "SKIPPED_NO_ASSERTS",
            "TOOL_MISSING",
            "SKIPPED_STUB",
        )


    def test_toolchain_failure_before_tier0_yields_empty_tier0_and_none_tier1(
        self, tmp_path: Path
    ) -> None:
        # Mirrors a real early exit: generator/gen.py's toolchain_block
        # writes reward.txt and `exit 0`'s before tier-0/1 ever run.
        trial = self._trial_with_stdout(tmp_path, "awscdk", "== build: npm run build ==\nBUILD FAILED\n")
        evidence = read_tier_evidence(trial)
        assert evidence == {"tier0": {}, "tier1_status": None}

    def test_various_tier1_status_values_parse(self, tmp_path: Path) -> None:
        for status in ("PASS", "FAIL", "TOOL_MISSING", "SKIPPED_STUB", "SKIPPED_NO_ASSERTS"):
            stdout = f"== summary: tier0_pass=1 tier1_status={status} ==\n"
            trial = self._trial_with_stdout(tmp_path / status, "awscdk", stdout)
            assert read_tier_evidence(trial)["tier1_status"] == status

    def test_wired_into_record_and_schema_valid_row(self, task_dir, tmp_path: Path) -> None:
        trial = self._trial_with_stdout(tmp_path, "hcl-raw", self._REALISTIC_STDOUT)
        record = build_result_record(trial, "hcl-raw", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["tier_evidence"] == {
            "tier0": {"taskdef-exists": "PASS", "swappiness-value-correct": "FAIL"},
            "tier1_status": "SKIPPED_NO_ASSERTS",
        }
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert row["tier_evidence"] == record["tier_evidence"]
        assert validate_result(row) == []

    def test_absent_evidence_omits_the_row_field_entirely(self, task_dir) -> None:
        # No verifier/test-stdout.txt in the checked-in genuine/ fixture.
        record = build_result_record(
            trial_dir("awscdk", "genuine"), "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        assert record["tier_evidence"] is None
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert "tier_evidence" not in row
        assert validate_result(row) == []

    def test_evidence_attached_even_on_an_invalid_trial(self, task_dir, tmp_path: Path) -> None:
        trial = tmp_path / "trial"
        shutil.copytree(trial_dir("awscdk", "bypass"), trial)
        (trial / "verifier").mkdir(parents=True, exist_ok=True)
        (trial / "verifier" / "test-stdout.txt").write_text(self._REALISTIC_STDOUT)
        record = build_result_record(trial, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["validity_class"] == INVALID_BYPASS
        assert record["tier_evidence"]["tier1_status"] == "SKIPPED_NO_ASSERTS"


class TestReadBudget:
    """gates/emit_result.py::read_budget -- the read side of the
    "MAX_TOKENS is inert and budget.json has no reader" fix (2026-08-06):
    scripts/run-bench.sh writes `<jobs-dir>/budget.json`; before this
    function nothing in the repo ever opened it.
    """

    def test_no_jobs_dir_returns_none_none(self) -> None:
        assert read_budget(None) == (None, None)

    def test_missing_file_returns_none_none(self, tmp_path: Path) -> None:
        assert read_budget(tmp_path) == (None, None)

    def test_reads_both_values(self, tmp_path: Path) -> None:
        (tmp_path / "budget.json").write_text(json.dumps({"max_iters": 8, "max_tokens": 50000}))
        assert read_budget(tmp_path) == (8, 50000)

    def test_null_max_tokens_is_none(self, tmp_path: Path) -> None:
        (tmp_path / "budget.json").write_text(json.dumps({"max_iters": 8, "max_tokens": None}))
        assert read_budget(tmp_path) == (8, None)

    def test_malformed_json_degrades_to_none_none(self, tmp_path: Path) -> None:
        (tmp_path / "budget.json").write_text("{not valid json")
        assert read_budget(tmp_path) == (None, None)


class TestResolveSplitGroup:
    """gates/emit_result.py::resolve_split_group -- populates the
    schema-REQUIRED split_group field (2026-08-06 fix: "the train/holdout
    split is unenforceable at the layer that matters -- the published
    number")."""

    def test_no_spec_id_is_unclassified(self) -> None:
        assert resolve_split_group(None) == "unclassified"

    def test_known_train_spec(self) -> None:
        # specs/split.yaml (checked in): ecs-swappiness/apigw-openapi ->
        # train, s3-lambda-log-retention/sfn-jsonata -> holdout.
        assert resolve_split_group("ecs-swappiness") == "train"

    def test_known_holdout_spec(self) -> None:
        assert resolve_split_group("sfn-jsonata") == "holdout"

    def test_unknown_spec_id_is_unclassified(self) -> None:
        assert resolve_split_group("not-a-real-spec-id") == "unclassified"


class TestNLlmCalls:
    """docs/iac-abstraction-aws-bench-plan.md Phase 2 item 3's
    iterations-to-green needs n_llm_calls, mirroring
    aws_bench/metrics/run_data.py::_llm_usage_from_trajectory's own
    accumulation exactly (see extract_n_llm_calls's own docstring)."""

    def _trial_with_trajectory(self, tmp_path: Path, extra_steps: list[dict]) -> Path:
        """Copy the checked-in genuine/awscdk fixture and APPEND
        `extra_steps` to its trajectory's own `steps` list (never replace
        wholesale) -- the fixture's original steps carry the real
        tsc/cdk-synth tool-call evidence the audit gate (gates/audit.py)
        needs to classify the trial as VALID in the first place; discarding
        them would make every test here exercise the invalid-bypass path
        instead of the n_llm_calls extraction this class is testing. The
        original steps carry no `metrics`/`llm_call_count` of their own
        (verified: gates/tests/fixtures/awscdk/genuine/agent/trajectory.json
        has neither key on any step), so they always contribute exactly 0
        to extract_n_llm_calls()'s sum -- safe to append to without
        disturbing this class's exact-count assertions.
        """
        trial = tmp_path / "trial"
        shutil.copytree(trial_dir("awscdk", "genuine"), trial)
        traj_path = trial / "agent" / "trajectory.json"
        data = json.loads(traj_path.read_text())
        data["steps"] = list(data.get("steps", [])) + extra_steps
        traj_path.write_text(json.dumps(data))
        return trial

    def test_no_trajectory_file_returns_none_not_zero(self, tmp_path: Path) -> None:
        # "unknown" (no trajectory to read at all) must never be
        # indistinguishable from "0" (a real, parsed zero-step answer) --
        # residual finding, 2026-08-06.
        trial = tmp_path / "trial"
        trial.mkdir()
        assert extract_n_llm_calls(trial) is None

    def test_malformed_trajectory_returns_none_not_zero(self, tmp_path: Path) -> None:
        trial = tmp_path / "trial"
        (trial / "agent").mkdir(parents=True)
        (trial / "agent" / "trajectory.json").write_text("{not valid json")
        assert extract_n_llm_calls(trial) is None

    def test_missing_steps_key_returns_none_not_zero(self, tmp_path: Path) -> None:
        trial = tmp_path / "trial"
        (trial / "agent").mkdir(parents=True)
        (trial / "agent" / "trajectory.json").write_text(json.dumps({"no_steps_key": True}))
        assert extract_n_llm_calls(trial) is None

    def test_checked_in_genuine_fixtures_have_no_per_step_metrics(self) -> None:
        # The hand-authored gates/tests fixtures were built for audit-gate
        # testing and carry no per-step `metrics`/`llm_call_count` --
        # extract_n_llm_calls degrades to 0 for them, matching upstream's
        # own "no signal" branch, not a crash or a guess.
        assert extract_n_llm_calls(trial_dir("awscdk", "genuine")) == 0

    def test_llm_call_count_int_is_summed(self, tmp_path: Path) -> None:
        steps = [
            {"source": "user", "message": "hi"},
            {"source": "agent", "llm_call_count": 2},
            {"source": "agent", "llm_call_count": 3},
        ]
        trial = self._trial_with_trajectory(tmp_path, steps)
        assert extract_n_llm_calls(trial) == 5

    def test_metrics_present_without_llm_call_count_counts_as_one(self, tmp_path: Path) -> None:
        steps = [
            {"source": "agent", "metrics": {"prompt_tokens": 10}},
            {"source": "agent", "metrics": {"prompt_tokens": 20}},
        ]
        trial = self._trial_with_trajectory(tmp_path, steps)
        assert extract_n_llm_calls(trial) == 2

    def test_non_agent_source_steps_are_ignored(self, tmp_path: Path) -> None:
        steps = [
            {"source": "user", "llm_call_count": 99},
            {"source": "observation", "metrics": {"prompt_tokens": 1}},
            {"source": "agent", "llm_call_count": 1},
        ]
        trial = self._trial_with_trajectory(tmp_path, steps)
        assert extract_n_llm_calls(trial) == 1

    def test_agent_step_with_neither_signal_contributes_zero(self, tmp_path: Path) -> None:
        steps = [{"source": "agent", "message": "just talking, no LLM metrics recorded"}]
        trial = self._trial_with_trajectory(tmp_path, steps)
        assert extract_n_llm_calls(trial) == 0

    def test_wired_into_record_and_row(self, task_dir, tmp_path: Path) -> None:
        steps = [{"source": "agent", "llm_call_count": 4}]
        trial = self._trial_with_trajectory(tmp_path, steps)
        record = build_result_record(trial, "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {})
        assert record["n_llm_calls"] == 4
        row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture")
        assert row["n_llm_calls"] == 4
        assert validate_result(row) == []

    def test_invalid_trial_never_computes_n_llm_calls(self, task_dir) -> None:
        # build_result_record only calls extract_n_llm_calls() on the VALID
        # branch (mirrors _extract_score_fields()'s own placement) -- an
        # invalid trial's record simply has no n_llm_calls key, same as it
        # has no reward/tokens.
        record = build_result_record(
            trial_dir("awscdk", "bypass"), "awscdk", task_dir, FAKE_DIGEST_IMAGE_REF, {}
        )
        assert "n_llm_calls" not in record


class TestToResultRowAutoCensoring:
    """to_result_row's censored=None auto-detection from max_iters/max_tokens
    (docs/iac-abstraction-aws-bench-plan.md Phase 2 item 2's budget cap)."""

    def _row_for(self, tokens_total: int, reward: float, n_llm_calls: int | None, **kwargs):
        record = {
            "arm": "awscdk",
            "validity_class": VALID,
            "equipping_hash": "a" * 64,
            "reward": reward,
            "n_input_tokens": tokens_total,
            "n_output_tokens": 0,
        }
        if n_llm_calls is not None:
            record["n_llm_calls"] = n_llm_calls
        return to_result_row(
            record, model="claude-sonnet-5", harness="empty", oracle_version="oracles@fixture", **kwargs
        )

    def test_no_budget_params_defaults_to_false_backward_compatible(self) -> None:
        row = self._row_for(tokens_total=999999, reward=0.0, n_llm_calls=999)
        assert row["censored"] is False

    def test_explicit_censored_wins_over_auto_detection(self) -> None:
        row = self._row_for(
            tokens_total=10, reward=0.0, n_llm_calls=1, censored=True, max_tokens=100000
        )
        assert row["censored"] is True

    def test_success_is_never_censored_even_over_budget(self) -> None:
        row = self._row_for(tokens_total=999999, reward=1.0, n_llm_calls=999, max_tokens=1000, max_iters=1)
        assert row["censored"] is False

    def test_tokens_over_max_tokens_is_censored(self) -> None:
        row = self._row_for(tokens_total=150000, reward=0.0, n_llm_calls=1, max_tokens=100000)
        assert row["censored"] is True

    def test_tokens_under_max_tokens_is_not_censored_by_tokens_alone(self) -> None:
        row = self._row_for(tokens_total=500, reward=0.0, n_llm_calls=1, max_tokens=100000)
        assert row["censored"] is False

    def test_iters_at_or_over_max_iters_is_censored(self) -> None:
        row = self._row_for(tokens_total=500, reward=0.0, n_llm_calls=8, max_iters=8)
        assert row["censored"] is True

    def test_missing_n_llm_calls_does_not_crash_max_iters_check(self) -> None:
        row = self._row_for(tokens_total=500, reward=0.0, n_llm_calls=None, max_iters=8)
        assert row["censored"] is False


def _stream_line(msg_id: str, usage: dict, uuid: str = "u") -> str:
    return json.dumps({"type": "assistant", "uuid": uuid,
                       "message": {"id": msg_id, "role": "assistant", "usage": usage, "content": []}})


def _result_line(usage: dict, cost: float) -> str:
    return json.dumps({"type": "result", "subtype": "success", "usage": usage, "total_cost_usd": cost, "num_turns": 3})


def test_tokens_recovered_from_claude_code_stream_when_result_json_has_none(tmp_path) -> None:
    """A harbor trajectory-conversion failure leaves agent_result token fields
    None while agent/claude-code.txt is complete; the transcript's terminal
    result event is then the source. Per-message usage is a streaming partial
    and is deliberately ignored."""
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({
        "verifier_result": {"rewards": {"reward": 1.0}},
        "agent_result": {"n_input_tokens": None, "n_cache_tokens": None, "n_output_tokens": None, "cost_usd": None},
    }))
    lines = [
        json.dumps({"type": "system", "subtype": "init"}),
        _stream_line("m1", {"input_tokens": 10, "cache_read_input_tokens": 100, "output_tokens": 2}),
        _stream_line("m2", {"input_tokens": 3, "cache_read_input_tokens": 200, "output_tokens": 4}),
        _result_line({"input_tokens": 20, "cache_creation_input_tokens": 50, "cache_read_input_tokens": 300, "output_tokens": 777}, 0.42),
    ]
    (trial / "agent" / "claude-code.txt").write_text("\n".join(lines) + "\n")

    out = _extract_score_fields(trial)

    assert out["reward"] == 1.0
    assert out["n_output_tokens"] == 777
    assert out["n_input_tokens"] == 20 + 50 + 300
    assert out["n_cache_tokens"] == 300
    assert out["cost_usd"] == 0.42
    assert out["tokens_source"] == "claude-code-stream"


def test_transcript_without_result_event_recovers_nothing(tmp_path) -> None:
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({
        "verifier_result": {"rewards": {"reward": 1.0}},
        "agent_result": {"n_input_tokens": None, "n_cache_tokens": None, "n_output_tokens": None, "cost_usd": None},
    }))
    (trial / "agent" / "claude-code.txt").write_text(_stream_line("m1", {"input_tokens": 1, "output_tokens": 1}) + "\n")
    out = _extract_score_fields(trial)
    assert out["n_output_tokens"] is None and "tokens_source" not in out


def test_transcript_fallback_does_not_override_harbor_totals(tmp_path) -> None:
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({
        "verifier_result": {"rewards": {"reward": 0.0}},
        "agent_result": {"n_input_tokens": 50, "n_cache_tokens": 40, "n_output_tokens": 9, "cost_usd": 0.01},
    }))
    (trial / "agent" / "claude-code.txt").write_text(_result_line({"input_tokens": 999, "output_tokens": 999}, 9.9) + "\n")
    out = _extract_score_fields(trial)
    assert out["n_output_tokens"] == 9 and out["cost_usd"] == 0.01
    assert "tokens_source" not in out
