"""Gate 2 (gates/audit.py) proven against the synthetic per-arm fixtures.

Each arm has a genuine-use trajectory (toolchain actually invoked -> valid)
and a bypass trajectory (agent greps/cats its way to "done" without ever
running the arm's tool -> invalid-bypass). See gates/tests/fixtures/<arm>/.
"""

from __future__ import annotations

import json

import pytest

from gates.audit import (
    KNOWN_ARMS,
    audit_trajectory,
    audit_trial,
    resolve_trajectory_path,
)
from gates.tests.conftest import ARMS, trial_dir

assert set(ARMS) == set(KNOWN_ARMS), "fixture arms and gate-known arms must match 1:1"


@pytest.mark.parametrize("arm", ARMS)
def test_genuine_use_is_valid(arm: str) -> None:
    report = audit_trial(trial_dir(arm, "genuine"), arm)
    assert report["valid"] is True
    assert report["evidence"], "genuine-use fixture must produce at least one evidence entry"
    assert report["bash_call_count"] >= 1
    for entry in report["evidence"]:
        assert entry["step_id"] is not None
        assert entry["tool_call_id"]
        assert entry["pattern"]
        assert entry["command"]
    assert "invoked" in report["reason"]


@pytest.mark.parametrize("arm", ARMS)
def test_bypass_is_invalid(arm: str) -> None:
    report = audit_trial(trial_dir(arm, "bypass"), arm)
    assert report["valid"] is False
    assert report["evidence"] == []
    assert "invalid-bypass" in report["reason"]
    # The bypass fixtures do run Bash (cat/grep/node -e) — proving this is a
    # false-negative check (no evidence) rather than a "no Bash calls at all"
    # vacuous pass.
    assert report["bash_call_count"] >= 1


@pytest.mark.parametrize("arm", ARMS)
def test_evidence_matches_expected_pattern_name(arm: str) -> None:
    expected_pattern_names = {
        "awscdk": {"tsc", "cdk synth"},
        "hcl-raw": {"terraform validate", "terraform plan"},
        "terraconstructs": {"cdktn synth"},
    }[arm]
    report = audit_trial(trial_dir(arm, "genuine"), arm)
    found = {e["pattern"] for e in report["evidence"]}
    assert found <= expected_pattern_names
    assert found, "expected at least one recognized pattern name"


def test_cross_arm_patterns_do_not_cross_match() -> None:
    """A terraconstructs-style `cdktn synth` must NOT satisfy awscdk's `cdk synth`."""
    trajectory = {
        "agent": {"name": "x", "version": "1"},
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "message": "synth",
                "tool_calls": [
                    {
                        "tool_call_id": "c1",
                        "function_name": "Bash",
                        "arguments": {"command": "npx --no-install cdktn synth"},
                    }
                ],
            }
        ],
    }
    awscdk_report = audit_trajectory(trajectory, "awscdk")
    assert awscdk_report["valid"] is False

    terraconstructs_report = audit_trajectory(trajectory, "terraconstructs")
    assert terraconstructs_report["valid"] is True


def test_non_bash_tool_calls_are_ignored() -> None:
    """A `Write`/`Edit` tool call that merely contains the word "synth" in its
    payload must not count as toolchain evidence — only Bash invocations do."""
    trajectory = {
        "agent": {"name": "x", "version": "1"},
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "message": "writing a note",
                "tool_calls": [
                    {
                        "tool_call_id": "c1",
                        "function_name": "Write",
                        "arguments": {"file_path": "/app/notes.md", "content": "remember to run cdk synth later"},
                    }
                ],
            }
        ],
    }
    report = audit_trajectory(trajectory, "awscdk")
    assert report["valid"] is False
    assert report["bash_call_count"] == 0


