"""Gates 2+3 over a trial Harbor left WITHOUT a ``trajectory.json``.

Harbor's Claude Code converter rejects its own output when a step id is
skipped (``steps[16].step_id: expected 17, got 18``,
docs/upstream/harbor-trajectory-step-id-gap.md), which leaves the complete
``agent/claude-code.txt`` stream transcript on disk and no trajectory. Before
the fallback proven here, such a trial was voided as ``invalid-infra`` /
``audit-unavailable`` — a harness defect silently deleting a real, fully
evidenced row from the scored denominator.

``fixtures/awscdk/no-trajectory/`` is the real trial that motivated this
(``jobs/amend43-promotion/…/ecs-swappiness-awscdk__vg96pLR``, reward 1.0),
reduced to the three files the gates read, with long tool output truncated.
Its expected numbers are therefore the trial's own: 3654 output tokens and
15 turns.
"""

from __future__ import annotations

import json
import shutil
from pathlib import Path

import pytest

from gates.audit import (
    AUDIT_SOURCE_STREAM,
    audit_trajectory,
    audit_trial,
    resolve_audit_sources,
    steps_from_claude_code_stream,
)
from gates.emit_result import (
    INVALID_BYPASS,
    INVALID_INFRA,
    VALID,
    build_result_record,
    extract_n_llm_calls,
    extract_n_llm_calls_per_step,
    to_result_row,
)
from gates.tests.conftest import FIXTURES_DIR, trial_dir
from gates.tests.test_emit_result_multistep import (
    STEP_NAMES,
    _multistep_task_dir,
    _multistep_trial_dir,
)
from metrics.validate_result import validate_result

NO_TRAJECTORY = FIXTURES_DIR / "awscdk" / "no-trajectory"
TASK_DIR = FIXTURES_DIR / "task-dir"
FAKE_DIGEST_IMAGE_REF = "cdktn-bench/awscdk@sha256:" + "0" * 64


def _transcript(calls: list[tuple[str, str, str]], *, num_turns: int = 3) -> str:
    """A minimal stream-json transcript: one assistant ``tool_use`` + one user
    ``tool_result`` per call, then the terminal ``result`` event.

    ``calls`` are ``(call_id, command, result_text)``. Deliberately hand-built
    rather than reduced from a real trial, so the bypass/degraded cases below
    say exactly what they test.
    """
    lines: list[str] = []
    for call_id, command, result_text in calls:
        lines.append(
            json.dumps(
                {
                    "type": "assistant",
                    "message": {
                        "id": f"msg_{call_id}",
                        "role": "assistant",
                        "content": [
                            {"type": "tool_use", "id": call_id, "name": "Bash", "input": {"command": command}}
                        ],
                    },
                }
            )
        )
        lines.append(
            json.dumps(
                {
                    "type": "user",
                    "message": {
                        "role": "user",
                        "content": [
                            {"tool_use_id": call_id, "type": "tool_result", "content": result_text, "is_error": False}
                        ],
                    },
                }
            )
        )
    lines.append(
        json.dumps(
            {
                "type": "result",
                "subtype": "success",
                "num_turns": num_turns,
                "total_cost_usd": 0.5,
                "usage": {"input_tokens": 11, "cache_read_input_tokens": 22, "output_tokens": 33},
            }
        )
    )
    return "\n".join(lines) + "\n"


def _trajectory(calls: list[tuple[str, str, str]]) -> dict:
    """The ATIF trajectory Harbor would have written for the same ``calls``."""
    return {
        "steps": [
            {
                "step_id": i,
                "source": "agent",
                "tool_calls": [
                    {"tool_call_id": call_id, "function_name": "Bash", "arguments": {"command": command}}
                ],
                "observation": {"results": [{"source_call_id": call_id, "content": result_text}]},
            }
            for i, (call_id, command, result_text) in enumerate(calls, start=1)
        ]
    }


