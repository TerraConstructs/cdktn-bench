# Host gates — reference

Detail moved out of module headers under the comment-length rule. Each section
is referenced from the top of the file it describes.

## aws-stub

`gates/aws_stub.py` — a three-route HTTP stub answering only
`sts:GetCallerIdentity`, `iam:GetRole` and
`states:ValidateStateMachineDefinition`, the only three operations the host
gates need. Anything else is logged and answered with `400
UnsupportedOperation` rather than silently accepted. If a host gate needs a
fourth operation, extend the stub (DECISIONS.md Amendment 32: live AWS is the
only trial mode, so no offline/dummy-credential branch may be reintroduced in
the generator or the workspace).

The identity it answers is an **assumed role** —
`arn:aws:sts::<account>:assumed-role/cdktn-bench-gate/gate-session` — because
that is the credential shape every live trial runs under. An IAM-user ARN here
would let a scenario whose planned artifact embeds the caller ARN pass offline
on a shape no real trial can produce.

`iam:GetRole` follows from that: terraform-provider-aws
`data "aws_iam_session_context"` parses the session ARN and then calls GetRole
for the role name it extracted, failing the entire plan on any error. The stub
answers a full `GetRoleResponse` for `cdktn-bench-gate` (the issuer of its own
identity) and the IAM `NoSuchEntity` 404 for every other name — never an
invented role, which would let a plan resolve an issuer the account does not
hold.

`running_stub()` starts the script as a subprocess once per gate invocation,
waits for its `PORT=<n>` announcement, and yields the environment dict every
toolchain subprocess (`terraform plan`, `cdktn synth`, and the generated
the generated verifier's own `aws sts get-caller-identity` preflight) must run
under. The dict is a full copy of the gate's own `os.environ` with every
inherited `AWS_*` variable dropped and the stub's endpoint plus fixed dummy
credentials set.

Consumers: `gates/oracle_falsifiability.py`, `gates/grading_proof.py`,
`generator/check_reference_paths.py`. Each hoists one stub per gate process;
`check_arm` and `_run_solve` accept an `env=` so a standalone call still works
(starting a one-off stub of its own).

## tf-registry

`gates/tf_registry.py` + `arms/hcl-modules/environment/tf-registry/responder.py`
— the offline Terraform **module** registry the `hcl_modules` arm resolves
against. Providers have a `filesystem_mirror`; modules have no mirror mechanism
at all, so vendoring plus a responder is the whole option space
(`docs/design/tf-module-registry-loopback.md` §4).

`responder.py` serves one vendored tree (`--root`, the directory holding
`manifest.json`) on one ephemeral loopback port and answers six things:

| request | response |
| --- | --- |
| `GET /.well-known/terraform.json` | `{"modules.v1": "/v1/modules/"}` — the compose healthcheck's probe; Terraform never asks, because the `host` override skips discovery |
| `GET /v1/modules/<ns>/<name>/aws/versions` | every manifest version of that module, newest last |
| `GET /v1/modules/<ns>/<name>/aws/<version>/download` | `204` + `X-Terraform-Get` at an absolute `/tarballs/<name>-<version>.tar.gz` URL |
| `GET /tarballs/<name>-<version>.tar.gz` | the module directory's CONTENTS, built on first request and cached |
| `GET /v1/modules/search?q=` | manifest-backed name/description match, every module answered alike |
| `POST /mcp` | MCP streamable-http `initialize` / `tools/list` / `tools/call` |

The manifest is the whole world. A namespace other than
`terraform-aws-modules`, an unvendored module, or an unvendored version is a
404 whose body names the allowlist or the newest version that does exist —
never a passthrough, because a responder that could answer an unlisted version
from upstream would break the arm's offline guarantee silently. The file opens
no outbound connection at all, and
`gates/tests/test_tf_registry.py::test_responder_opens_no_outbound_connection`
runs it under a `socket.connect` audit hook to prove it.

The tarball strips the vendored directory name: go-getter extracts the archive
**as** the module root, so a retained top directory puts every `.tf` file one
level below where Terraform looks.

Nothing the responder serves says which modules are decoys, and neither does the
manifest it reads: that flag is the module-selection answer, and it lives only in
`scripts/vendor_modules.pins.json` on the host
(`docs/hcl-modules-vendoring.md`).

`POST /mcp` is the phase-4 skeleton of the bench-owned index tool
(`docs/design/registry-index-tool.md` design B): the nine tool names and input
schemas of `terraform-mcp-server`'s `registry` toolset, with every call
answering a **successful** result reading `<tool>: not available in this
environment`. A successful decline rather than an error is deliberate — an
error reads to an agent as an outage worth retrying, while the text states the
bound it is working inside. M2 replaces the bodies, not the hosting.

`running_registry(root)` is the host-gate lifecycle, shaped like
`running_stub()`: it starts the responder once, waits for its `PORT=<n>`
announcement, writes a temporary `TF_CLI_CONFIG_FILE`, and yields the
environment every toolchain subprocess must use. That config **concatenates**
whatever config the caller's environment already names (the arm's
`provider_installation { filesystem_mirror … }`) with a
`host "registry.terraform.io" { services = { "modules.v1" = … } }` override.
Concatenation, not replacement: the blocks are independent, and dropping the
provider half to gain the module half would send provider installation back to
the network. The override is also what makes plain HTTP legal — it skips
service discovery entirely, and without it Terraform always discovers over
HTTPS.

