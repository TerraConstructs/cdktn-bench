# Generator, shards, CI battery, metrics — reference

Long-form material that would otherwise sit in a file header. Each section is
referenced from the file it describes.

## gen.py output

`generator/gen.py` reads one spec under `specs/` and (re)writes:

    tasks/<scenario_id>/<id>-{awscdk,hcl-raw,terraconstructs}/
        task.toml, instruction.md, environment/, tests/, solution/ (stub only)
    oracles/<id>/intent.md
    oracles/rego/<id>/policy.rego        (stub only if missing)
    oracles/cfn-guard/<id>/policy.guard  (stub only if missing; awscdk tier-1
                                          engine "cfn_guard" only)
    oracles/rego-cfn/<id>/policy.rego    (stub only if missing; awscdk tier-1
                                          engine "rego" only — CFN-shaped Rego,
                                          specs/SCHEMA.md §4.5)

`<scenario_id>` is the aws-bench shard `generator/shards.py` assigns.

It also COPIES (never writes) one shared, hand-authored library into a task's
`tests/` when the spec asks for it:

    oracles/rego/lib/hcl_traversal.rego -> tasks/<shard>/<id>-<arm>/tests/

for `oracle.hcl_traversal: true` (specs/SCHEMA.md §4.6), on BOTH TF-shaped
arms: they are graded by the one `oracles/rego/<id>/policy.rego`, so both need
the library it imports. The `_hcl` MERGE that library reads is emitted for
`hcl_raw` ONLY — terraconstructs has no `.tf` files — see
`build_static_tiers_sh`'s `hcl_lib`/`hcl_merge` comment.

## Scenario shards

A shard IS an AWS member account. aws-bench binds one scenario to exactly one
account (`aws_bench/scenario/config.py`: `account_tags` holds exactly one
entry) and `_ScenarioAdmissionGate` (`aws_bench/task/queue.py`) serializes
mutating trials per `scenario_id`, holding the lock across the trial AND its
reset. More scenarios is the only way to get more concurrency, more
contamination isolation, or a smaller scenario-hash blast radius.

Shard 0 is named `anchor` and is the pre-existing account: it keeps its
`env init`/`env setup` state, so raising the count never re-provisions it.
Shard k>=1 is `anchor-k`. The assignment rule lives in
`generator/shards.py::shard_for` and in specs/SCHEMA.md §8.3.

`generator/shards.toml` holds the one knob. Raising it is an OWNER action with
AWS consequences, in this order:

1. edit `shard_count`
2. `make shards` — materializes `scenarios/anchor-1..N-1` + the registry
3. `make gen-all` — rewrites every task's `scenario_id` and task path
4. `aws-bench env init --n-concurrent N --wait-for-quotas`, then `env setup`

Steps 1-3 are repo-local; step 4 creates real member accounts and is the only
step this repo cannot perform.

## make ci battery

`ci/run-ci.sh` runs, for every spec under `specs/*.yaml`:

1. `gen-sync` — `make gen SPEC=…` must reproduce, byte-for-byte, the state
   every path that spec's generation touches was in immediately before the run
   (snapshot diff, never a git comparison).
2. `check-paths` — `make check-paths SPEC=…`. PASS/FAIL when the spec has a
   reference fixture authored (`generator/tests/fixtures/<id>/`), SKIP (rc=3,
   non-gating) when none of its arms do.
3. `seed-parity` — `make seed-parity SPEC=…`, BROWNFIELD only
   (specs/SCHEMA.md §2.7). SKIP (rc=3) for a greenfield spec.
4. `tier1-coverage`, `falsifiability`, `grading-proof`.

`specs/_toy/toy-ssm-parameter.yaml` is not a benchmark scenario and runs a
lighter smoke set (gen-sync + check-paths + tier1-coverage + falsifiability).
`check-paths` is in that set because toy is the only spec with a reference
fixture authored, so it is the only place the check runs non-vacuously.

Then, once: `make test-gates` and `make check`.

## tokens-to-green aggregator

`metrics/tokens_to_green.py` implements
`docs/iac-abstraction-aws-bench-plan.md` Phase 2 item 3 /
`iac-abstraction-benchmark-prereg.md` §4 (metrics/censoring) and §7 (analysis)
over a directory of published result rows:

