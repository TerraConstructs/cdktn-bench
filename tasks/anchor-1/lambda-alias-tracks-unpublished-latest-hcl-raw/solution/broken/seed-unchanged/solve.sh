#!/usr/bin/env bash
# GENERATED -- generator/gen.py::build_seed_unchanged_solve_sh, from
# specs/lambda-alias-tracks-unpublished-latest.yaml. Do not hand-edit; regenerate instead
# (`make gen SPEC=specs/lambda-alias-tracks-unpublished-latest.yaml`). Unlike every other file under
# solution/, this one IS generator-owned and IS overwritten on every
# run -- see that function's own docstring for why.
#
# THE MANDATORY BROWNFIELD DO-NOTHING NEGATIVE (specs/SCHEMA.md §2.7,
# DECISIONS.md Amendment 28 §5): this scenario's workspace does not
# start empty. It starts from `main.tf` as the
# workspace_seed shipped it -- working, green configuration. This
# fixture changes NOTHING and runs the real oracle, so the reward it
# scores is exactly "what does an agent get for doing nothing?".
#
# Required verdict: reward < 1.0. If it ever scores 1.0, the change
# request this scenario asks for is already satisfied by the seed and
# the scenario measures nothing -- gates/oracle_falsifiability.py fails
# on exactly that.
set -euo pipefail

echo "== seed-unchanged (lambda-alias-tracks-unpublished-latest/hcl_raw): leaving main.tf exactly as the workspace shipped it =="
if [ ! -s "main.tf" ]; then
  echo "MISSING SEED: main.tf is absent or empty -- this fixture" >&2
  echo "asserts the brownfield starting state, so an empty one is a" >&2
  echo "generation bug, not a solution failure." >&2
  exit 1
fi

exec bash tests/static_tiers.sh
