#!/usr/bin/env bash
# Generated -- generator/gen.py, from ../../../../specs/acm-dns-validation-record-wiring.yaml.
# Static tier-0/1 entry point for the terraconstructs arm: tests/verify.py without
# the live check and the idempotence and teardown tiers. Every
# hand-authored solution/**/solve.sh ends by running this file, and the
# two host-side gates run it to grade a fixture, so the in-container
# paths are exported HERE -- patching this one file repoints the whole
# chain. Do not hand-edit; regenerate instead (`make gen SPEC=specs/acm-dns-validation-record-wiring.yaml`).
#
# Reward contract: a bare float in $CDKTN_VERIFIER_LOGS_DIR/reward.txt
# (harbor/verifier/verifier.py::_parse_reward_text).
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
export CDKTN_VERIFIER_LOGS_DIR="/logs/verifier"
export CDKTN_VERIFIER_PROJECT_DIR="/app/project"
export CDKTN_VERIFIER_SEED_RECEIPT="/logs/seed-deploy-receipt.json"
if ! command -v python3 >/dev/null 2>&1; then
  mkdir -p "$CDKTN_VERIFIER_LOGS_DIR"
  {
    echo "python3 and jq are both required to evaluate the tier-0"
    echo "structural asserts (tests/tier0.py drives tests/ops.py, which"
    echo "invokes jq); at least one is missing from this image, so no"
    echo "assert was evaluated -- a run-invalidating condition, not a"
    echo "silent pass."
  } | tee "$CDKTN_VERIFIER_LOGS_DIR/tier0-unavailable"
  echo "0.0" > "$CDKTN_VERIFIER_LOGS_DIR/reward.txt"
  exit 0
fi
exec python3 "$DIR/verify.py" --static-only "$@"