@pytest.mark.parametrize(
    "arm,command",
    [
        ("awscdk", "echo 'cdk synth'"),
        ("awscdk", "# TODO: run cdk synth later"),
        ("awscdk", "echo 'we would run cdk synth here' >> notes.md"),
        ("awscdk", "grep -r 'cdk synth' ."),
        ("awscdk", "cat cdk-synth-notes.txt"),
        ("awscdk", "which tsc"),
        ("awscdk", "printf 'tsc\\n'"),
        ("awscdk", "man cdk | grep synth"),
        ("hcl-raw", "echo terraform validate"),
        ("hcl-raw", "cat terraform-plan-notes.txt"),
        ("terraconstructs", "echo 'cdktn synth'"),
    ],
)
def test_mention_without_invocation_is_not_evidence(arm: str, command: str) -> None:
    """Regression test for the Gate 2 "defeated by echo" finding: a Bash
    command that merely *mentions* the arm's tool (as an argument to
    echo/printf/grep/cat/which/man, or inside a `#`-comment) must never
    satisfy the audit — only a genuine argv[0]-position invocation may."""
    trajectory = {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {"tool_call_id": "c1", "function_name": "Bash", "arguments": {"command": command}}
                ],
            }
        ]
    }
    report = audit_trajectory(trajectory, arm)
    assert report["valid"] is False, f"{command!r} should NOT satisfy {arm}'s toolchain evidence"
    assert report["evidence"] == []


def test_echo_bypass_end_to_end_via_shipped_bypass_fixture(tmp_path) -> None:
    """End-to-end reproduction of the finding: take the shipped bypass
    fixture, append one step whose command merely echoes the toolchain
    name, and confirm the trajectory-level audit still reports invalid."""
    import shutil

    src = trial_dir("awscdk", "bypass")
    dst = tmp_path / "bypass-plus-echo"
    shutil.copytree(src, dst)

    traj_path = dst / "agent" / "trajectory.json"
    traj = json.loads(traj_path.read_text())
    traj["steps"].append(
        {
            "step_id": 99,
            "source": "agent",
            "message": "one more check",
            "tool_calls": [
                {
                    "tool_call_id": "call_attack",
                    "function_name": "Bash",
                    "arguments": {"command": "echo 'cdk synth would go here'"},
                }
            ],
        }
    )
    traj_path.write_text(json.dumps(traj))

    report = audit_trial(dst, "awscdk")
    assert report["valid"] is False
    assert report["evidence"] == []


@pytest.mark.parametrize(
    "arm,command",
    [
        ("awscdk", "cat > NOTES.md <<'EOF'\nRun the build with:\ncdk synth\nEOF"),
        ("awscdk", 'echo "step 1: edit\ncdk synth\ndone"'),
        ("hcl-raw", "cat > NOTES.md <<'EOF'\nRun the build with:\nterraform validate\nEOF"),
    ],
)
def test_multiline_mention_via_heredoc_or_quoted_newline_is_not_evidence(arm: str, command: str) -> None:
    """Regression test for the round-2 Gate 2 finding: a heredoc body (data
    written to a file) or a quoted string containing embedded newlines must
    not be shredded into per-line segments by a naive newline-split -- doing
    so let a NOTES.md/agent-output.txt heredoc, or a multi-line quoted echo,
    smuggle a matching argv[0] line past the audit."""
    trajectory = {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {"tool_call_id": "c1", "function_name": "Bash", "arguments": {"command": command}}
                ],
            }
        ]
    }
    report = audit_trajectory(trajectory, arm)
    assert report["valid"] is False, f"{command!r} should NOT satisfy {arm}'s toolchain evidence"
    assert report["evidence"] == []


def test_real_invocation_immediately_after_a_heredoc_still_counts() -> None:
    """The heredoc-stripping fix must not over-strip: a genuine toolchain
    invocation on the line right after a heredoc's terminator is a real,
    separate command and must still be credited as evidence."""
    trajectory = {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {
                        "tool_call_id": "c1",
                        "function_name": "Bash",
                        "arguments": {"command": "python3 - <<PY\nprint(1)\nPY\ncdk synth"},
                    }
                ],
            }
        ]
    }
    report = audit_trajectory(trajectory, "awscdk")
    assert report["valid"] is True
    assert report["evidence"], "the cdk synth line following the heredoc must be recognized"