- **(0) scenario-form stratification — the coarsest boundary, applied FIRST.**
  Every row carries a REQUIRED `scenario_form`, derived by
  `gates/emit_result.py::derive_scenario_form` from the task dir. The label is
  composite — a step-shape base (`greenfield`/`multi-step`/
  `pre-configured-account`) plus a `-brownfield` suffix when the workspace is
  seeded — so the two independent dimensions never collapse into one another.
  Rows are split on it before the train/holdout split and before the cell, and
  forms are never pooled: they measure different tasks and, for multi-step, a
  different metric (`DECISIONS.md` Amendment 36, resting on Amendment 26 §4 —
  cumulative across-steps tokens-to-green; Amendment 27 §2 — one scenario's
  single- and multi-step forms are different scenarios; Amendment 28 §6 —
  brownfield is a separate stratum). Output carries `by_scenario_form` plus one
  markdown section per form. A directory holding more than one form sets
  `pooling_refused: true` and reports **no** combined headline (top-level
  `cells`/`headline_cells`/`train_cells`/`split_composition`/`tier_attribution`
  are all `null`). A row with no `scenario_form` aborts the run with exit code 2
  and no output file — no backfill, no default.
- **(a) censored tokens-to-green per cell** (scenario form x arm x model x harness):
  Kaplan-Meier median + IQR over `tokens_total`, right-censored. A non-green
  trial is "event not yet observed by this many tokens", never dropped.
  Censoring is at the ADMINISTRATIVE budget bound; the own-stopping-point
  variant is a diagnostic (`tokens_to_green_km_own_stopping_point`).
- **(b) success-rate-within-budget** per cell with Wilson 95% intervals.
- **(c) iterations-to-green**: order statistics over `n_llm_calls` on
  successful trials. A trial with an absent/unreadable trajectory contributes
  `None` and is counted under `n_iterations_unknown`, never treated as zero.
- **(d) per-catch tier-attribution table** from `tier_evidence` (see
  `gates/emit_result.py::read_tier_evidence` for the tier-0-real /
  tier-1-bundle-only caveat it inherits); the tier-1 bundle row is joined
  against the spec's declared tier-1 `structural_assert` names when resolvable.
- **(e) train/holdout stratification** (prereg §7.1), applied *within* each
  scenario form: `headline_cells` (holdout-only, the pre-registered primary
  result) and `train_cells`, never pooled. Each cell also carries `by_scenario`/`scenario_coverage` so a
  paired-by-scenario analysis needs no re-read of raw rows.
- **(f) `tier1_not_verifiable` accounting** per cell plus a same-shaped
  sensitivity summary with those rows excluded.
- **(g) `benchmark.json` + `benchmark.md`**, tables mirroring aws-bench's own
  `aggregate_detailed` (docs/aws-bench-guide.md §6).

## split.py

`generator/split.py` assigns every non-toy `specs/*.yaml` id to `train` or
`holdout` and writes `specs/split.yaml`.

### Algorithm (`scenario-split-v1`, frozen — `SPLIT_ALGORITHM_VERSION`)

1. Each candidate scenario id scores the first 16 hex chars of
   `sha256(f"{SEED}:{spec_id}")`, read as an integer — a deterministic,
   seed-fixed permutation key. Same id and seed give the same score forever;
   nothing depends on file mtimes, spec content, or iteration order.
2. Ids sort by score ascending. That total order is fixed per id, but an id's
   *rank* shifts when the candidate set changes (a lower-scored id joining in
   front of it).
3. `n_train = round(TRAIN_FRACTION * n)` (round-half-up). The lowest-scored
   `n_train` ids are `train`; the rest are `holdout`.

### Re-split procedure

1. `uv run python generator/split.py --write` recomputes the assignment from
   every non-toy `specs/*.yaml` id on disk and overwrites `specs/split.yaml`.
2. Diff the old and new `assignments` blocks. Adding scenarios can shift the
   60/40 cutoff rank even though no individual score changes, so an id near the
   boundary can flip. With only a handful of scenarios, "60% train" is a moving
   cutoff over a fixed ranking, not a stable per-id assignment.
3. If an id flipped:
   - **train → holdout**: any tuned skill/MCP equipping developed against that
     scenario while it was train is tainted — equipping selected using signal
     from a scenario must not then be run held-out against it. Retire that
     equipping and re-tune once a stable train set is confirmed, or freeze the
     split (stop running `--write`) once real tuning work begins for a phase.
   - **holdout → train**: no integrity problem, but note it in DECISIONS.md so
     anyone reading Amendment 10 for that scenario sees where it moved.
4. Record the before/after assignment table and which ids flipped as a new
   DECISIONS.md amendment. `--write` bumps `generated_at` itself.

### Enforcement