A `host` block **replaces the whole service map**, so the override restates
`providers.v1` at its real URL as well: overriding `modules.v1` alone makes
Terraform report that `registry.terraform.io` "does not offer a Terraform
provider registry" and fail `init` at the provider stage. Inside the arm image
the `filesystem_mirror` answers providers and that line is never reached; on
the host, which has no mirror, it is what keeps provider installation working
exactly as it does for the other three Terraform-shaped arms.

The yielded environment additionally carries `CDKTN_BENCH_TF_REGISTRY_URL` and
`CDKTN_BENCH_TF_REGISTRY_LOG`. The log holds one `ACCESS <method> <path>
<status>` line per request and is the **only** evidence that a module came from
the responder rather than from `registry.terraform.io`: the end-to-end test
asserts the `versions`, `download` and tarball lines appear after a real
`terraform init`, and that no discovery request does. A dead-proxy environment
variable would prove only that outbound failed, not where the bytes came from.

Consumer: `gates/oracle_falsifiability.py::arm_env`, which is identity for every
arm but `hcl_modules` — three green arms must not come to depend on a fourth
arm's subprocess. It lives there rather than in `gates/artifact_collector.py`,
which imports it: `falsifiability`, `grading-proof` and `normaliser-parity` all
run this arm's fixtures, and one definition is what keeps them running in the
same environment. Each wraps ONE responder per arm inside its one AWS stub per
process.

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
  verifier stdout) must equal the predicted tier. Reward 0.0 alone only
  proves something caught the violation, never that it was caught at the tier
  the spec records, and the per-catch tier-attribution table depends on that
  tier being right.
* **"live" / "teardown"** — reward is expected to stay 1.0 (that invisibility
  to the static tiers IS the catch; the host gate can run neither tier, so it
  never claims tier 0/1 caught the fixture). The falsifying evidence is instead
  the fixture printing `LIVE_ONLY_CONFIRMED_MARKER` after mechanically
  confirming the static-indistinguishability property it claims — a two-plan
  triggers-hash diff showing no change, two synthesized artifacts that are
  byte-identical once every `{% ... %}` expression body is elided, or two plans
  differing only in the one attribute no `structural_assert` of the spec reads.
  There is no static tool for either tier by definition. Both share one verdict
  in `oracle_falsifiability.apply_live_family_verdict`. See
  docs/apigw-redeploy-mechanics.md and `specs/SCHEMA.md` §5.2.

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
exercises the arm's grading chain is shown to be discriminated by it. Three
kinds of proof are accepted (see "Live-tier proof" and "Teardown-tier proof"
below); at least one enabled arm must produce one, or the spec fails outright.

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

### Teardown-tier proof

The same argument one tier further out (`specs/SCHEMA.md` §5.2, DECISIONS.md
Amendment 41): a configuration that applies green, passes the live check and
then fails its own `destroy` is invisible to every static tier by construction,
so the arm owns no tier-1 fixture and the generator-injected destroy is what
decides it. `teardown_tier_proof()` accepts that, on the conditions
`live_tier_proof()` uses with one substitution — `verifier.teardown` must be
`enabled` AND `gating` (an observational teardown writes its verdict to
`/logs/verifier/teardown-result.json` and leaves the reward alone, so it proves
nothing about grading), and the catch must declare `predicted_tier_caught:
"teardown"` on this arm. `teardown.enabled` already requires an enabled,
hand-authored live check, which is what makes a destroy exist to grade.

