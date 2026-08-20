# metrics

The headline-metric aggregation (build plan Phase 2 items 2-3 / prereg §4,
§7): censored median + IQR tokens-to-green (Kaplan-Meier over the
`MAX_ITERS`/`MAX_TOKENS` budget cap), paired success-rate-within-budget with
Wilson 95% intervals, iterations-to-green, and the per-catch tier-attribution
table (which oracle tier caught each planted catch, per arm).

## Verified upstream contract: `--metric uv-script:` cannot do this

Before writing `tokens_to_green.py` the runner's native custom-metric hook
was verified against the pinned upstream sources (`aws-bench` git rev
`6450cb56c4552934a37feff492a6fd4eb84d1108`, `harbor==0.9.0` as installed in
`.venv/lib/python3.14/site-packages/harbor/`) rather than assumed from the
build plan's own framing. The contract is real, but it is **reward-only and
job-scoped** — it structurally cannot compute tokens-to-green:

- **The I/O shape** — `harbor/metrics/uv_script.py:17-47`
  (`UvScript.compute`): writes one line per trial to a temp
  `rewards.jsonl` — either `null` or the trial's raw
  `VerifierResult.rewards` dict (e.g. `{"reward": 1.0}`) — then runs
  `uv run <script_path> -i <rewards.jsonl> -o <metric.json>` and reads back
  whatever JSON object the script writes to `-o`. No tokens, no trial id,
  no scenario/arm/model label, no censoring flag — the wire format is
  *just* the reward.
- **Where that list comes from** — `harbor/job.py:401-406` and
  `harbor/job.py:727-759`: `rewards_list` is built from
  `trial_result.verifier_result.rewards` per trial, bucketed by
  `evals_key` (one `--metric` computation per dataset×agent×model bucket
  within a single job — never across jobs/cells). There is no token/cost
  join anywhere on this path; `TrialResult.compute_token_cost_totals()`
  (docs/aws-bench-guide.md §6) is a completely separate accessor this code
  path never touches.
- **CLI wiring** — `aws_bench/cli/metrics.py:13-21` (`parse_metric`)
  turns `uv-script:script_path=./m.py` into
  `MetricConfig(type=UV_SCRIPT, kwargs={"script_path": "./m.py"})`;
  `aws_bench/cli/jobs.py:163-168` (the `--metric` option, repeatable) and
  `aws_bench/cli/jobs.py:732-733` (`config.metrics = [parse_metric(m) for m
  in metric]`) wire it into the job config, **additive** to whatever
  metrics the dataset itself declares (`aws_bench/job.py:441-460`), never
  replacing them.
- **The template itself confirms the shape** —
  `.venv/lib/python3.14/site-packages/harbor/cli/template-metric/metric.py`:
  the shipped example script's entire body is "unwrap each reward dict's
  one value, average it." That is the full expressive range of what this
  hook is *for*.

**Conclusion, matching build-plan mismatch M3 exactly**: `tokens_to_green.py`
is a **standalone offline aggregator**, not something registered via
`--metric uv-script:`. It is run explicitly after a job (or after
`gates/emit_result.py` has produced published rows from one), reading a
**directory of `metrics/result_schema.json`-conformant rows** — which
already carry `tokens_total`/`reward`/`censored`/`arm`/`model`/`harness`/
`scenario`/`tier_evidence` — rather than the bare reward stream the native
hook is limited to. This is a documented, deliberate divergence from trying
to force the aggregation through `--metric`, not an oversight.

## `metrics/tokens_to_green.py`

```
uv run python metrics/tokens_to_green.py <results-dir> \
    [--out-dir DIR] [--max-iters N] [--max-tokens N]
```

Recursively finds every `*.json`/`*.ndjson`/`*.jsonl` file under
`<results-dir>` (skipping its own prior `benchmark.json`/`metric.json`
output), parses each with the same JSON-object / JSON-array / NDJSON
tolerance `validate_result.py` uses, and schema-validates every row —
a row that fails validation is reported and **excluded**, never silently
pooled. Writes `benchmark.json` + `benchmark.md` to `--out-dir` (default:
`<results-dir>`).