def _trial_with_transcript(root: Path, calls: list[tuple[str, str, str]], *, reward: float = 1.0) -> Path:
    trial = root / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "agent" / "claude-code.txt").write_text(_transcript(calls))
    (trial / "result.json").write_text(
        json.dumps({"verifier_result": {"rewards": {"reward": reward}}, "agent_result": None})
    )
    return trial


# --- the real trial -------------------------------------------------------


def test_fixture_really_has_no_trajectory() -> None:
    """The whole point of the fixture: if a trajectory ever appears beside it,
    every assertion below stops testing the fallback."""
    assert not (NO_TRAJECTORY / "agent" / "trajectory.json").exists()
    assert (NO_TRAJECTORY / "agent" / "claude-code.txt").is_file()
    assert resolve_audit_sources(NO_TRAJECTORY) == [
        (NO_TRAJECTORY / "agent" / "claude-code.txt", AUDIT_SOURCE_STREAM)
    ]


def test_transcript_only_trial_audits_as_genuine_toolchain_use() -> None:
    report = audit_trial(NO_TRAJECTORY, "awscdk")
    assert report["valid"] is True
    assert report["degraded"] is False
    assert report["audit_source"] == AUDIT_SOURCE_STREAM
    assert report["bash_call_count"] >= 1
    assert {e["pattern"] for e in report["evidence"]} <= {"tsc", "cdk synth", "npm run build", "npm run synth"}
    # Every entry is addressable back into the transcript by its own toolu_ id.
    assert all(e["tool_call_id"].startswith("toolu_") for e in report["evidence"])


def test_transcript_only_row_is_valid_and_carries_the_trials_own_numbers() -> None:
    record = build_result_record(NO_TRAJECTORY, "awscdk", TASK_DIR, FAKE_DIGEST_IMAGE_REF)
    assert record["validity_class"] == VALID
    assert record["score_emitted"] is True
    assert record["reward"] == 1.0
    assert record["n_output_tokens"] == 3654
    assert record["n_llm_calls"] == 15
    assert record["audit_source"] == AUDIT_SOURCE_STREAM
    assert record["tokens_source"] == AUDIT_SOURCE_STREAM


def test_published_row_carries_the_provenance_and_still_validates() -> None:
    record = build_result_record(NO_TRAJECTORY, "awscdk", TASK_DIR, FAKE_DIGEST_IMAGE_REF)
    row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="dev")
    assert row["audit_source"] == AUDIT_SOURCE_STREAM
    assert row["tokens_source"] == AUDIT_SOURCE_STREAM
    assert row["reward"] == 1.0 and row["tokens_output"] == 3654 and row["n_llm_calls"] == 15
    validate_result(row)


def test_n_llm_calls_prefers_the_transcripts_own_num_turns() -> None:
    """num_turns (15) is harbor's own count and differs from the number of
    distinct assistant message ids (13) in this transcript, so the fallback
    must not substitute its own tally where the harness reported one."""
    assert extract_n_llm_calls_per_step(NO_TRAJECTORY) == {"trial": 15}
    ids = {
        json.loads(line)["message"]["id"]
        for line in (NO_TRAJECTORY / "agent" / "claude-code.txt").read_text().splitlines()
        if json.loads(line).get("type") == "assistant"
    }
    assert len(ids) != 15


# --- neither file ---------------------------------------------------------


def test_trial_with_neither_file_stays_audit_unavailable(tmp_path: Path) -> None:
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 1.0}}}))

    record = build_result_record(trial, "awscdk", TASK_DIR, FAKE_DIGEST_IMAGE_REF)
    assert record["validity_class"] == INVALID_INFRA
    assert record["infra"]["kind"] == "audit-unavailable"
    assert record["score_emitted"] is False
    assert "audit_source" not in record
    assert extract_n_llm_calls(trial) is None


# --- the fallback is the SAME audit, not a laxer one ----------------------


