# Generator, shards, CI battery, metrics — reference

Long-form material that would otherwise sit in a file header. Each section is
referenced from the file it describes.

## gen.py output

`generator/gen.py` reads one spec under `specs/` and (re)writes:

    tasks/<scenario_id>/<id>-{awscdk,hcl-raw,terraconstructs,hcl-modules}/
        task.toml, instruction.md, environment/, tests/, solution/ (stub only)
    oracles/<id>/intent.md
    oracles/rego/<id>/policy.rego        (stub only if missing)
    oracles/rego-cfn/<id>/policy.rego    (stub only if missing — the awscdk
                                          arm's CFN-shaped Rego bundle,
                                          specs/SCHEMA.md §4.5)

`<scenario_id>` is the aws-bench shard `generator/shards.py` assigns. The fourth
arm, `hcl-modules` (`DECISIONS.md` Amendment 46), is emitted only for a spec that
enables it — the three pilot composition-trap scenarios. It authors the same
`main.tf` + `provider.tf` pair as `hcl-raw`, its verifier normalises the plan and
additionally DENIES a root `module` call whose source is not a registry source,
and its `environment/` carries the vendored module trees and the registry
sidecar's compose file. `gen.ARMS_PENDING_IMAGE` is now empty; it stays as the
shape a FIFTH arm is introduced through, refusing generation with a sentence
rather than a KeyError halfway through a run, and
`generator/tests/test_hcl_modules_arm.py::test_pending_arms_are_exactly_the_ones_the_generator_cannot_write`
keeps it honest in both directions. `::test_every_arm_has_an_image` stops
the Makefile's "skip an arm whose `environment/` is empty" from hiding a deleted
Dockerfile on a shipped arm.

It also COPIES (never writes) one shared, hand-authored library into a task's
`tests/` when the spec asks for it:

    oracles/rego/lib/hcl_traversal.rego -> tasks/<shard>/<id>-<arm>/tests/

for `oracle.hcl_traversal: true` (specs/SCHEMA.md §4.6), on EVERY TF-shaped
arm: they are graded by the one `oracles/rego/<id>/policy.rego`, so each needs
the library it imports — without it every `hcl.*` call is a compile-time
`rego_type_error` and `opa eval` aborts. The `_hcl` MERGE that library reads is
emitted for `hcl_raw` ONLY — terraconstructs has no `.tf` files, and
hcl_modules' graded resource lives in an installed module body — see
`hcl_input_mode`'s comment in gen.py.

The verifier itself is Python (DECISIONS.md Amendment 44). `tests/test.sh` is
harbor's entry point and `tests/static_tiers.sh` the one every hand-authored
`solution/**/solve.sh` ends with, so both survive as shims that export the two
in-container paths and `exec python3 tests/verify.py` (the second with
`--static-only`). `tests/tiers.py` is the mechanism, byte-identical in every
task; `tests/verify.py` is this task's configuration -- the toolchain commands,
the artifact, the tier-1 engine and policy, and every reason string the live
tiers can record -- and is the file to read to see what one task grades.

These generated files under `tests/` are worth naming because a reader meets
them inside a task dir rather than here:

    tests/tier0.py       THE tier-0 oracle a reviewer opens: this arm's assert
                         table, one `(name, jq filter, op, expected)` tuple per
                         applicable tier-"0" structural_assert with the declared
                         JSONPath in a comment above it. tiers.py runs it as
                         `python3 tier0.py <artifact>` and reads its exit
                         status as the whole tier-0 verdict.
    tests/ops.py         the op table (specs/SCHEMA.md §4.2) and the
                         three-valued outcome, stdlib only, driving `jq` as a
                         subprocess. Byte-identical in every arm's tests/ and in
                         a brownfield task's pre_invoke/, which calls
                         `python3 /pre_invoke/ops.py --one ...` once per live
                         assert -- one owner (`generator/tier0_py.py`'s
                         `OPS_PY`), so the seed proof and tier 0 can never
                         disagree about what `set_eq` means. It replaced the
                         emitted `tests/_assert_lib.sh` bash library in
                         DECISIONS.md Amendment 43, which also made Python `re`
                         the single tier-0 regex flavour.
    tests/tier0.rego     the tier-0 structural asserts compiled to Rego
                         (generator/jsonpath_rego.py). Written only for a spec
                         whose `oracle.tier0_engine` is `rego`, the one engine
                         whose verifier reads it (specs/SCHEMA.md
                         §4.5.1). No spec selects it, so no task dir carries
                         one; `make tier0-parity` compiles its own.
    tests/hcl_merge.py   the `.tf`/`.tf.json` -> JSON pre-parse, `hcl_raw` arm
                         of an `oracle.hcl_traversal` spec only. Invoked as
                         `python3 hcl_merge.py <artifact> <merged>`;
                         a missing file is the fail-closed `LIB_MISSING` status,
                         never a verdict. It was a heredoc inside the emitted
                         shell until DECISIONS.md Amendment 42, and
                         `generator/tests/test_hcl_merge.py` pins both the
                         emitted bytes and the invocation.

