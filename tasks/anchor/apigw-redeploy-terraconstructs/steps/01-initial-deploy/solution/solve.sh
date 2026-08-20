#!/usr/bin/env bash
# steps/01-initial-deploy/solution/solve.sh -- HAND-AUTHORED reference
# solution for STEP 01 of the multi-step `apigw-redeploy` scenario
# (DECISIONS.md Amendment 27, docs/prompt-decomposition-audit.md).
# Regenerating this scenario will NOT overwrite it (destructive-safe rule,
# SCHEMA.md §8.2 point 8).
#
# WHY IT IS A WRAPPER, NOT A COPY. Revision 1 of this arm's IaC is defined
# ONCE, in ../../../solution/solve.sh's write_rev1(). That file is the
# whole-scenario reference solution (the FINAL step's reference, and the
# shape every solution/broken/<catch>/ fixture is written against). Copying
# its heredoc here would give this arm two definitions of revision 1 that
# drift apart the first time either is edited -- and a step-01 oracle
# validated against a stale revision 1 proves nothing. Instead that script
# takes STEP=01, which stops after revision 1 and runs whatever
# tests/static_tiers.sh is staged.
#
# WHAT "staged" MEANS. gates/oracle_falsifiability.py builds a sandbox whose
# tests/ is the SHARED root tests/ merged with the tests/ of the step being
# checked -- exactly what Harbor's own verifier uploads into /tests for that
# step (harbor/verifier/verifier.py::_resolve_tests). So when this runs under
# the step-01 row, `bash tests/static_tiers.sh` is step 01's own subset
# oracle, and when the root solve.sh runs under the final-step row it is the
# full tier suite.
#
# OFFLINE (default): write revision 1, synth/plan it, assert its structural
# facts, run step 01's static tiers. No AWS credentials, no network.
# LIVE=1: really deploy revision 1 and poll both routes via step 01's own
# tests/live_check.py --expect ok. Manual proof shape only -- the trial has
# the AGENT deploy (see the audit doc §3) -- and it cleans up after itself.
set -euo pipefail

HERE="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
ROOT_SOLVE="$HERE/../../../solution/solve.sh"

if [ ! -f "$ROOT_SOLVE" ]; then
  echo "steps/01-initial-deploy/solution/solve.sh: cannot find the whole-scenario" >&2
  echo "reference solution at $ROOT_SOLVE -- this wrapper reuses its write_rev1()" >&2
  echo "on purpose (see this file's header); it has no revision-1 definition of" >&2
  echo "its own." >&2
  exit 1
fi

STEP=01 exec bash "$ROOT_SOLVE" "$@"