_BYPASS_CALLS = [
    ("toolu_a", "cat lib/scenario-stack.ts", "export class ScenarioStack {}"),
    ("toolu_b", "echo 'cdk synth' >> NOTES.md", ""),
    ("toolu_c", "grep -r 'swappiness' lib/", "lib/scenario-stack.ts: swappiness: 42"),
]


def test_transcript_showing_no_toolchain_run_is_invalid_bypass(tmp_path: Path) -> None:
    trial = _trial_with_transcript(tmp_path, _BYPASS_CALLS)
    report = audit_trial(trial, "awscdk")
    assert report["valid"] is False
    assert report["evidence"] == []
    assert "invalid-bypass" in report["reason"]
    assert report["bash_call_count"] == len(_BYPASS_CALLS)

    record = build_result_record(trial, "awscdk", TASK_DIR, FAKE_DIGEST_IMAGE_REF)
    assert record["validity_class"] == INVALID_BYPASS
    assert record["score_emitted"] is False


@pytest.mark.parametrize(
    "calls",
    [
        _BYPASS_CALLS,
        [("toolu_a", "npm run build && npx cdk synth", "Successfully synthesized to cdk.out")],
        [("toolu_a", "cdk synth", "bash: cdk: command not found")],
    ],
)
def test_transcript_and_trajectory_reach_the_same_verdict(tmp_path: Path, calls: list) -> None:
    """The reconstruction is faithful, not lenient: the same tool calls audit
    identically whether they were read from the transcript or from the ATIF
    trajectory Harbor would have written for them — including the
    degraded-arm classification, which is what separates invalid-infra from
    invalid-bypass."""
    from_stream = audit_trial(_trial_with_transcript(tmp_path, calls), "awscdk")
    from_trajectory = audit_trajectory(_trajectory(calls), "awscdk")

    for key in ("valid", "degraded", "degraded_kind", "reason", "bash_call_count"):
        assert from_stream[key] == from_trajectory[key], key
    assert [(e["step_id"], e["tool_call_id"], e["pattern"], e["status"]) for e in from_stream["evidence"]] == [
        (e["step_id"], e["tool_call_id"], e["pattern"], e["status"]) for e in from_trajectory["evidence"]
    ]


def test_structured_exit_code_in_the_transcript_marks_a_degraded_arm(tmp_path: Path) -> None:
    """Claude Code records the Bash exit code on the user event's own
    ``tool_use_result``; the fallback hands it to the audit under
    ``extra.metadata`` exactly where Harbor puts it, so exit 127 still reads
    as a degraded arm (invalid-infra) rather than as an agent bypass."""
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    lines = [
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "cdk synth"}}
                    ],
                },
            }
        ),
        json.dumps(
            {
                "type": "user",
                "message": {
                    "role": "user",
                    "content": [{"tool_use_id": "toolu_1", "type": "tool_result", "content": "", "is_error": True}],
                },
                "tool_use_result": {"stdout": "", "stderr": "cdk: not found", "exitCode": 127},
            }
        ),
        json.dumps({"type": "result", "subtype": "error", "num_turns": 2, "usage": {"output_tokens": 1}}),
    ]
    (trial / "agent" / "claude-code.txt").write_text("\n".join(lines) + "\n")
    (trial / "result.json").write_text(json.dumps({"verifier_result": {"rewards": {"reward": 0.0}}}))

    report = audit_trial(trial, "awscdk")
    assert report["degraded"] is True
    assert report["degraded_kind"] == "missing"

    record = build_result_record(trial, "awscdk", TASK_DIR, FAKE_DIGEST_IMAGE_REF)
    assert record["validity_class"] == INVALID_INFRA
    assert record["infra"]["kind"] == "toolchain-missing"


