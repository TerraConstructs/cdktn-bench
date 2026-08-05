#!/bin/bash
# Verifier entry point for cdktn-smoke/anchor-write-file.
#
# Deliberately a stub, not a general-purpose oracle: this task exists to
# validate aws-bench plumbing end-to-end (agent container build, credential
# staging against the anchor scenario, verifier phase, reward-file contract,
# token accounting in result.json — see docs/iac-abstraction-aws-bench-plan.md
# Phase 0 exit criterion), not to score IaC authoring quality. It still reads
# the agent's output and records whether it matched, but the reward is
# unconditionally 1.0 so the anchor/smoke pair always demonstrates a full
# green trial regardless of agent behavior.
#
# Slice B (integrity rails) is expected to replace this stub with the
# preflight/audit-gated verifier described in the build plan once the audit
# gate exists to invalidate (not just fail) a non-conforming run.
set -uo pipefail

EXPECTED="cdktn-bench-anchor-smoke-ok"
AGENT_OUTPUT="/logs/agent/agent-output.txt"

mkdir -p /logs/verifier

if [ -f "$AGENT_OUTPUT" ] && [ "$(cat "$AGENT_OUTPUT")" = "$EXPECTED" ]; then
    echo "agent-output.txt matched expected marker." | tee /logs/verifier/test-stdout.txt
else
    echo "agent-output.txt did not match expected marker (stub reward is unconditional; this is informational only)." \
        | tee /logs/verifier/test-stdout.txt
fi

# Contract: aws-bench's verifier reads a bare float from
# /logs/verifier/reward.txt (harbor/verifier/verifier.py::_parse_reward_text).
echo "1.0" > /logs/verifier/reward.txt
exit 0