`generator/gen.py::enforce_no_holdout_equipping()` hard-fails `make gen` if a
holdout scenario's generated task directory contains skill/MCP/plugin config
(the same equipping-file discovery `gates/equipping.py`'s hash uses). It reads
`specs/split.yaml`, so a hand-edited split file silently changes what that gate
permits — `generator/tests/test_split.py::test_matches_committed_split_yaml`
is what catches the hand-edit.

## make gen targets

`mk/gen.mk` defines the per-spec generator and gate targets. Host-toolchain
requirements that the target comments reference:

- **`make falsifiability`** and **`make grading-proof`** need the arm
  toolchains (terraform, node/npm, jq) on `PATH`. A spec that sets
  `oracle.hcl_traversal: true` (specs/SCHEMA.md §4.6) additionally needs
  `hcl2json`: the hcl_raw arm's generated `tests/static_tiers.sh` runs it over
  the agent's own `*.tf` before `opa eval`. When it is missing, tier-1 reports
  `TOOL_MISSING` — a hard failure by design, so the gate goes red rather than
  silently grading that scenario on plan JSON alone. The pin and checksum live
  in `arms/hcl-raw/environment/Dockerfile`.
- **`make check-paths`** runs the arm's real toolchain against a hand-authored,
  oracle-correct reference fixture at
  `generator/tests/fixtures/<spec-id>/<arm>/`, so it needs the same toolchain
  plus network the first time `npm ci` populates `node_modules`. A spec with no
  fixtures directory reports `NOT_AUTHORED` (non-gating).
- None of these are wired into `make check` / `test-gates`, for the reason
  recorded in `mk/rails.mk`'s gate-preflight note: they need a host toolchain
  the default battery does not assume.

## Seed live assert falsifiability

`spec_model.SeedLiveAssert` narrows what a `workspace_seed.deploy` live proof
may say, so that the proof can actually be contradicted by an account the seed
never reached. Two independent routes to a free pass are closed, in
`SeedLiveAssert._wellformed`. Neither is a decision procedure: together they do
not prove an accepted assert can fail, they only make the two known vacuous
shapes unexpressible. `min_length=1` and `pins_catch` are counting rules, not
falsifiability rules.

### The op rule

Three of SCHEMA.md §4.2's nine ops compile to a jq filter that is true on zero
resolved nodes — that is, on a completely empty AWS account:

    not_exists   -> `($v | length) == 0`                  -- true on []
    absent_or_eq -> `($v | length) == 0 or ...`           -- true on []
    not_regex    -> `$v | all(...)`; jq's all/1 over []   -- true on []

`set_eq` with an empty `expected` means "the account holds none of these",
which is true on `[]` for the same reason. Every other accepted op requires at
least one resolved node by construction (`exists`: length > 0; `eq`: length ==
1; `in`: flattened length > 0; `contains`/`regex`: length >= 1).

These ops stay legal on a `StructuralAssert`, where "this key is absent from
the template" is a falsifiable fact about an artifact that definitely exists.
They are rejected on every live assert, not only the `pins_catch`-bearing one:
an operator reads the non-pinning entries as part of the same proof, and one
that cannot fail dilutes the verdict — "3 live asserts held" must mean three
facts about the account, not two facts and a tautology.

Each rejection is pinned by an executed test,
`generator/tests/test_seed_deploy.py::test_the_rejected_ops_really_do_pass_on_an_empty_account`,
which runs the rejected shape against an empty-account fixture and shows it
passing, so no rule outlives its justification.

### The path rule

The op rule alone is not enough, because vacuity is reachable through the path.
A `jsonpath` that stops at the CONTAINER instead of descending into it hands
even `exists` one node on an empty account:

    $ echo '{"SecurityGroups":[]}' > /tmp/empty.json
    $ assert_check probe '.SecurityGroups' exists '' /tmp/empty.json
      PASS [probe]                                          # rc=0

`[ .SecurityGroups ]` is `[[]]` — length 1, and `map(select(. != null))` does
not drop an empty array. So a `workspace_seed.deploy` whose entire live proof
passed on a completely empty account was expressible, accepted at load, emitted
and reported as `seed_deployed`.

The rule: the compiled filter must contain at least one `.[]` stage, i.e. the
JSONPath must carry a `[*]` or `[?(...)]` segment and therefore iterate a
collection rather than name it. On an empty collection an iterating filter
resolves to zero nodes, which is what every accepted op needs in order to be
contradictable. Write `$.SecurityGroups[*].GroupName`, not `$.SecurityGroups`.

It is a conservative shape rule and rejects some falsifiable paths as
collateral — notably recursive descent (`$..GroupName`), which compiles to
`.. | objects | .GroupName?` and iterates nothing. A live assert that genuinely
needs one of those should widen the rule deliberately, with its own executed
empty-account proof.
