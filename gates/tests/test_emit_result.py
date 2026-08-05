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
from pathlib import Path

import pytest

from gates.emit_result import (
    INVALID_BYPASS,
    INVALID_INFRA,
    VALID,
    build_result_record,
    classify_infra_failure,
    to_result_row,
)
from gates.tests.conftest import ARMS, SCENARIOS, trial_dir
from metrics.validate_result import validate_result

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