Tried after the tier-1 selector and after the live-tier one, so an arm holding
either of those still produces it. `ecr-repo-destroy-force-delete` is the first
user: its Terraform-shaped arms are proven this way, while `awscdk` — where the
CDK default removal policy `Retain` makes a silent no-op destroy report clean —
keeps a static assert and a tier-1 fixture.

## audit

`gates/audit.py` — Gate 2: did the trial actually invoke its arm's toolchain,
or did it grep/cat its way to a green reward? Evidence is positional
(`ARM_TOKEN_PATTERNS`, argv[0] after wrapper-peeling); `gates/README.md` has
the matching rules. This section covers only where the tool calls are read
from.

### Transcript fallback and its provenance field

Normally the gate reads Harbor's ATIF `agent/trajectory.json`. Harbor's Claude
Code converter, however, can reject its own output — it pairs a tool result to
its call in timestamp order and renumbers nothing, so a result whose recorded
timestamp precedes its own call is dropped and the surviving steps carry a
step-id gap (`steps[16].step_id: expected 17, got 18`, logged in `trial.log` as
"Failed to convert Claude Code events to trajectory"; see
`docs/upstream/harbor-trajectory-step-id-gap.md`). The trial then has a
complete `agent/claude-code.txt` stream transcript and no trajectory, which
used to void the row as `invalid-infra` / `audit-unavailable`.

So when a step has no trajectory but does have the transcript beside it, the
gate builds the step list from the transcript instead
(`steps_from_claude_code_stream`), pairing results to calls in TRANSCRIPT order
— which is what cannot produce the gap. Resolution is per step
(`resolve_audit_sources`), so a multi-step trial that lost one step's
trajectory is still audited over all of them, and the trajectory always wins
where both files exist. A trial with NEITHER file stays `audit-unavailable`.

The reconstruction is faithful, not lenient. It reproduces Harbor's own
observation text (`_format_tool_result`: the block content, then
`[stdout]`/`[stderr]`/`[exit_code]`/`[metadata]` chunks) and hands the audit
the same raw `tool_use_result` under `extra.metadata`, so the structured
exit-code channel and the anchored free-text heuristics both classify a call
exactly as they would from a trajectory — including the degraded-arm verdict
that separates `invalid-infra` from `invalid-bypass`. Where Claude Code emits
no `exitCode` at all (the version that produced the affected rows does not),
BOTH paths fall back to the free-text heuristics, and a call neither channel
can classify stays `unknown`, which callers treat as non-degrading: absence of
an exit code is not positive evidence that the toolchain was unavailable.

Provenance is recorded rather than inferred. An audit record, the
`build_result_record` record and the published row each gain
`audit_source: "claude-code-stream"` when any step was audited this way; the
key is ABSENT (equivalently `"trajectory"`) otherwise, so records for trials
that had a trajectory are unchanged. `tokens_source` marks the same failure on
the token side — `_tokens_from_claude_code_stream` recovers the totals from the
transcript's terminal `result` event because Harbor fills `agent_result` only
when its conversion succeeded — and `n_llm_calls` comes from that event's own
`num_turns`. Both fields are optional in `metrics/result_schema.json`
(no required field changed, so `schema_version` stays 1.1). Pinned by
`gates/tests/test_audit_stream_fallback.py` against a reduced copy of the real
trial that motivated it (`gates/tests/fixtures/awscdk/no-trajectory/`).

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

The hash manifest is, under `HASH_SCHEME_VERSION = 2` (Amendment 47): the
instruction (or every `steps/<name>/instruction.md`), the discovered
skill/MCP/plugin files, the resolved image digest, `extra_cfg` (with
`task.toml [metadata] workspace_seed_sha256` folded in), `compose_sha256` for
`environment/docker-compose.yaml`, and `harbor_equipping` for
`task.toml [environment] mcp_servers`/`skills_dir` — the last three being Harbor's
own channels, which scheme 1 did not read. The three keys are always present, null
when undeclared, so their first use moves a hash instead of pooling two
differently-equipped trials. Rows minted under scheme 1 and scheme 2 are not
comparable by hash, deliberately. CLI-supplied equipping is recorded separately as
content digests in `jobs/*/budget.json` `cli_equipping`
(`gates/equipping.py::cli_equipping_digests`), never as the flag's path.

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

Tier-1 entries are never executed as declared paths by the generated verifier
 (tier 1 is Rego-graded), so a broken `tf_jsonpath` there is inert
