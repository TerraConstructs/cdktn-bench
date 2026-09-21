#!/usr/bin/env bash
# Generated -- generator/gen.py. Harbor's verifier entry point: it
# executes THIS path, so the entry stays a shell file. The verifier is
# tests/verify.py, which runs every tier this task declares -- the static
# tiers, the live check, and the idempotence and teardown tiers -- and
# owns the reward file. Do not hand-edit; regenerate instead.
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
exec python3 "$DIR/verify.py" "$@"
