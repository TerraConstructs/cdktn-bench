#!/usr/bin/env bash
# Generated -- generator/gen.py. Verifier entry point: exec the real
# static-tier chain, then (only if the spec ever flips live_check on
# AND the runner sets CDKTN_BENCH_LIVE_CHECK=1) run the informational,
# non-gating live_check.py. Do not hand-edit; regenerate instead.
set -uo pipefail
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

"$DIR/static_tiers.sh"
rc=$?

if [ "${SPEC_LIVE_CHECK_ENABLED:-false}" = "true" ] \
   && [ "${CDKTN_BENCH_LIVE_CHECK:-0}" = "1" ] \
   && [ -f "$DIR/live_check.py" ]; then
  python3 "$DIR/live_check.py" > /logs/verifier/live_check-result.json 2>&1 || true
fi

exit $rc
