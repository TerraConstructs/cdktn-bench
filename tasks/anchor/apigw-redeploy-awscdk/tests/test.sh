#!/usr/bin/env bash
# Generated -- generator/gen.py. Verifier entry point: exec the real
# static-tier chain, then (only if this scenario's task.toml sets
# SPEC_LIVE_CHECK_ENABLED=true, i.e. verifier.live_check.enabled is
# true for this spec) run the informational, non-gating
# live_check.py. Do not hand-edit; regenerate instead.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$DIR/static_tiers.sh"
rc=$?

if [ "${SPEC_LIVE_CHECK_ENABLED:-false}" = "true" ] \
   && [ -f "$DIR/live_check.py" ]; then
  python3 "$DIR/live_check.py" > /logs/verifier/live_check-result.json 2>&1 || true
fi

exit $rc
