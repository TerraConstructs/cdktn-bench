# Tier-0.5 (embedded-expression JSONata) — sfn-jsonata (hcl_raw)

This scenario declares `oracle.tier05_jsonata` (specs/sfn-jsonata.yaml).
Generated -- generator/gen.py. Do not hand-edit; regenerate instead.

Tier-0.5 does NOT run inside `tests/static_tiers.sh` and does NOT
affect `/logs/verifier/reward.txt` in v1 -- it is non-gating, the
same as `tests/live_check.py` (SCHEMA.md §5's precedent). See
DECISIONS.md "Tier-0.5 runs host-side, non-gating" for why: no arm
image ships Python/jsonata-python.

Run it AFTER `tests/static_tiers.sh` has produced this arm's
artifact (`plan.json`), from the repo root, in this repo's own
`uv` environment (not inside the arm container):

    uv run python -m oracles.lib.tier05_jsonata \
        /app/project/plan.json specs/sfn-jsonata.yaml

Exit 0 iff every declared case in `oracle.tier05_jsonata.cases`
passed; writes `/logs/verifier/tier05-result.json` if
`/logs/verifier/` exists (observational only, never gating).