def test_a_call_whose_result_never_arrived_is_unknown_not_degraded(tmp_path: Path) -> None:
    """An interrupted transcript's last tool_use has no tool_result. Absence of
    an observation is not evidence the toolchain was unavailable, so the call
    stays creditable — the same treatment a trajectory gives it."""
    trial = tmp_path / "trial"
    (trial / "agent").mkdir(parents=True)
    (trial / "agent" / "claude-code.txt").write_text(
        json.dumps(
            {
                "type": "assistant",
                "message": {
                    "id": "msg_1",
                    "role": "assistant",
                    "content": [
                        {"type": "tool_use", "id": "toolu_1", "name": "Bash", "input": {"command": "cdk synth"}}
                    ],
                },
            }
        )
        + "\n"
    )
    report = audit_trial(trial, "awscdk")
    assert [e["status"] for e in report["evidence"]] == ["unknown"]
    assert report["valid"] is True and report["degraded"] is False


def test_transcript_step_ids_are_gapless_by_construction() -> None:
    """The upstream defect is a step-id gap produced by pairing tool results to
    calls in TIMESTAMP order. This reconstruction pairs in transcript order and
    numbers the calls it emits, so it cannot reproduce the gap."""
    steps = steps_from_claude_code_stream(NO_TRAJECTORY / "agent" / "claude-code.txt")
    assert [s["step_id"] for s in steps] == list(range(1, len(steps) + 1))


# --- rows that HAVE a trajectory are untouched ----------------------------


def test_trajectory_backed_audit_record_has_no_audit_source() -> None:
    report = audit_trial(trial_dir("awscdk", "genuine"), "awscdk")
    assert "audit_source" not in report
    record = build_result_record(trial_dir("awscdk", "genuine"), "awscdk", TASK_DIR, FAKE_DIGEST_IMAGE_REF)
    assert record["validity_class"] == VALID
    assert "audit_source" not in record
    row = to_result_row(record, model="claude-sonnet-5", harness="empty", oracle_version="dev")
    assert "audit_source" not in row


def test_trajectory_wins_when_both_files_are_present(tmp_path: Path) -> None:
    """The transcript is a fallback, never a second opinion: a trial with both
    files is audited from the trajectory and its record is unchanged."""
    trial = tmp_path / "trial"
    shutil.copytree(trial_dir("awscdk", "genuine"), trial)
    (trial / "agent" / "claude-code.txt").write_text(_transcript(_BYPASS_CALLS))

    report = audit_trial(trial, "awscdk")
    assert "audit_source" not in report
    assert report["valid"] is True
    assert report["trajectory_path"] == str(trial / "agent" / "trajectory.json")


# --- multi-step: the fallback is per step ---------------------------------


def test_multistep_falls_back_only_for_the_step_that_lost_its_trajectory(tmp_path: Path) -> None:
    trial = _multistep_trial_dir(tmp_path)
    task = _multistep_task_dir(tmp_path)
    lost, kept = STEP_NAMES
    (trial / "steps" / lost / "agent" / "trajectory.json").unlink()
    shutil.copyfile(
        NO_TRAJECTORY / "agent" / "claude-code.txt",
        trial / "steps" / lost / "agent" / "claude-code.txt",
    )

    sources = resolve_audit_sources(trial)
    assert [p.parent.parent.name for p, _ in sources] == [lost, kept]
    assert [kind for _, kind in sources] == [AUDIT_SOURCE_STREAM, "trajectory"]

    report = audit_trial(trial, "awscdk")
    assert report["valid"] is True
    assert report["audit_source"] == AUDIT_SOURCE_STREAM
    # Both steps contributed; neither was silently dropped.
    assert sorted({e["step_name"] for e in report["evidence"]}) == sorted(STEP_NAMES)

    per_step = extract_n_llm_calls_per_step(trial)
    assert per_step[lost] == 15
    assert per_step[kept] is not None
    record = build_result_record(trial, "awscdk", task, FAKE_DIGEST_IMAGE_REF)
    assert record["validity_class"] == VALID
    assert record["audit_source"] == AUDIT_SOURCE_STREAM
    assert record["n_llm_calls"] == sum(per_step.values())