def test_heredoc_bypass_end_to_end_via_shipped_bypass_fixture(tmp_path) -> None:
    """End-to-end reproduction of the round-2 finding: take the shipped
    bypass fixture, append one step that writes a heredoc mentioning the
    toolchain, and confirm the trajectory-level audit still reports invalid."""
    import shutil

    src = trial_dir("awscdk", "bypass")
    dst = tmp_path / "bypass-plus-heredoc"
    shutil.copytree(src, dst)

    traj_path = dst / "agent" / "trajectory.json"
    traj = json.loads(traj_path.read_text())
    traj["steps"].append(
        {
            "step_id": 99,
            "source": "agent",
            "message": "writing notes",
            "tool_calls": [
                {
                    "tool_call_id": "call_attack",
                    "function_name": "Bash",
                    "arguments": {"command": "cat > NOTES.md <<'EOF'\nRun the build with:\ncdk synth\nEOF"},
                }
            ],
        }
    )
    traj_path.write_text(json.dumps(traj))

    report = audit_trial(dst, "awscdk")
    assert report["valid"] is False
    assert report["evidence"] == []


def test_unknown_arm_raises() -> None:
    with pytest.raises(ValueError):
        audit_trajectory({"agent": {}, "steps": []}, "pulumi")


def test_missing_trajectory_raises(tmp_path) -> None:
    with pytest.raises(FileNotFoundError):
        resolve_trajectory_path(tmp_path / "does-not-exist")


def test_audit_trial_accepts_trajectory_json_path_directly(arm="awscdk") -> None:
    path = trial_dir(arm, "genuine") / "agent" / "trajectory.json"
    report = audit_trial(path, arm)
    assert report["valid"] is True
    assert report["trajectory_path"] == str(path)


def _traj_with_observation(command: str, content: str) -> dict:
    return {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {"tool_call_id": "c1", "function_name": "Bash", "arguments": {"command": command}}
                ],
                "observation": {"results": [{"source_call_id": "c1", "content": content}]},
            }
        ]
    }