### The plan normaliser in `tests/tiers.py`

Terraform puts a module's resources under
`planned_values.root_module.child_modules[*]`, and every `tf_jsonpath` and every
Rego policy addresses `planned_values.root_module.resources`. A module resource
is therefore not graded and found wrong — it is invisible, which reads as a
correct solution on every value assert and as a contradicted `exists`. The
normaliser (`tiers.py::normalise_plan`, DECISIONS.md Amendment 46 — the fourth
Terraform arm composed from registry modules) rewrites the plan into the shape
the asserts already speak, once per run, before any tier:

| side | what it does |
|---|---|
| `planned_values` | hoists every resource from every depth of `child_modules` into `root_module.resources` and drops the emptied `child_modules`. A hoisted resource gains `x_module_path` (the call chain, instance keys kept: `["module.fe[\"a\"]", "module.inner"]`) and, where `resource_changes` supplies one, `x_after_unknown` |
| `resource_changes` | untouched. It is already flat and carries `module_address`, which is what the blast-radius read needs |
| `configuration` | `module_calls` left in place, annotated with `x_unresolved` wherever a reference crosses a module boundary this document cannot follow |

`planned_values` **cannot express unknown** — an unknown attribute is simply
absent from `values`, indistinguishable from unset — so `x_after_unknown`,
joined from `resource_changes` on `(address, deposed)`, is the only way a policy
can tell "the agent did not set it" from "Terraform cannot know it yet".

**The normaliser never guesses a value.** It resolves nothing into a value slot;
where a reference cannot reach a root-frame value it records a reason and stops
(`module_count`, `module_for_each`, `module_repeated_unrepresented` — the
`for_each = toset(...)` shape, which emits no `for_each_expression` at all —
`module_output`, `module_input_default`, `module_input_repeated`,
`module_input_chain`, `module_input_opaque`, `iteration`, `local_symbol`,
`context_symbol`, `expression_not_represented`). That list is
`docs/design/tf-modules-arm.md` §1 and `docs/design/plan-normaliser-survey.md`
§5, and it is normative: resolving a reference INTO the slot is the prior art's
shape mistake, and it destroys the held/contradicted/unresolvable distinction
the whole three-valued contract rests on.