documentation that nothing else would ever catch. `.planned_values...
aws_iam_role_policy...values.policy` resolves to NOTHING at plan time whenever
the policy's Resource references a provider-computed attribute; an `op: in`
against zero resolved nodes is False, so this gate turns that into a real
assert failure. See specs/SCHEMA.md §4.2 on `tf_jsonpath`/`cfn_jsonpath`.

Paths resolve through the SAME mechanism the generated verifier uses
for tier 0 — `generator/jsonpath_jq.py`'s jq compilation plus the task's own
generated `tests/ops.py` — not a second, host-side evaluator.
`oracles/lib/structural.py` uses `jsonpath_ng`, which cannot parse the `||`-OR'd
filter syntax several tier-1 CFN paths use at all.

This gate is **engine-independent by design**: it grades every assert through
the jq compiler whatever a spec's `oracle.tier0_engine` says, because the
question it answers is "does this declared path resolve against a real
artifact", which is a property of the shared grammar and not of either
backend. Whether two graders reach the SAME outcome on an artifact is a
different question, answered by `make tier0-parity` (below) and by
`oracles/tests/test_op_parity.py`. The gate stages a `tests/tier0.rego` beside
the driver when the task ships one, because a `rego`-engine spec's verifier —
which this gate runs for real to produce the artifact — aborts its `opa eval`
without it. No spec ships one today.

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

The `jq` on the host must be 1.7.x: the arm images pin `jq` 1.7.1 by sha256
(DECISIONS.md Amendment 43), and tier 0 is graded through it, so a host gate
run under bookworm's 1.6 would be proving a different grader than a trial runs.

### --seed mode: brownfield seed parity

What "the three seeds are equivalent" must and must not mean (specs/SCHEMA.md
§2.7 `workspace_seed`). NOT resource-count or resource-type parity: the whole
thesis of the benchmark is that one L2 construct decomposes into N Terraform
resources, so a census check would fail every honest seed. Equivalence is
defined behaviourally, by declared facts:

1. Every arm's seed synths/plans GREEN with no overlay. A workspace that does
   not is not "existing infrastructure", it is a generation failure.
2. Every `seed_assert` holds on every arm its `applies_to` names, resolved
   through the same jq compiler and the same `tests/ops.py` a real trial's
   tier 0 runs.

The residual, human half is `workspace_seed.premise`: a mechanical gate can
prove "these three configurations satisfy the same declared facts", never
"these three describe the same system". That has the same status as
`oracle.intent`, and is reviewed the same way.

AWS access: `main()` starts one `gates/aws_stub.py::running_stub()` per
invocation and threads its env into every toolchain subprocess. The generated
verifier this drives preflights `aws sts get-caller-identity` on both
Terraform-shaped arms and voids the run without it; the stub answers that
preflight, so the check needs no ambient credentials and can never reach a real
account.

## tier0-parity

`gates/tier0_parity.py` — `make tier0-parity SPEC=… [OUT=dir]`,
`make tier0-parity-all`. **On demand, NOT in `make ci`**: the jq driver is the
shipped tier-0 grader and the Rego engine was evaluated and not adopted
(DECISIONS.md Amendment 42), so nothing here gates a commit. It WAS the landing
condition for the driver itself (Amendment 43); run it when the compiler, the
shared grammar or `tests/ops.py` changes.

Grades every artifact a spec's own fixtures produce with two graders — three
under `--rego` — and requires identical per-assert three-valued outcomes and
identical `tier0_pass`:

| column | what runs |
|---|---|
| driver | the generated `tests/ops.py`, one `--one` call per assert — the grader a trial runs today |
| bash | `assert_check` as it stood before Amendment 43, recovered by `ast` from `<--baseline-rev>:generator/gen.py` and sourced from a scratch file, never from the working tree — the grader a trial ran before |
| Rego (`--rego`) | one `opa eval` of a `tests/tier0.rego`: the task's own under `oracle.tier0_engine: rego`, otherwise compiled into the run's scratch dir, so any spec can be graded |

Every `regex`/`not_regex` assert graded is listed in the summary with both
columns' verdicts, named rather than merely found non-divergent: the flavour
moving from jq's Oniguruma to Python `re` is the one deliberate divergence
surface the migration opened.

Fixtures are produced through `gates/artifact_collector.py`, which drives
`gates/oracle_falsifiability.py::_run_solve` under the aws-stub, so a fixture
runs here exactly as `make falsifiability` runs it — same toolchain
requirements and the same runtime class.

Producing an artifact costs 25–60s; grading one with every column costs
milliseconds. `OUT=<dir>` keeps the collected tree and a manifest, and
`--regrade <dir>` re-grades it with no toolchain at all, which is how a grader
change is checked against the whole corpus in seconds.