class TestObservationBasedDegradedToolchain:
    """Regression tests for the finding: audit.py previously never inspected
    ``steps[].observation``, so a matched Bash call scored valid=True even
    when the toolchain was never actually installed (command not found /
    exit 127) or was SIGKILLed (exit 137) before it could run."""

    def test_command_not_found_is_not_valid_evidence(self) -> None:
        traj = _traj_with_observation(
            "npx --no-install cdk synth", "bash: cdk: command not found\nExit code 127"
        )
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is False
        assert report["degraded"] is True
        assert report["degraded_kind"] == "missing"
        assert report["evidence"][0]["status"] == "missing"

    def test_sigkill_is_not_valid_evidence(self) -> None:
        traj = _traj_with_observation("npx --no-install tsc --noEmit", "Killed\nExit code 137")
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is False
        assert report["degraded"] is True
        assert report["degraded_kind"] == "sigkill"

    def test_genuine_tool_failure_still_counts_as_valid(self) -> None:
        """A failed cdk synth (the tool ran, and errored) is different from
        a missing/SIGKILLed tool — it still proves the agent tried the real
        toolchain, per the module's own long-standing rationale."""
        traj = _traj_with_observation(
            "npx --no-install cdk synth",
            "Error: stack validation failed\nsynthesis error TS2345",
        )
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] == "failed"

    def test_missing_observation_is_not_treated_as_degraded(self) -> None:
        """No observation captured at all (the pre-existing, more common
        case in these fixtures) must not be misclassified as a degraded
        arm -- it falls back to the prior, more permissive behavior."""
        traj = {
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
                }
            ]
        }
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] == "unknown"

    def test_self_authored_command_not_found_echo_does_not_degrade(self) -> None:
        """Regression test for the round-2 "self-void via observation text"
        finding: an agent chaining a real toolchain call with its own
        `echo 'command not found'` must not degrade the call -- the bare
        phrase, unanchored to the matched tool's own name, must never
        satisfy the missing-toolchain classifier."""
        traj = _traj_with_observation(
            "npx --no-install cdk synth; echo 'command not found'",
            "Stack failed to synthesize: TypeError …\ncommand not found",
        )
        report = audit_trajectory(traj, "awscdk")
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] != "missing"

    def test_genuine_enoent_is_not_toolchain_missing(self) -> None:
        """A real Node/cdk ENOENT (missing project file, not a missing
        binary) must not misclassify as a degraded arm -- "no such file or
        directory" is dropped from the missing-toolchain pattern entirely."""
        traj = _traj_with_observation(
            "npx --no-install cdk synth",
            "Error: ENOENT: no such file or directory, open '/app/project/cdk.json'",
        )
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] != "missing"

    def test_exit_code_phrase_in_prose_is_not_terminal_line_sigkill(self) -> None:
        """An exit-code phrase mentioned mid-sentence, not as the observation's
        own terminal status line, must not satisfy the sigkill classifier."""
        traj = _traj_with_observation(
            "npx --no-install cdk synth",
            "Synth failed with exit 137 mentioned in the log",
        )
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] != "sigkill"

    def test_command_not_found_for_a_different_tool_does_not_degrade(self) -> None:
        """"command not found" anchored to an unrelated tool name (not the
        one this call actually matched) must not degrade the match -- the
        anchor is to THIS call's own matched tool, not any tool at all."""
        traj = _traj_with_observation("npx --no-install cdk synth", "bash: jq: command not found")
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] != "missing"

    def test_real_claude_code_exit_code_format_still_detected(self) -> None:
        """The anchoring fix must not over-correct: claude_code.py's own
        `_format_tool_result` emits a literal `[exit_code] N` terminal line
        (harbor/agents/installed/claude_code.py) -- that real shape must
        still classify as missing/sigkill."""
        traj = _traj_with_observation("npx --no-install cdk synth", "[stdout]\nsome output\n[exit_code] 127")
        report = audit_trajectory(traj, "awscdk")
        assert report["degraded"] is True
        assert report["degraded_kind"] == "missing"

    def test_mixed_evidence_one_ok_call_is_enough(self) -> None:
        """A first attempt that hit command-not-found followed by a working
        retry must still be valid -- there IS real evidence the tool ran."""
        traj = {
            "steps": [
                {
                    "step_id": 1,
                    "source": "agent",
                    "tool_calls": [
                        {"tool_call_id": "c1", "function_name": "Bash", "arguments": {"command": "cdk synth"}}
                    ],
                    "observation": {"results": [{"source_call_id": "c1", "content": "cdk: command not found"}]},
                },
                {
                    "step_id": 2,
                    "source": "agent",
                    "tool_calls": [
                        {
                            "tool_call_id": "c2",
                            "function_name": "Bash",
                            "arguments": {"command": "npx --no-install cdk synth"},
                        }
                    ],
                    "observation": {
                        "results": [{"source_call_id": "c2", "content": "Synthesized ExampleStack.template.json"}]
                    },
                },
            ]
        }
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        statuses = {e["status"] for e in report["evidence"]}
        assert statuses == {"missing", "ok"}


def test_fixtures_are_well_formed_json() -> None:
    for arm in ARMS:
        for scenario in ("genuine", "bypass"):
            path = trial_dir(arm, scenario) / "agent" / "trajectory.json"
            data = json.loads(path.read_text())
            assert data["steps"], f"{path} must have at least one step"


def _traj_single_bash(command: str) -> dict:
    return {
        "steps": [
            {
                "step_id": 1,
                "source": "agent",
                "tool_calls": [
                    {"tool_call_id": "c1", "function_name": "Bash", "arguments": {"command": command}}
                ],
            }
        ]
    }


