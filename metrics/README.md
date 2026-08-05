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

The aggregation script itself is populated in Slice D/E. Landed in **Slice B**:

- `result_schema.json` — JSON Schema for one published result row. `equipping_hash`,
  `oracle_version`, `arm`, `model`, `harness`, `validity_class`, `tokens_input`,
  `tokens_output`, `tokens_total`, `reward`, and `censored` are schema-**required**,
  not optional-by-convention — the direct fix for the chant-bench gap
  (`docs/chant-bench-diff.md` §5: `run.substrate` was specified in that project's own
  plan and silently absent from all 122 published result JSONs). `validity_class`'s
  enum (`valid` / `invalid-bypass` / `invalid-infra`) matches
  `gates/emit_result.py`'s `VALID`/`INVALID_BYPASS`/`INVALID_INFRA` constants exactly,
  so a gate-emitted verdict always carries over into a published row unchanged.
  `equipping_hash` is `gates/equipping.py`'s `compute_equipping_hash()` output.
  Note `gates/emit_result.py`'s own per-trial JSON record (audit evidence, infra
  classification, raw `n_input_tokens`/`n_output_tokens`/`cost_usd`) is a *different*,
  richer diagnostic artifact one layer below this schema — the Slice D/E aggregation
  step is what maps a gate record into a schema-conformant published row (adding
  `oracle_version`/`model`/`harness`/`schema_version`, flattening token field names,
  and deciding `censored`).
- `validate_result.py` — validates a result row (or a JSON array / NDJSON file of
  rows) against `result_schema.json`; wired into `make check` via `mk/rails.mk`
  (`check-result-schema`, checked against `examples/valid-result.json`).
- `examples/valid-result.json` — a hand-authored example row, real `equipping_hash`
  computed against `tasks/anchor/smoke`.
- `test_validate_result.py` — schema round-trip tests (required-field coverage, enum
  rejection, the `tokens_total >= tokens_input + tokens_output` semantic check, CLI
  exit codes for JSON-object/array/NDJSON inputs).