### What it cannot prove

**It grades the artifacts that exist.** A divergence reachable only through a
value no fixture produces is invisible to it however many specs it covers — a
regex subject with a trailing newline, a non-ASCII subject under a `\w`
shorthand or a `[[:alpha:]]` POSIX class, and a `|fromjson` string only jq's
lenient decoder reads or one carrying an unpaired `\uD800`-`\uDBFF` escape.
Those are pinned per column in `oracles/tests/test_op_parity.py` and, where the
Rego backend is the one that would diverge, refused per resolved value by its
compiler (specs/SCHEMA.md §4.2, §4.5.1). Agreement here is evidence about the
artifacts in hand, never a proof that two graders are interchangeable.

### Exit codes

`0` = every graded cell agrees. `1` = a divergence, or an artifact that could
not be graded at all. `3` = `NOT_AUTHORED`: no fixture produced a gradeable
artifact, the repo's convention for "non-gating because its prerequisite is not
authored yet".

## normaliser-parity

`gates/plan_normaliser_parity.py` — `make normaliser-parity SPEC=… [OUT=dir]`,
`make normaliser-parity-all`. **On demand, NOT in `make ci`**, for the same
reason as `tier0-parity`: it runs every fixture for real and needs the host
toolchain. Run it when the plan normaliser, the tier-0 compiler or a policy
changes.