class TestCommonShellFormsAreCredited:
    """Regression tests for the finding: genuine invocations of the arm's
    toolchain wrapped in common shell forms (timeout, a subshell, an
    if/then, `bash -c '...'`, a versioned npx package) were not credited as
    evidence, producing a false invalid-bypass verdict for a trial that
    genuinely ran the real toolchain."""

    @pytest.mark.parametrize(
        "command",
        [
            "timeout 600 cdk synth",
            "(cd app && cdk synth)",
            "if [ -f cdk.json ]; then cdk synth; fi",
            "bash -c 'cdk synth'",
            "npx -y aws-cdk@2 synth",
        ],
        ids=[
            "timeout-wrapper",
            "subshell-parens",
            "if-then",
            "bash-c-string",
            "npx-versioned-package",
        ],
    )
    def test_awscdk_forms_yield_evidence(self, command: str) -> None:
        report = audit_trajectory(_traj_single_bash(command), "awscdk")
        assert report["valid"] is True, f"{command!r} should be credited as awscdk toolchain evidence"
        assert report["evidence"], f"{command!r} should produce at least one evidence entry"
        assert report["evidence"][0]["pattern"] == "cdk synth"

    @pytest.mark.parametrize(
        "command",
        [
            "timeout 600 terraform validate",
            "(cd infra && terraform plan)",
            "if [ -f main.tf ]; then terraform validate; fi",
            "bash -c 'terraform validate'",
        ],
        ids=["timeout-wrapper", "subshell-parens", "if-then", "bash-c-string"],
    )
    def test_hcl_raw_forms_yield_evidence(self, command: str) -> None:
        report = audit_trajectory(_traj_single_bash(command), "hcl-raw")
        assert report["valid"] is True, f"{command!r} should be credited as hcl-raw toolchain evidence"
        assert report["evidence"], f"{command!r} should produce at least one evidence entry"

    def test_do_keyword_form_is_credited(self) -> None:
        """A `for`/`do` loop body is another compound-statement form whose
        segment starts with the bare `do` keyword after `_segments` splits
        on `;` — analogous to the `then`/`else` cases."""
        report = audit_trajectory(_traj_single_bash("for i in 1; do cdk synth; done"), "awscdk")
        assert report["valid"] is True
        assert report["evidence"]

    def test_else_keyword_form_is_credited(self) -> None:
        report = audit_trajectory(
            _traj_single_bash("if [ ! -f out.json ]; then echo skip; else cdk synth; fi"), "awscdk"
        )
        assert report["valid"] is True
        assert report["evidence"]

    @pytest.mark.parametrize(
        "command",
        [
            "nice -n 10 cdk synth",
            "ionice -c2 -n7 cdk synth",
            "stdbuf -oL cdk synth",
        ],
        ids=["nice", "ionice", "stdbuf"],
    )
    def test_additional_process_wrappers_are_peeled(self, command: str) -> None:
        """The hint's full wrapper list (timeout/nice/ionice/stdbuf) beyond
        just the one verified `timeout` form."""
        report = audit_trajectory(_traj_single_bash(command), "awscdk")
        assert report["valid"] is True, f"{command!r} should be credited as awscdk toolchain evidence"

    def test_bash_c_recursion_does_not_defeat_cross_arm_isolation(self) -> None:
        """`bash -c 'cdktn synth'` must still only satisfy terraconstructs,
        never awscdk -- the recursion re-runs the same positional matcher,
        it doesn't loosen it."""
        report = audit_trajectory(_traj_single_bash("bash -c 'cdktn synth'"), "awscdk")
        assert report["valid"] is False

        report = audit_trajectory(_traj_single_bash("bash -c 'cdktn synth'"), "terraconstructs")
        assert report["valid"] is True

    def test_sh_c_form_is_also_recursed(self) -> None:
        report = audit_trajectory(_traj_single_bash("sh -c 'terraform validate'"), "hcl-raw")
        assert report["valid"] is True

    def test_bash_c_mention_without_invocation_still_not_evidence(self) -> None:
        """A `bash -c` string that merely *echoes* the tool name (rather
        than invoking it) must still not satisfy the audit -- recursion
        re-applies the same positional matcher to the inner string, it
        doesn't switch to substring search."""
        report = audit_trajectory(_traj_single_bash("bash -c 'echo cdk synth'"), "awscdk")
        assert report["valid"] is False
        assert report["evidence"] == []


