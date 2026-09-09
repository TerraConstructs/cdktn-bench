# Host gates — reference

Detail moved out of module headers under the comment-length rule. Each section
is referenced from the top of the file it describes.

## aws-stub

`gates/aws_stub.py` — a two-route HTTP stub answering only
`sts:GetCallerIdentity` and `states:ValidateStateMachineDefinition`, the only
two operations the host gates need. Anything else is logged and answered with
`400 UnsupportedOperation` rather than silently accepted. If a host gate needs
a third operation, extend the stub (DECISIONS.md Amendment 32: live AWS is the
only trial mode, so no offline/dummy-credential branch may be reintroduced in
the generator or the workspace).

`running_stub()` starts the script as a subprocess once per gate invocation,
waits for its `PORT=<n>` announcement, and yields the environment dict every
toolchain subprocess (`terraform plan`, `cdktn synth`, and the generated
`tests/static_tiers.sh`'s own `aws sts get-caller-identity` preflight) must run
under. The dict is a full copy of the gate's own `os.environ` with every
inherited `AWS_*` variable dropped and the stub's endpoint plus fixed dummy
credentials set.

Consumers: `gates/oracle_falsifiability.py`, `gates/grading_proof.py`,
`generator/check_reference_paths.py`. Each hoists one stub per gate process;
`check_arm` and `_run_solve` accept an `env=` so a standalone call still works
(starting a one-off stub of its own).

## oracle-falsifiability

`gates/oracle_falsifiability.py`.

### Multi-step specs

A spec with `steps:` has one oracle PER STEP under `steps/<name>/tests/`, and
no root `tests/` oracle (specs/SCHEMA.md §2.6 "steps"; DECISIONS.md
Amendment 27, multi-step scenarios). The gate then:

* Runs the task-root `solution/solve.sh` and every
  `solution/broken/<catch>/solve.sh` against the **final** step's oracle. The
  final step's oracle is the full tier suite (`spec_model` enforces that), so
  those rows check exactly what they checked before the decomposition. Every
  declared catch is a fact about the final delivered artifact, which is what
  the root reference solution produces.
* Additionally requires each **non-final** step to have its own
  `steps/<name>/solution/solve.sh` scoring reward 1.0 against that step's own
  subset oracle. Nothing else shows an intermediate step's oracle is
  satisfiable, and a step-01 oracle no correct step-01 solution can pass would
  abort every trial at the `min_reward` gate before step 02's prompt fires --
  silently, because Harbor records a step abort on the `StepResult` and not on
  the trial.

The sandbox `tests/` for a step is the shared root `tests/` merged with that
step's own `tests/`, in that order — the same two source dirs
`harbor/verifier/verifier.py::_resolve_tests` uploads into `/tests`, so a
solve.sh's `bash tests/static_tiers.sh` means the same thing here as in a real
trial.

### Per-tier fixture handling

Which verdict a `solution/broken/<catch>/` fixture must produce depends on the
catch's `predicted_tier_caught` for the arm:

* **"0" / "1"** — reward 0.0, AND `observed_tier()` (parsed from the run's own
  static_tiers.sh stdout) must equal the predicted tier. Reward 0.0 alone only
  proves something caught the violation, never that it was caught at the tier
  the spec records, and the per-catch tier-attribution table depends on that
  tier being right.
* **"live"** — reward is expected to stay 1.0 (that invisibility to the static
  tiers IS the catch; the host gate cannot run a live tier, so it never claims
  tier 0/1 caught the fixture). The falsifying evidence is instead the fixture
  printing `LIVE_ONLY_CONFIRMED_MARKER` after mechanically confirming the
  static-indistinguishability property it claims — a two-plan triggers-hash
  diff showing no change, or two synthesized artifacts that are byte-identical
  once every `{% ... %}` expression body is elided. There is no static tool for
  this tier by definition. See docs/apigw-redeploy-mechanics.md.

Extra `solution/broken/<dir>/` directories that match no declared catch name
are discovered and required to score 0.0 the same way, so widened tier-1
bundles keep coverage for alternate-but-equally-idiomatic shapes that no catch
name names.

### AWS access

Every `solve.sh` runs under `gates/aws_stub.py::running_stub()` — credential
free, not offline. `main()` hoists one stub for the whole gate process.

## grading-proof

`gates/grading_proof.py` — the end-to-end proof that each arm is GRADEABLE: a
correct reference solution scores 1.0 and a negative fixture that genuinely
exercises the arm's grading chain is shown to be discriminated by it. Two kinds
of proof are accepted (see "Live-tier proof" below); at least one enabled arm
must produce one, or the spec fails outright.

Deliberately thin: it reuses `oracle_falsifiability.check_arm` (the same
sandbox-preparation path `make falsifiability` runs) rather than a second,
drifting implementation. Its only job is to pick, per arm, the two rows out of
`check_arm`'s own result list that answer that question.

### Negative-fixture selection

Selection is **per arm** and by what the run actually OBSERVED
(`oracle_falsifiability.observed_tier`), not by `predicted_tier_caught`: the
first `solution/broken/<dir>/` fixture — in the same order `check_arm` walks
them, declared `spec.catches[]` first, then extra non-catch-named directories —
whose run was caught at tier "1" on that arm.

A spec-wide selector cannot work: a scenario whose point is that one arm's
typed surface catches a mistake EARLIER than another's has no catch that is
tier-1 on every arm-group at once. `sfn-jsonata`'s `mode-mixing-jsonpath-
artifacts` (awscdk "0", hcl "1") and `ecs-swappiness`'s
`swappiness-requires-maxswap` (awscdk "0", hcl "1", terraconstructs override
"0") are both that shape, and a spec-wide selector made `make grading-proof`
exit 1 unconditionally for both.

Per-arm observed selection also finds a scenario's hand-authored escape-hatch
fixture (`…-raw-constructor-escape-hatch`, `…-cfn-override`, both awscdk-only)
without this script knowing either name in advance.

`--catch` / `CATCH=` overrides the auto-selection with one explicit fixture
name, applied to every enabled arm; a named fixture missing on an arm is a hard
FAIL for that arm, because an explicit request names one specific thing to
prove.

### Live-tier proof

A scenario whose discriminating fact only exists at runtime owns no tier-1
fixture and never will: where both the right and the wrong shape produce the
same artifact graph, a cross-resource tier-1 rule is vacuous
(`lambda-alias-tracks-unpublished-latest` on awscdk — both shapes reference an
`AWS::Lambda::Version` through `Fn::GetAtt`, and only the CDK-generated logical
id differs, which no `structural_assert` may pin). Such a spec is still graded,
at the tier it says decides, so `live_tier_proof()` accepts that instead —
DECISIONS.md Amendment 39, "grading-proof accepts a live-tier proof of
gradeability".

An arm with no tier-1 fixture offers a live-tier proof when ALL of the
following hold, each read off the run rather than assumed:

* the spec's `verifier.live_check` is `enabled`, `gating` AND `hand_authored`
  (`specs/SCHEMA.md` §5) — a non-gating live check costs a trial no reward, so
  it proves nothing about grading;
* a catch applying to this arm declares `predicted_tier_caught: "live"` here;
* that fixture's host-side run produced a graded artifact (the `tier0_pass=`
  summary is present in its stdout) and scored **1.0** — every static tier,
  tier 0 and where present tier 1, passed it;
* `observed_tier()` names no static tier, so the live tier is the one left to
  decide;
* the run printed `LIVE_ONLY_CONFIRMED_MARKER`, the same mechanically-earned
  evidence the falsifiability gate requires of a live catch.

Fail-closed on every branch, and the tier-1 proof is still tried first per arm,
so a spec that has one is unaffected. A live-predicted fixture that a static
tier DOES catch is a tier-attribution failure in `make falsifiability` exactly
as before, and reaches neither selector here. The run's final line names which
proof satisfied each arm.

## emit-result

`gates/emit_result.py` — Gate 3 of the three-gate integrity pattern: wrap a
trial with a validity class and refuse to emit a score row for an invalid one
(docs/lex00-bench-diff.md).

### Validity classes

* `valid` — the audit gate (`gates/audit.py`) found toolchain evidence and no
  infra-failure signal was detected.
* `invalid-bypass` — the trial completed but never invoked the arm's toolchain.
  Not a scored failure of the arm; the trial never really tested it. Evidence
  is a synth, plan, diff or deploy of the arm's own tool (`tsc`, `cdk`,
  `terraform`, `cdktn`) or one of the arm's package.json scripts (`npm run
  build`, `npm run synth`); the table is `ARM_TOKEN_PATTERNS` in
  `gates/audit.py`.
* `invalid-infra` — an infrastructure failure (OOM, Docker daemon unreachable,
  missing/invalid model-auth env var) was found in the trial's own
  harness-owned logs, OR the audit gate found the toolchain was invoked but
  never actually available to run (`degraded`: exit 127 command-not-found, or
  exit 137 SIGKILL). Takes priority over a bypass verdict — a trial OOM-killed
  before it could run did not "choose" to bypass the toolchain. Per
  DECISIONS.md "Memory floor for tsc-heavy arms", a tsc/cdk-synth OOM is
  infrastructure-invalid, never a scored CDK failure.

`_LOG_CANDIDATES` is deliberately narrowed to harness-owned artifacts:
`trial.log` (Harbor/docker's lifecycle log), `exception.txt` (Harbor's
uncaught-exception dump) and `result.json` (Harbor's structured
`TrialResult`). The agent's own output streams must never be scanned — an
agent, or a task whose instruction or legitimate tool output mentions a phrase
like "out of memory", could otherwise self-void its own trial, and since
`invalid-infra` outranks both other classes that silently drops a genuine
failure from the scored denominator. If agent-authored evidence is ever needed
for infra detection, drive it off structured signals (container exit code,
docker error return codes, harbor exception type), not free-text scanning.

Only `valid` trials get score/reward fields; invalid ones get
`score_emitted: false` and no score fields, so a caller that sums a job's
rewards without checking `validity_class` cannot silently pool them. Every
record carries `equipping_hash` (`gates/equipping.py`) so results can never be
pooled across a different instruction/skill/image equipping.

### Multi-step trial-dir layout

`cdktn_bench.trial.CdktnMultiStepTrial` (Harbor's `harbor/trial/multi_step.py`)
relocates the per-phase output dirs after every step:
`MultiStepTrial._archive_step_outputs` moves `agent/`, `verifier/` and
`artifacts/` into `steps/<name>/`. At the end of a multi-step trial the trial
dir has no top-level `agent/` or `verifier/` at all.

Every reader follows the same shape, which is what keeps a single-step trial
dir byte-identical: look at the top-level path FIRST and return exactly what
the pre-multi-step code returned if it is there; only fall back to
`steps/<name>/...` when it is not.

The three harness-owned logs `classify_infra_failure` scans (`trial.log`,
`exception.txt`, `result.json`) are NOT relocated — they are written once at
trial level. That reader therefore needs no fallback, and must not gain one:
`_LOG_CANDIDATES` is deliberately narrowed to harness-owned artifacts.

Per-step evidence readers search the top-level `verifier/` first, then the step
dirs in REVERSE execution order: under the cdktn default
`multi_step_reward_strategy = "final"` (DECISIONS.md Amendment 26) the
published reward comes from the LAST step, so the evidence must describe the
verification that produced the score. When Harbor's own abort predicate says
the scoring step started and died, the earlier steps are dropped from the
search entirely and the readers return their honest "no evidence" value.

## check-reference-paths

`generator/check_reference_paths.py`.

For every `oracle.structural_assert` a spec declares (tier "0" and tier "1"
alike), resolve its declared path with its declared op/expected against a REAL
synthesized/planned artifact — produced by running the arm's real toolchain
against a hand-authored, oracle-correct reference fixture — rather than against
the spec author's mental model of what the artifact looks like.

Tier-1 entries are never executed by the generated `tests/static_tiers.sh`
(tier 1 is Rego/cfn-guard-graded), so a broken `tf_jsonpath` there is inert
documentation that nothing else would ever catch. `.planned_values...
aws_iam_role_policy...values.policy` resolves to NOTHING at plan time whenever
the policy's Resource references a provider-computed attribute; an `op: in`
against zero resolved nodes is False, so this gate turns that into a real
assert failure. See specs/SCHEMA.md §4.2 on `tf_jsonpath`/`cfn_jsonpath`.

Paths resolve through the SAME mechanism the generated `static_tiers.sh` uses
for tier 0 — `generator/jsonpath_jq.py`'s jq compilation plus
`_assert_lib.sh`'s `assert_check` — not a second, Python-side evaluator.
`oracles/lib/structural.py` uses `jsonpath_ng`, which cannot parse the `||`-OR'd
filter syntax several tier-1 CFN paths use at all.

### Fixtures

`generator/tests/fixtures/<spec-id>/<arm-dirname>/<entry_file>` — one
hand-authored, oracle-CORRECT file per enabled arm, dropped in place of the
already-generated task's own entry_file. Everything else (provider.tf /
bin/app.ts / main.ts bootstrap, `environment/` toolchain, `tests/`) comes from
the real generated task dir, so this exercises the exact path a trial's
verifier does.

`.../bad/<entry_file>` is optional: a fixture that deliberately violates one or
more catches, used for a best-effort cross-check. Any `op != "not_exists"`
failing on it is reported but never required. An `op == "not_exists"` assert
that does NOT resolve a violation on the bad fixture is flagged — a
`not_exists` check passing vacuously on a correct artifact tells you nothing
about whether it would ever catch a real violation.

### Exit codes

Exit 0 iff every declared structural_assert resolves and passes against its
arm's reference fixture, for every arm that has one authored. Exit 3 iff every
enabled arm reports NOT_AUTHORED, i.e. no arm has a fixture yet — a distinct
code from a real pass, because otherwise `ci/run-ci.sh`'s summary table cannot
tell a vacuous run from one that actually resolved every path. Callers that
want NOT_AUTHORED to stay non-gating must treat rc 3 specially, not as a
failure; `ci/run-ci.sh`'s SKIP handling is the reference implementation.

Requires the real arm toolchain (terraform, node/npm, jq) on PATH, and network
the first time `npm ci` populates node_modules for awscdk/terraconstructs
fixtures. Not wired into `make check`/test-gates for that reason (see
mk/rails.mk's gate-preflight note).

### --seed mode: brownfield seed parity

What "the three seeds are equivalent" must and must not mean (specs/SCHEMA.md
§2.7 `workspace_seed`). NOT resource-count or resource-type parity: the whole
thesis of the benchmark is that one L2 construct decomposes into N Terraform
resources, so a census check would fail every honest seed. Equivalence is
defined behaviourally, by declared facts:

1. Every arm's seed synths/plans GREEN with no overlay. A workspace that does
   not is not "existing infrastructure", it is a generation failure.
2. Every `seed_assert` holds on every arm its `applies_to` names, resolved
   through the same jq compiler and `_assert_lib.sh::assert_check` a real
   trial's tier 0 runs.

The residual, human half is `workspace_seed.premise`: a mechanical gate can
prove "these three configurations satisfy the same declared facts", never
"these three describe the same system". That has the same status as
`oracle.intent`, and is reviewed the same way.

AWS access: `main()` starts one `gates/aws_stub.py::running_stub()` per
invocation and threads its env into every toolchain subprocess. The generated
`static_tiers.sh` this drives preflights `aws sts get-caller-identity` on both
Terraform-shaped arms and voids the run without it; the stub answers that
preflight, so the check needs no ambient credentials and can never reach a real
account.