**The invariant:** a plan with no module in it normalises to itself under
canonical (sorted-key) JSON, so every existing fixture grades identically before
and after. `normalise_plan` asserts it on every run, not only in
`make normaliser-parity` (docs/gates.md#normaliser-parity), and it is why no
`x_` key is ever added to a root-module resource and why `local.`, `count.` and
`each.` on a ROOT resource's own expressions are deliberately not marked —
those are what the existing tiers already own. A module input whose chain leads
back OUT to one of them is a different case and IS marked, because that mark
lands on the module resource, where it is the only signal a policy gets.

It runs on `hcl_raw` and `terraconstructs` only; `tests/verify.py` declares
`normalise_plan: True` there and nothing at all on `awscdk`, which grades a
CloudFormation template where a nested stack is denied by its own rule rather
than normalised. The document is written to `<artifact>.normalised.json` beside
the plan and the raw artifact is left exactly as the toolchain wrote it, because
the falsifiability collector and the live tiers read that one. A normaliser that
produces no document is `ENGINE_ERROR` on tier 1 and the existing
"the proof did not run" outcome on tier 0, with a `plan-normaliser.log` and a
`tier{0,1}-engine-error` marker — never a silent pass, which is why
`ENGINE_ERROR` is in `bad_statuses`. It is listed on **every** arm, including
the ones with no engine that can abort: that list is the equal-strictness
contract between arms (DECISIONS.md Amendment 29 — a catch may not cost the
reward on one arm and not on another), so an arm that later gains such an
engine cannot gain a silent pass with it.

### What a tier-1 verdict prints

A tier-1 FAIL prints the `deny` set that produced it: one `DENY: <message>` line
per entry, in the tier-1 section ahead of the `== summary: ... ==` line, so a
transcript alone says WHICH fact denied the plan rather than only that the
reward was 0.0. Each message is folded onto a single line, because a message
carries the artifact's own resource addresses and an embedded newline would let
one open a line the result gates parse (`PASS [name]`, `== summary: ... ==`,
`<LABEL> FAILED`); those gate patterns are anchored to whole lines for the same
reason. An `opa eval` that exits non-zero is never a FAIL: it is `ENGINE_ERROR`
with opa's stderr in the transcript and a `tier1-engine-error` marker, because a
Rego runtime error is a defect in the oracle, not a wrong answer.

### Live verifier tiers in `tests/verify.py`

Two optional live tiers are declared in `tests/verify.py`, both
GENERATION-conditional: a spec that does not opt in declares the tier as `None`
and nothing can arm one at runtime. They are two configurations of ONE shared
mechanism (`tiers.py::live_tier`), so neither can grow a branch the other lacks:
probe that there is anything to ask about, run the arm's command, classify its
exit code against that tier's own branches, record the verdict, and fold a
non-positive outcome into the reward only under that tier's gating switch.

| tier | spec key | env flags | outcomes | result file |
|---|---|---|---|---|
| idempotence (SCHEMA.md §5.1) | `verifier.idempotence` | `SPEC_IDEMPOTENCE_ENABLED` / `_GATING` | `converged` / `pending_changes` / `not_verifiable` | `/logs/verifier/idempotence-result.json` + `idempotence.log` |
| teardown (SCHEMA.md §5.2) | `verifier.teardown` | `SPEC_TEARDOWN_ENABLED` / `_GATING` | `clean` / `destroy_failed` / `not_verifiable` | `/logs/verifier/teardown-result.json` + `teardown.log` |

ORDER IS FIXED AND LOAD-BEARING: live check, then idempotence, then teardown.
Destroying first would invalidate both tiers above it. On a multi-step spec each
tier rides the FINAL step's `[steps.verifier] env` only.

Both tiers' per-arm commands are generator constants — `IDEMPOTENCE_COMMAND`,
`TEARDOWN_COMMAND` — never spec keys, so no spec can ship a tier without one.
`TEARDOWN_STATE_PROBE` IS `IDEMPOTENCE_STATE_PROBE`: one map, so the two tiers
cannot come to disagree about where an arm keeps its state. On a
`workspace_seed.deploy` spec both tiers also emit the SEED MOVEMENT GUARD from
one function (`build_seed_movement_guard`, SCHEMA.md §2.7.1 finding H): the
state probe cannot fire when the harness wrote the state before the agent's
first token, so each tier requires the state identity to have MOVED before it
calls a plan converged or spends a destroy. Both write their
result file whether gating or not, and both `gating` flags AND-compose
fail-closed into `reward.txt`.

The teardown tier GRADES the agent's destroy; it is not a cleanup mechanism.
The framework's post-trial reset still returns the account to baseline whatever
the tier reports, and a destroy that fails for a transient AWS reason is not
retried (the destroy is a toolchain run, not an `aws` call, so Amendment 35's
retry does not reach inside it).

## Equipping levels (`arm x equipping`)

A spec opts in with `equipping.levels` (specs/SCHEMA.md §1.1) and the generator
emits one task directory per `(arm, level)`: `<spec id>-<arm dirname>` at `bare`,
`<spec id>-<arm dirname>-<level>` above it. `bare` is always emitted and never
listed, so a spec that says nothing produces exactly the bytes it produced
before. The material is corpus-wide under `equipping/`, keyed
`levels/<arm dirname>.<level>.yaml`; a level is emitted only for the arms whose
file exists, and `make gen` prints a WARNING naming every pair it therefore does
not emit, so a ragged grid is stated rather than silent.

What a tuned level adds to a task, and nothing else:

| path | what moves |
|---|---|
| `environment/equipping/skills/<name>/` | the level's skill trees, copied from `equipping/` |
| `environment/equipping/mcp.json` | the same MCP list as a file, so the hash's file glob sees it too |
| `environment/Dockerfile` | one appended `COPY equipping/ /opt/equipping/` (`patch_dockerfile_equipping_copy`), outside `/app/project` |
| `task.toml [environment]` | `skills_dir` plus one `[[environment.mcp_servers]]` table per server — the two channels Harbor reads |

Everything else is the scenario and is byte-identical across levels:
`instruction.md`, `tests/` and `solution/` (the reference solution and the
`solution/broken/` negative fixtures) are mirrored from the bare sibling by
`mirror_bare_task_material`. That copy is not a convenience — `solution/solve.sh`
and the negative fixtures are hand-authored and destructive-safe, so a freshly
created tuned dir would otherwise carry the scaffolded stub that exits 1 and no
negative fixtures at all, and an equipping level would silently change what was
graded. `gates/tuned_equipping.py` re-checks the identity per level.

**Holdout.** A spec assigned `holdout` in `specs/split.yaml` may list no levels:
`generate()` refuses before it writes anything and
`enforce_no_holdout_equipping` refuses again on the generated tree (prereg §7.1,
DECISIONS.md Amendment 10). Tuned equipping is developed on `train` only.

**Row labelling.** The level is not a new result field. It is the existing
`harness` column (`metrics/result_schema.json`), whose enum M2 extends to
`empty` / `tuned` / `tuned-stale`, so `metrics/tokens_to_green.py`'s
`(scenario_form, arm, model, harness)` cell key already carries the equipping
dimension and `tuned` can never pool with `tuned-stale`. The value is derived by
`gates/equipping.py::harness_for_task`, never passed as a flag — see
docs/gates.md "tuned-equipping".

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
4. `cdktn-bench env init --env-name <env> --registry-path local-registry.json -d <dataset> --n-concurrent N --wait-for-quotas`, then `env setup` with the same dataset flags (both need the scenario source; `env init` reuses existing accounts by tag and creates only the new shard's)

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

`make tier0-parity` is deliberately NOT in this battery: the jq driver is the
shipped tier-0 grader, so cross-checking it against the retired bash library or
against the Rego compiler is an on-demand check, run when a grader or the
shared grammar changes (docs/gates.md#tier0-parity).

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
holdout scenario's generated task directory contains skill/MCP/plugin config, or
declares an MCP server or a skills dir in `task.toml [environment]` (the same
equipping-file discovery AND the same Harbor-declaration reader
`gates/equipping.py`'s hash uses — Amendment 47, hash scheme 2). It reads
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
- **`make tier0-parity`** (on demand, not part of `make ci`) runs every
  fixture of the spec for real, so it needs the same toolchain as
  `make falsifiability` and takes the same order of
  time. `OUT=<dir>` keeps the collected artifacts so
  `gates/tier0_parity.py --regrade <dir>` can re-check a grader change
  against them with no toolchain at all.
- **`make normaliser-parity`** (on demand, not part of `make ci`) has the same
  requirements and the same runtime class as `make tier0-parity`: it runs every
  fixture of both Terraform-shaped arms for real, and `OUT=<dir>` /
  `--regrade <dir>` work the same way.
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
    $ python3 tests/ops.py --one probe '.SecurityGroups' exists null /tmp/empty.json
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