class TestStructuredExitCodeOverridesForgedObservationText:
    """Regression tests for the finding: an agent could suppress a real
    tool's output and print its own anchored fake status line (e.g. `bash:
    cdk: command not found`) to route a genuinely-valid trial to
    invalid-infra. Harbor's claude_code.py records a structured exit code
    on the matching step's `extra.metadata.tool_use_result` (`exitCode`/
    `exit_code`) -- when present and unambiguous, that structured signal
    must be trusted over the agent-controlled observation text."""

    @staticmethod
    def _traj(command: str, content: str, exit_code: int) -> dict:
        return {
            "steps": [
                {
                    "step_id": 1,
                    "source": "agent",
                    "tool_calls": [
                        {"tool_call_id": "c1", "function_name": "Bash", "arguments": {"command": command}}
                    ],
                    "observation": {"results": [{"source_call_id": "c1", "content": content}]},
                    "extra": {"metadata": {"tool_use_result": {"exitCode": exit_code}}},
                }
            ]
        }

    def test_forged_command_not_found_text_does_not_degrade_a_real_success(self) -> None:
        traj = self._traj(
            "npx --no-install cdk synth",
            "bash: cdk: command not found\nExit code 127",
            exit_code=0,
        )
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] == "ok"

    def test_structured_missing_wins_even_with_benign_text(self) -> None:
        traj = self._traj(
            "npx --no-install cdk synth",
            "Synthesized ExampleStack.template.json",
            exit_code=127,
        )
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is False
        assert report["degraded"] is True
        assert report["degraded_kind"] == "missing"
        assert report["evidence"][0]["status"] == "missing"

    def test_structured_sigkill_is_trusted(self) -> None:
        traj = self._traj("npx --no-install cdk synth", "looks totally fine", exit_code=137)
        report = audit_trajectory(traj, "awscdk")
        assert report["degraded"] is True
        assert report["degraded_kind"] == "sigkill"

    def test_structured_nonzero_other_than_127_137_is_failed_not_missing(self) -> None:
        traj = self._traj("npx --no-install cdk synth", "stack validation error", exit_code=1)
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is True
        assert report["degraded"] is False
        assert report["evidence"][0]["status"] == "failed"

    def test_exit_code_field_variant_is_also_read(self) -> None:
        """`exit_code` (snake_case) alongside `exitCode` -- some producers
        may use either key; both must be honored."""
        traj = {
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
                    "extra": {"metadata": {"tool_use_result": {"exit_code": 0}}},
                }
            ]
        }
        report = audit_trajectory(traj, "awscdk")
        assert report["evidence"][0]["status"] == "ok"

    def test_ambiguous_multi_call_step_falls_back_to_text(self) -> None:
        """A step's `extra` is step-level, not per-call -- when a step
        carries more than one tool call, the structured exit code can't be
        unambiguously attributed to this specific Bash call, so the gate
        must fall back to the pre-existing text-based classification
        (still anchored) rather than misapplying someone else's exit code."""
        traj = {
            "steps": [
                {
                    "step_id": 1,
                    "source": "agent",
                    "tool_calls": [
                        {
                            "tool_call_id": "c1",
                            "function_name": "Bash",
                            "arguments": {"command": "npx --no-install cdk synth"},
                        },
                        {
                            "tool_call_id": "c2",
                            "function_name": "Bash",
                            "arguments": {"command": "echo done"},
                        },
                    ],
                    "observation": {
                        "results": [
                            {"source_call_id": "c1", "content": "Synthesized ExampleStack.template.json"}
                        ]
                    },
                    "extra": {"metadata": {"tool_use_result": {"exitCode": 127}}},
                }
            ]
        }
        report = audit_trajectory(traj, "awscdk")
        # Structured code (127) is ambiguous across 2 tool_calls in this step
        # so it must NOT be applied; text-based classification (benign
        # synth output, no anchored failure) yields "ok".
        assert report["valid"] is True
        assert report["evidence"][0]["status"] == "ok"

    def test_no_extra_field_falls_back_to_prior_text_behavior(self) -> None:
        """Trajectories without any `extra.metadata` (the pre-existing,
        far more common shape in these fixtures) must behave exactly as
        before -- pure text-based classification."""
        traj = _traj_single_bash("npx --no-install cdk synth")
        traj["steps"][0]["observation"] = {
            "results": [{"source_call_id": "c1", "content": "bash: cdk: command not found"}]
        }
        report = audit_trajectory(traj, "awscdk")
        assert report["valid"] is False
        assert report["degraded"] is True
        assert report["evidence"][0]["status"] == "missing"
