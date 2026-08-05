# metrics

The custom `--metric uv-script:` aggregation (build plan Phase 2 / mismatch M3):
censored median + IQR tokens-to-green (Kaplan-Meier over the `MAX_ITERS` /
`MAX_TOKENS` budget cap), paired success-rate-within-budget with Wilson intervals,
iterations-to-green, and the per-catch tier-attribution table (which oracle tier
caught each planted catch, per arm).

Reads per-trial token/cost data already captured by aws-bench in `result.json`
(`TrialData.token_cost_totals`) and joins it to rewards — this script is aggregation
only, not a scoring change. See `docs/aws-bench-guide.md` §6 for the shape of the raw
per-trial data this reads.

Populated in Slice D/E.