The plan normaliser (docs/generator.md#the-plan-normaliser-in-teststierspy)
hoists module resources into `planned_values.root_module.resources`, the shape
every assert and policy already addresses. It runs on all three
Terraform-shaped arms for **every** spec, not only the module ones — so the
whole corpus's grading flows through it, and everything but the `hcl_modules`
pilot is module-free. This gate is the proof that nothing moved there. For each collected artifact it grades the RAW
document and the NORMALISED one and requires:

| compared | requirement |
|---|---|
| tier 0 | identical per-assert three-valued outcome, from the task's own `tests/ops.py` |
| tier 1 | identical `deny` and `not_verifiable` SETS from the task's own `policy.rego` — the rule fired or it did not, and OPA's ordering is not part of the contract |
| the documents | canonical (sorted-key) byte identity |

The `awscdk` arm is not collected at all: its CONFIG declares no normaliser, so
re-grading it would report agreement about a mechanism that did not run.
Collecting `hcl_modules` additionally starts the loopback registry responder
(`gates/tf_registry.py`), without which its fixtures' `terraform init` would
resolve from the public registry or not at all.

### A module-shaped fixture is held to the opposite contract

On a plan that does contain a module the normaliser is SUPPOSED to change the
grading — that is the mechanism, not drift — so none of the three above is
required there. What the gate requires instead is that the change runs in the
loud direction: a tier-0 assert may move OFF `unresolvable`, which is the
module resource becoming visible to a grader that could not see it, and may
never move ONTO it. Its tier-1 sets and its bytes are printed as "the hoist
changed, in the loud direction" rather than demanded, and whether the fixture's
reward still lands where the spec says is `make falsifiability`'s question.

Every `hcl_modules` fixture of the three pilot scenarios is module-shaped and
lands in that column, so the gate now reports a two-digit module-shaped count
rather than a single one; "identical raw versus normalised" is not expected of
any of them, and a run in which they WERE identical would mean the normaliser
had stopped hoisting.

The longest-standing such fixture, and the only one on a module-free arm, is
`s3-notification-authoritative-singleton/hcl-raw/broken/all-wiring-hidden-inside-a-module`,
the deliberate false-fail where correct wiring is hidden in a `module` block.
Its seven tier-0 asserts were all `unresolvable` (the resources were invisible)
and are all `held` on the normalised document (the wiring really is correct).
Its 0.0 therefore rests entirely on that scenario's tier-1 deny for module use
— and since the normaliser drops `child_modules`, the surviving half of that
deny is the one reading `configuration.root_module.module_calls`
(oracles/rego/README.md). A change that stopped preserving `module_calls` would
turn that fixture into a silent 1.0; `make falsifiability` on the spec is what
holds it.

The normaliser is imported from `generator/verify_py.py`'s own `TIERS_PY`
template rather than from a task dir, so the gate runs before the corpus is
regenerated as well as after.

Fixtures come from `gates/artifact_collector.py`, exactly as `tier0-parity`'s
do, and `OUT=<dir>` / `--regrade <dir>` re-check a normaliser change against a
collected tree in seconds with no toolchain.

### What it cannot prove

**It grades the artifacts that exist.** All but one fixture in the corpus is
module-free, so what this gate mostly proves is the zero-drift half: the
normalised document is the identical document. That the hoist grades a
module-shaped plan CORRECTLY — as opposed to loudly — is pinned on hand-written
plan JSON in `generator/tests/test_plan_normaliser.py`: a silent drop, two
resources landing at one address, an overwritten root resource, a deposed
object taking the live resource's unknowns. A module-shaped fixture per catch
is M3 phase 3B, which waits on the vendored modules of phase 4 because a host
gate cannot `terraform init` a module it cannot resolve offline.

### Exit codes

`0` = no drift. `1` = drift, or an artifact that could not be graded at all.
`3` = `NOT_AUTHORED`: no fixture produced a gradeable artifact.

## hcl-merge-bytes

`gates/hcl_merge_bytes.py` — `make hcl-merge-bytes SPEC=… [REUSE=dir] [REV=rev]`,
the byte gate on the lifted HCL pre-parser
(DECISIONS.md Amendment 42). The Python that merges an arm's parsed `.tf`
documents into the plan JSON is now a generated `tests/hcl_merge.py` rather
than a heredoc inside the emitted shell, and the lift is only safe if the
document it writes to `/logs/verifier/oracle-input.json` — the real tier-1
input for an `oracle.hcl_traversal` spec — is unchanged. So the gate runs a
baseline copy of the program taken from a git revision
(`REV=`/`--baseline-rev`, default the parent of the lift commit, the last
revision whose `static_tiers.sh` still carries the heredoc) against each
fixture's kept working copy and compares the two documents by sha256, for the
spec's reference fixture and every broken fixture it ships. The baseline reads
the same `plan.normalised.json` the generated program merged, so a
module-shaped fixture compares the merge and not the normaliser
(`normaliser-parity` owns raw-versus-normalised).

The program reads only its two arguments and the `*.tf`/`*.tf.json` files in
its working directory, so `--reuse <dir>` compares a tree
`tier0-parity`'s `OUT=` already collected and runs no toolchain at all;
without it the gate collects its own through `gates/artifact_collector.py`.

`0` = every fixture's document is identical. `1` = a difference, a baseline run
that failed, or nothing comparable. Not wired into `make ci`: it is a gate on a
one-time lift, run when the pre-parser or its invocation changes.

## verifier-parity

`gates/verifier_parity.py` — `uv run python gates/verifier_parity.py <spec>…
--out FILE.json [--baseline HEAD.json]`. **On demand, NOT in `make ci`**: it
answers one question, asked when the verifier itself changes (DECISIONS.md
Amendment 44, the Python verifier), and it costs a full fixture collection.

The verifier's output is a CONTRACT, not a log. `gates/emit_result.py` reads the
per-assert `PASS [name]` lines, the summary line's `tier1_status=` and the
`/logs/verifier/*` markers; `gates/oracle_falsifiability.py` reads the summary
line and the `<LABEL> FAILED` lines; harbor reads `reward.txt`. A tier-1 FAIL
also prints one `DENY: <message>` line per `deny` entry — an explanation, not a
parsed surface, which is why both summary patterns match a WHOLE line and every
deny message is folded onto one (docs/generator.md, "What a tier-1 verdict
prints"). So the gate runs
every fixture of every arm through `oracle_falsifiability._run_solve` and
records exactly those three surfaces — the reward bytes, the set of files under
the run's logs dir with each one's digest, and the stdout lines the gates parse
— then compares two recordings and names every divergence. Toolchain chatter is
deliberately not compared: it is the arm's own output, identical by construction
because the same command runs.

Two surfaces are normalised, or a recording would diverge from itself: the
sandbox path, which is per-run and which jq quotes back inside an
unresolvable-assert message, and `oracle-input.json`, compared by presence
rather than digest because the plan document it is built from carries a
`timestamp` and reorders its `references` arrays. That document's own bytes are
gated per fixture by `gates/hcl_merge_bytes.py` instead.

It covers the STATIC half, which is what a fixture's `solve.sh` reaches
(`bash tests/static_tiers.sh`). The live, idempotence and teardown tiers are
covered instead by the sandboxed whole-verifier executions in
`generator/tests/test_seed_deploy.py` and `generator/tests/test_teardown_tier.py`
(`generator/tests/verifier_harness.py` stages one task's real emitted verifier
and runs it against stub binaries).