**Train/holdout stratification (prereg §7.1, 2026-08-06 fix):** every
row's REQUIRED `split_group` (`train`/`holdout`/`unclassified`,
`gates/emit_result.py::resolve_split_group`, populated from
`generator/split.py::spec_group`) partitions `build_report`'s output into
three cell lists — `headline_cells` (holdout-split rows only — this is the
**pre-registered primary result**), `train_cells` (equipping-tunable
scenarios, reported separately, never pooled with holdout), and the
pooled `cells` (every row regardless of split, kept for backward
compatibility / reference — explicitly **not** the headline, see
`render_markdown`'s own section ordering). `split_composition` reports raw
row counts per group, including `n_unclassified_rows` (a scenario with no
`specs/split.yaml` entry yet) so those rows are visibly excluded from
both tables rather than silently dropped or guessed into either side.

Per **cell** (`arm` × `model` × `harness`, computed identically whichever
of `cells`/`headline_cells`/`train_cells` it appears in), over that cell's
`valid` rows only (`validity_class != "valid"` rows are counted under
`n_excluded_invalid` and never pooled into a headline number — the same
rule `result_schema.json`'s own `validity_class` field description states):

- **`success_rate`** — `successes / n` with a Wilson 95% confidence
  interval (`wilson_interval()` — the score-interval form, not the naive
  normal approximation, which undercoverages at small n or p near 0/1).
- **`tokens_to_green_km`** (the HEADLINE convention, 2026-08-06
  censoring-semantics fix) — Kaplan-Meier censored median + IQR over
  `tokens_total`. **Event** = `reward >= 1.0`. **Censored** = every other
  valid row, right-censored at the cell's ADMINISTRATIVE budget bound
  (`--max-tokens`, else the max observed `tokens_total` in that cell) —
  **not** at its own stopping point — matching prereg §4's own wording
  precisely: "runs that never reach green WITHIN THE BUDGET CAP are
  right-censored." Censoring at a trial's own stopping point instead
  (this field's pre-fix behavior) lets an arm whose failures quit cheaply
  report an artificially *low* tokens-to-green purely because its
  failures are cheap — independent of its actual success rate — the
  survivorship-style artifact this fix removes by construction (both
  arms' non-green trials now censor at the SAME administrative time
  regardless of when they actually stopped). That old convention is still
  computed and reported per cell as a diagnostic,
  `tokens_to_green_km_own_stopping_point` (with
  `tokens_to_green_km_administrative_bound_used` recording which bound
  was actually applied) — useful for spotting exactly this kind of
  failure-cheapness artifact, never the headline. `median`/`q25`/`q75`
  are `None` ("not estimable", rendered `NE` in `benchmark.md`) when the
  KM curve never drops to the corresponding survival threshold within the
  cell's sample. **`censored_frac`**/**`low_event_count`**
  (`n_events < MIN_EVENTS_FOR_CONFIDENT_MEDIAN` = 5) are reported
  UNCONDITIONALLY on every `km_median_iqr` result, independent of whether
  the median was reached (2026-08-06 fix: a majority-censored cell can
  still report a fully "reached" median when censoring happens *before*
  the events rather than after — `median_reached=False` implies
  majority-censored, but not the other way around — so a caller must not
  infer the censored fraction from `median_reached` alone).
- **`iterations_to_green_km`** (the HEADLINE convention, 2026-08-06 fix
  round 2 — mirrors `tokens_to_green_km` exactly) — the same KM treatment
  over `n_llm_calls` (this repo's proxy for `MAX_ITERS`), with every
  non-green valid row that has a *known* `n_llm_calls` right-censored at
  the cell's ADMINISTRATIVE budget bound (`--max-iters`, else the max
  observed `n_llm_calls` in that cell) — **not** at its own stopping
  point. The previous own-stopping-point-only behavior reproduced the
  identical anti-survivorship artifact `tokens_to_green_km`'s
  censoring-semantics fix removed, just on the iterations axis: two cells
  with identical greens and identical success rate could report medians
  that differ purely because one arm's failures happen to quit cheap
  while the other's hit the cap — **`--max-iters` did not change this**
  (its help text used to say so explicitly; it now does). Passing
  `censored=True`/`False` per row (upstream, via `to_result_row`'s
  budget-driven auto-censoring) is a *separate* concern from this KM
  curve's censoring TIME — the two must not be conflated: `censored`
  says whether a row hit a cap at all, the KM bound says WHEN a non-green
  row is treated as censored regardless of why it stopped. The old
  own-stopping-point convention is still computed and reported per cell
  as a diagnostic, `iterations_to_green_km_own_stopping_point` (with
  `iterations_to_green_km_administrative_bound_used` recording which
  bound was actually applied), same shape as the tokens-axis fields.
  `n_iterations_unknown` (2026-08-06 fix) counts valid rows with no
  `n_llm_calls` at all (an absent/unreadable/malformed trajectory —
  `gates/emit_result.py::extract_n_llm_calls` returns `None`, never a
  fabricated `0`, for those) — such rows are excluded from both KM curves
  entirely rather than silently entering them as an event at time 0.0.
- **`iterations_to_green`** — plain order statistics (mean/median/p25/p75/
  min/max) over `n_llm_calls` on **successful** trials only — the simpler,
  non-censoring-aware secondary metric the prereg names as such (§4).
- **`tokens_total_uncensored`** — plain mean±stddev over every valid row's
  `tokens_total`, uncensored — a descriptive reference stat only (mirrors
  aws-bench's own `aggregate_detailed` mean/median-per-bucket style,
  docs/aws-bench-guide.md §6), explicitly **not** the headline number,
  since it is silently biased toward whichever arm fails cheaply (the
  exact survivorship trap the prereg's censoring discipline exists to
  avoid, §4 "anti-survivorship").
- **`n_tier1_not_verifiable`** / **`sensitivity_excluding_tier1_not_verifiable`**
  (2026-08-06 fix) — count of valid rows where
  `tier1_not_verifiable=true` (a tier-1 check that was never actually
  evaluated for that trial, `result_schema.json`'s own field description),
  plus a same-shaped `summarize_cell` block over the rest of the cell with
  those rows excluded (bounded to one level of recursion — the
  sensitivity block itself carries no further nested sensitivity field),
  so a reader can see whether a headline result survives their removal
  rather than silently pooling them in.
- **`scenario_coverage`** / **`by_scenario`** (2026-08-06 fix, "prereg §7
  analysis outputs not derivable from `benchmark.json`") — raw row counts
  per scenario, plus a full `summarize_cell` block computed over each
  scenario's own subset of the cell's rows. `cell_key()` itself is still
  `(arm, model, harness)` only (scenario identity was previously
  discarded entirely at this layer) — this unblocks prereg §7's primary
  test ("tokens-to-green ... PAIRED BY SCENARIO") and its main-effects
  decomposition without requiring a re-read of raw rows, even though
  `benchmark.md`'s own rendered table still only shows the pooled-per-cell
  numbers.

**Per-catch tier-attribution table** (`build_tier_attribution`) — over
failed (`reward < 1.0`) valid rows' `tier_evidence`:

- Tier-`"0"` rows are **real per-assert evidence**: each declared tier-0
  `structural_assert` independently echoes its own PASS/FAIL
  (`gates/emit_result.py::read_tier_evidence`, parsing
  `verifier/test-stdout.txt`'s `  PASS [name]` / `  FAIL [name]` lines —
  `generator/gen.py`'s `_assert_lib.sh::assert_check()` is the producer).
- Tier-`"1"` rows are a **single bundled verdict** per scenario/arm — the
  oracle itself only ever computes one `opa eval`/`cfn-guard validate`
  result covering every tier-1 catch at once (verified against
  `generator/gen.py`'s tier1 blocks: the individual tier-1 assert names
  are compiled into a bash `#`-comment for human readability, never
  echoed to stdout at runtime), so there is still **no** finer
  per-tier-1-catch breakdown available from the current oracle design.
  2026-08-06 fix: the row's `name` is no longer an unconditionally opaque
  `"(tier-1 bundle)"` placeholder — `build_tier_attribution` now joins it
  against `specs/<scenario>.yaml`'s own declared tier-1
  `structural_assert` names when that spec file resolves (e.g.
  `"(tier-1 bundle: maxswap-present-when-swappiness-tuned)"`), falling
  back to the old opaque name only when it can't (a fixture/synthetic
  scenario id, or a scenario this metrics run has no local `specs/` for)
  — this enumerates the CANDIDATE catches per scenario/arm in
  `benchmark.json` itself rather than only in README prose; it still
  cannot say WHICH of the enumerated asserts fired for a given failure.
- Failed trials with no `tier_evidence` at all are reported under
  `no_evidence_failed_trials`, never silently dropped.

### Kaplan-Meier median monotonicity (why "adding a censored row never
decreases the median" holds)

Inserting one additional censored observation at any time `t_c` can only
**add** to the risk set for every event-time `<= t_c` (an observation
censored at `t_c` is still "at risk" through `t_c` under the standard tie
convention `kaplan_meier()` implements) and never removes anyone from any
risk set. So every hazard `d_i/n_i` at `t_i <= t_c` can only shrink, hence
`S_new(t) >= S_old(t)` pointwise for **all** `t` (unaffected for
`t > t_c`, since the new observation has already left every later risk
set). Since `median = inf{t : S(t) <= 0.5}` and `S_new >= S_old`
pointwise, `{t : S_new(t) <= 0.5} ⊆ {t : S_old(t) <= 0.5}`, so the new
median (the infimum of a subset) is `>=` the old one — including the case
where the set becomes empty (median becomes "not estimable"), which is the
*correct* direction under the convention that "not estimable" means "at
least as large as every finite candidate," not smaller. `metrics/
test_tokens_to_green.py::TestKmMedianMonotonicityProperty` exercises this
with 300 randomized insertions plus one worked example of the
defined→not-estimable edge case.

### Wilson interval spot-check

`metrics/test_tokens_to_green.py::TestWilsonInterval` checks the formula
two independent ways rather than trusting one memorized "published" digit
string: (1) the **closed form at n=1** (`lo=0`, `hi=z²/(1+z²)`, derived
separately from the production formula — for `k=0` this evaluates to
≈0.7935, the commonly-cited Wikipedia worked example for the Wilson score
interval at n=1), and (2) the interval's own **complementary symmetry**
invariant, `CI_hi(k, n) == 1 - CI_lo(n-k, n)`, checked over 200 randomized
`(k, n)` pairs — true of the Wilson interval by construction (swapping
success/failure mirrors the interval around 0.5), so any implementation
bug that broke the formula's shape would almost certainly break this
symmetry too.

## `gates/emit_result.py` additions (this task)

Two additive extensions, driven by what `generator/gen.py`'s generated
`tests/static_tiers.sh` actually writes to `/logs/verifier/` (checked
directly, not assumed) — neither changes any existing required field or
existing caller's behavior; `metrics/emit_fixture_rows.py` and every prior
test still pass unmodified:

- **`read_tier_evidence(trial_dir)`** — parses
  `<trial_dir>/verifier/test-stdout.txt` for the per-assert
  `PASS [name]`/`FAIL [name]` lines and the `tier1_status=...` summary line
  `build_static_tiers_sh`'s generated script always produces. Returns
  `None` when the file doesn't exist (verifier never ran a
  static_tiers.sh-shaped `test.sh`) — never an empty dict, so a caller can
  tell "no evidence at all" apart from "evidence exists but a toolchain
  step failed before tier-0/1 ever ran" (`{"tier0": {}, "tier1_status":
  None}`). Always attached to `build_result_record()`'s output as
  `tier_evidence` (present/absent regardless of `validity_class`, same
  reasoning as the existing `audit`/`infra` fields), and carried into
  `to_result_row()`'s output as the new **optional**
  `result_schema.json` property `tier_evidence` (only when not `None` —
  existing rows without it stay schema-valid, since it isn't required).
- **`extract_n_llm_calls(trial_dir)`** — counts LLM calls from
  `<trial_dir>/agent/trajectory.json`, mirroring
  `aws_bench/metrics/run_data.py::_llm_usage_from_trajectory`'s own
  accumulation exactly (verified against the pinned `aws-bench` clone):
  for each `source == "agent"` step, add `step.llm_call_count` when it's an
  int, else add 1 iff `step.metrics` is present, else 0. Needed because
  `result.json`'s `agent_result` never carries this field itself (verified:
  only `cost_usd`/`n_input_tokens`/`n_output_tokens`/`n_cache_tokens` do)
  — only the trajectory does. Populates the already-declared-but-previously
  -unproduced `n_llm_calls` optional field on the row.
- **`to_result_row(..., censored=None, max_iters=None, max_tokens=None)`**
  — `censored`'s default changed from a hardcoded `False` to `None`
  ("auto-detect"), which is backward compatible: with neither
  `max_iters` nor `max_tokens` passed (every existing call site),
  auto-detection is a no-op and `censored` still comes out `False`.
  When budget params ARE passed, a `reward < 1.0` row with
  `tokens_total >= max_tokens` or `n_llm_calls >= max_iters` is
  auto-censored — mirroring `scripts/run-bench.sh`'s own `budget.json`
  ("MAX_ITERS = 8 feedback cycles or MAX_TOKENS per trajectory, whichever
  first"). An explicit `censored=True`/`False` always wins over
  auto-detection.

## Budget enforcement (`scripts/run-bench.sh`)

`MAX_ITERS` (default 100 — the prereg's 8, raised by DECISIONS.md Amendment
22) and `MAX_TOKENS` (default unset — pilot-set, per
the build plan) are documented in full in `scripts/run-bench.sh`'s own
header; summary:

- `MAX_ITERS` maps to Claude Code's real `--max-turns` CLI flag via
  `--ak max_turns=N` (verified against
  `.venv/lib/python3.14/site-packages/harbor/agents/installed/claude_code.py`
  `CLI_FLAGS`: `CliFlag("max_turns", cli="--max-turns", type="int",
  env_fallback="CLAUDE_CODE_MAX_TURNS")` — this is the exact knob
  docs/aws-bench-guide.md §5 already named). Injected before any
  pass-through `--` args so an explicit user-supplied `--ak max_turns=...`
  still wins (`harbor/cli/utils.py::parse_kwargs` overwrites on duplicate
  key, later argv entries win).
- `MAX_TOKENS` has **no native harness flag** — the installed Claude Code
  agent's `CLI_FLAGS` only have `max_budget_usd` (a cost, not a token,
  cap) and `max_thinking_tokens` (a per-response reasoning cap, not a
  whole-trajectory budget). It is therefore a **post-hoc grading
  threshold**, recorded to `<jobs-dir>/budget.json` for
  `gates/emit_result.py`'s (and `tokens_to_green.py`'s) own use, not a
  pre-hoc kill-switch.

## Landed in Slice B (unchanged by this task)

- `result_schema.json` — JSON Schema for one published result row.
  `equipping_hash`, `oracle_version`, `arm`, `model`, `harness`,
  `validity_class`, `tokens_input`, `tokens_output`, `tokens_total`,
  `reward`, `censored`, and `tier1_not_verifiable` are schema-**required**,
  not optional-by-convention — the direct fix for the chant-bench gap
  (`docs/chant-bench-diff.md` §5: `run.substrate` was specified in that
  project's own plan and silently absent from all 122 published result
  JSONs). `validity_class`'s enum (`valid` / `invalid-bypass` /
  `invalid-infra`) matches `gates/emit_result.py`'s
  `VALID`/`INVALID_BYPASS`/`INVALID_INFRA` constants exactly, so a
  gate-emitted verdict always carries over into a published row unchanged.
  `equipping_hash` is `gates/equipping.py`'s `compute_equipping_hash()`
  output.
- `validate_result.py` — validates a result row (or a JSON array / NDJSON
  file of rows) against `result_schema.json`; wired into `make check` via
  `mk/rails.mk` (`check-result-schema`, checked against
  `examples/valid-result.json`).
- `examples/valid-result.json` — a hand-authored example row, real
  `equipping_hash` computed against `tasks/anchor/smoke`.
- `test_validate_result.py` — schema round-trip tests (required-field
  coverage, enum rejection, the `tokens_total >= tokens_input +
  tokens_output` semantic check, CLI exit codes for
  JSON-object/array/NDJSON inputs).
- `emit_fixture_rows.py` — proves the schema has a real producer: runs
  Gates 2+3 (`gates.emit_result.build_result_record` +
  `to_result_row`) against the `gates/tests/fixtures/` trial dirs and
  validates the resulting rows.

## Tests

- `metrics/test_tokens_to_green.py` — KM median/IQR hand-computed against a
  worked 5-row example; a majority-censored cell asserted `median: None`;
  Wilson closed-form + symmetry spot-checks; tier-attribution table
  correctness (tier-0 real, tier-1 bundled, `TOOL_MISSING`/`SKIPPED_STUB`
  counted as failures, `PASS`/`SKIPPED_NO_ASSERTS` never attributed,
  missing-evidence trials reported not dropped); the KM
  never-decreases-under-added-censoring property test (300 randomized
  insertions); row loading/validation (rejects invalid rows without
  pooling them, ignores its own prior output, recurses, tolerates
  JSON-object/array/NDJSON); end-to-end CLI (`benchmark.json`/`.md`
  written, non-zero exit on any rejected row).
- `gates/tests/test_emit_result.py` (`TestTierEvidence`, `TestNLlmCalls`,
  `TestToResultRowAutoCensoring`) — `read_tier_evidence`/
  `extract_n_llm_calls` parsing correctness (absent file, realistic
  output, early-toolchain-failure partial output, every `tier1_status`
  value, wiring into a schema-valid row, evidence attached even on an
  invalid trial), and `to_result_row`'s budget-driven auto-censoring
  (backward-compat no-op with no budget params, explicit `censored`
  always wins, success is never censored regardless of budget, tokens/
  iters-over-budget censoring, missing `n_llm_calls` doesn't crash the
  `max_iters` check).
- `test/test_run_bench_wrapper.py` (`TestBudgetWiring`) — `--dry-run`-only
  coverage of `MAX_ITERS`/`MAX_TOKENS` defaulting, env-var/flag precedence,
  the injected `--ak max_turns=N` (and that a user's own later `--ak`
  still overrides it), `--max-iters 0` skipping injection, and
  `--ae CDKTN_BENCH_MAX_TOKENS=N` only appearing when `MAX_TOKENS` is set.
