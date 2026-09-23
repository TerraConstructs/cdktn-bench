# cdktn-bench roadmap

What we are building toward, what the evidence says so far, and what is queued.
The append-only pre-registration log lives in `DECISIONS.md`; this file is the
forward-looking view and is expected to change.

**Status date:** 2026-08-20.

---

## 1. Where the harness is

| capability | state | proof |
|---|---|---|
| 3 arms (awscdk / hcl-raw / terraconstructs) | shipped | live green on all three |
| uniform toolchain (`tsc` emit → `node`, gate chained into synth) | shipped | Amdt 25 |
| **multi-step trials** (`cdktn_bench` extends Harbor `MultiStepTrial`) | shipped, **live-proven** | Amdts 26/27; first live run 2026-08-20, 1.0/1.0 |
| **brownfield / poisoned workspace** (`workspace_seed`) | shipped, **live-proven** | Amdt 28 (ACCEPTED 2026-08-26); 3 arms green |
| identity separation (`workspace_id`, deny-listed agent-visible names) | shipped | Amdt 28 §10 |
| idempotence tier (2nd plan / `cdk diff --fail`) | shipped, **live-exercised** | Amdt 28 §4; `converged` on all 3 arms 2026-08-26 |
| teardown-grading oracle | **not built** | blocks one Batch-A scenario |

**Operational debt (updated 2026-08-26).** The 2026-08-20 battery's backlog is
mostly cleared:

* `ecs-swappiness` ×3 — **DONE** 2026-08-25. awscdk 1.0/3,332 · terraconstructs
  1.0/5,090 · hcl-raw 0.0/1,780. The missing third arm of §3 finding 3.
* `named-resource-replacement` ×3 — **DONE** 2026-08-26, and it is the first
  valid brownfield row (Amdts 28 and 31 both ACCEPTED on it). The 2026-08-25
  attempt was VOID: the seed was never deployed
  (`docs/brownfield-seed-not-deployed.md`, now closed).
* `apigw-openapi` ×3 — **still outstanding, deliberately.** Its prompt is
  known-bad (over-specified; the cautionary example in
  `docs/adding-scenarios.md`). Needs a lean prompt + shape-tolerant oracle
  before it is worth spending a battery on.
* Account hygiene — clean. `env verify` matches baseline; the account was reset
  to baseline 2026-08-26 after the last trial.

**Still open:** `make parity` (cross-arm prompt parity) is never invoked by CI —
neither `ci/run-ci.sh`'s per-scenario loop nor `make check` calls it — so the
property that keeps tokens-to-green comparable across arms has zero CI
coverage. `full-ci` has also grown from ~45 min (Aug 13–19) to ~3 h (Aug 26)
with no `timeout-minutes` on either job and no npm/Terraform provider caching.

---

## 2. What we measure — a profile, not a scalar

A single weighted score would bury the inversions that make the results worth
publishing (see §3). What we report:

**Headline** — output tokens-to-green (Amdt 23), reported **separately per
posture** and never pooled (Amdts 23/27/28):

| posture | measures |
|---|---|
| greenfield | day-1 authoring cost |
| multi-step | day-2 change cost on code the agent itself wrote |
| brownfield | day-2 change cost on code it did **not** write |

**Admission gates (pass/fail, not scored)** — correctness, idempotence, and, if
`docs/design/oracle-authority-proposal.md` is adopted, the behavioural probe.

**Profile columns** — extracted deterministically, no judgement:

| metric | definition | state |
|---|---|---|
| **read-before-write (rbw)** | output tokens emitted before the first mutation of the arm's own entry file, absolute and as a share of the trial | **built** (`metrics/extract_signals.py`) |
| **escape-hatch incidence** | did the solution ever leave the L2 (`Cfn*`, `addOverride`, `defaultChild`; provider-level raw resources) | **built** |
| **blast radius** | resources `replace`d vs `update`d in place by a change | **not built** — needs the plan/changeset captured as an artifact |

### Why not a maintainability rubric

Static maintainability metrics are either tautological or arm-biased here. LOC
restates the compression premise rather than testing it; cyclomatic complexity is
meaningless for declarative IaC; type-safety counts are biased by construction;
and LLM-judged readability has a **structural** defect — credible judging needs
blinding, and TypeScript vs HCL cannot be blinded, so any judge score is
permanently confounded with arm identity.

**Maintainability is therefore operationalized as the cost of the next change**,
which the brownfield and multi-step postures measure directly.

---

## 3. What the evidence says so far

From the partial 2026-08-20 battery (9 valid trials + the standalone multi-step
run). **n=1 per cell — these are hypotheses, not findings.**

1. **The discovery tax is about abstraction distance, not types.** Mean rbw is
   **33% for awscdk**, **3% for terraconstructs**, **10% for hcl-raw** (the
   hcl-raw figure is inflated by one failing trial; its successful runs are
   1–3%). terraconstructs is *also* typed TypeScript L2s, and it patterns with
   HCL. The separator appears to be how far the abstraction departs from the
   underlying resource model the agent already knows — `aws-cdk-lib` L2s carry
   their own vocabulary that must be read out of `.d.ts` files; terraconstructs
   constructs sit close to Terraform provider resources.
2. **Tokens-to-green can invert.** `sfn-jsonata` (Step Functions JSONata):
   awscdk 15,533 output tokens / 46% rbw vs hcl-raw 7,033 / 2% — both green,
   no type errors on either side. The CDK cost was **front-loaded reading**, not
   failure. This is the L2-lag family: when a service feature is newer than the
   abstraction's ergonomics, pass-through beats abstraction.
3. **Transparency cuts both ways — `ecs-swappiness` is the mirror of finding 2.**
   `memorySwappiness` is silently inert unless `maxSwap` is also set; the prompt
   asks only for swappiness=42 and never names `maxSwap`. **hcl-raw wrote
   `linuxParameters = { swappiness = 42 }`**, passed all three tier-0 asserts
   (`taskdef-exists`, `taskdef-ec2-compatible`, `swappiness-value-correct`), and
   was caught only by tier-1 → **0.0**. **terraconstructs wrote
   `{ maxSwap: 256, swappiness: 42 }`** and stated the reason unprompted — *"ECS
   only honors swappiness when maxSwap [is set]"* — which paraphrases the JSDoc
   on the very property it was typing (`aws-ecs/lib/linux-parameters.d.ts`: *"If
   a value is not specified for maxSwap then this parameter is ignored"*). The
   HCL arm had nowhere to receive that: `container_definitions` is a
   `jsonencode()`'d **string**, an opaque blob the provider passes through with
   no types, no docs, no validation.

   Set beside finding 2, the same property of Terraform flips sign:

   | | `sfn-jsonata` | `ecs-swappiness` |
   |---|---|---|
   | knowledge needed | how the **tool** encodes a feature | how the **service** behaves |
   | HCL pass-through | **wins** — nothing to learn | **loses** — nothing to teach |
   | outcome | hcl 7,033 tok vs cdk 15,533, both green | hcl **0.0**, tcons 1.0 |

   Terraform's transparency is an asset when the missing knowledge is about the
   *tool* and a liability when it is about the *service*. That is a far more
   defensible claim than "abstractions are better", and it makes both results
   necessary rather than one of them noise.

   **A correction to an earlier reading of this row.** hcl-raw's 41% rbw was
   first written up here as a "lostness signal". Re-reading the trace, that is
   wrong: its whole run was 7 tool calls — `ls`, `Read main.tf`, `Edit main.tf`,
   `terraform init`, `validate && plan`, `Read`, write-answer — i.e. two normal
   orientation calls before editing at step 3, then genuine self-verification.
   The 41% is a **small-denominator artifact** (477 of just 1,152 output
   tokens), not confusion. rbw% is only comparable between trials of similar
   size; report the absolute alongside it and treat sub-2k-token trials as
   uninformative on this axis. **No lostness claim is supported by this data.**

   **Self-verification could not have saved it, but a LIVE probe would have —
   verified empirically 2026-08-20 against account 886312446417.** Registering
   the agent's own shape via the ECS API and reading it back:

   | sent | stored, per `describe-task-definition` |
   |---|---|
   | `linuxParameters: {swappiness: 42}` | **`linuxParameters: {}`** — silently dropped |
   | `linuxParameters: {swappiness: 42, maxSwap: 256}` | `{maxSwap: 256, swappiness: 42}` — kept |

   `RegisterTaskDefinition` returns **`ACTIVE`, revision 1** — a clean success
   that silently discards the configuration. So the trap is **API-visible**:
   `describe-task-definition` exposes it immediately as an empty
   `linuxParameters`. What could NOT have caught it is anything the agent ran
   offline — `terraform plan` and `validate` both passed, because the config is
   valid Terraform; the discard happens server-side at registration.

   Two consequences worth carrying forward:
   - This is **positive evidence for the behavioural-oracle direction**
     (`docs/design/oracle-authority-proposal.md`): a two-line live probe
     catches this more directly than the tier-1 structural assert does, and
     without encoding the coupling knowledge into the oracle at all.
   - **Hypothesis (untested):** because Terraform sends `swappiness` and AWS
     stores `{}`, the next `refresh`/`plan` should read back the empty map and
     show a **perpetual diff** — meaning the idempotence tier would also catch
     this. Worth confirming on the first live run of this scenario.

   It failed **cheap** — 1,152
   output tokens, 8 messages, the smallest trial in the battery — the signature
   of a *confident* wrong answer, which a pass/fail oracle plus a token count
   would have scored as "efficient".

   **The delivery mechanism is verified, not inferred.** The terraconstructs
   agent's tool sequence reads: step 5 `grep` for the ECS type files, steps 6-8
   `Read` `ec2-task-definition.d.ts`, **`linux-parameters.d.ts`** and
   `container-definition.d.ts`, … step 13 the first `Write` of the solution. It
   **read the JSDoc carrying the coupling before writing a line**. The
   abstraction delivered the knowledge at runtime; the agent did not merely
   happen to agree with it.

   **Still unmeasured, and the obvious re-run:** awscdk's row was lost to the
   infra timeout, and it ships the identical JSDoc.

4. **Discovery materializes as code and survives a session reset.** In
   multi-step `apigw-redeploy`, CDK's rbw halves from step 1 to step 2
   (43%→18%, 35%→17%) *despite a fresh session with no memory*. The step-1 code
   in the workspace is the cache. Consequence: our fresh-session design does
   not measure un-amortized cost — it measures cost amortized **through the
   artifact**, which is how real maintenance works.
5. **CDK required an escape hatch on `apigw-redeploy`, both steps** — first
   mechanical escape-hatch evidence, from a scenario not designed to test it.

---

### The unifying reading — an abstraction is crystallized community failure

Findings 2 and 3 look contradictory (transparency wins, then loses) until you
ask *what an abstraction actually contains*. It is not primarily an API wrapper:
it is **accumulated community experience of what goes wrong, encoded so the next
person cannot easily repeat it**. The `swappiness`/`maxSwap` JSDoc is somebody's
production incident turned into a docstring. Terraform community modules exist
for the same reason — wiring raw provider resources into a working system was
hard, so practitioners captured the hard-won composition lessons and shared them
as code.

This gives one law that explains both findings:

> **abstraction advantage ≈ (encoded hard-won experience) − (cost of learning
> the abstraction's own vocabulary)**

- `ecs-swappiness`: an old, well-trodden, painful corner → much experience
  encoded → the abstraction teaches → **abstraction wins**.
- `sfn-jsonata`: a feature newer than its wrapper → little experience encoded
  yet → only vocabulary left to learn → **pass-through wins**.

The L2-lag family (§5) is therefore not a separate phenomenon; it is this law
evaluated where the first term is still near zero.

**The LLM-specific half.** A model knows the *head* of its training
distribution, not the tail. Popular resources and mainstream patterns are known
deeply; niche couplings like `swappiness`/`maxSwap` are not. So the prediction
sharpens into something measurable:

> the abstraction advantage should be **largest exactly where the model's prior
> knowledge is weakest**, and should invert to a pure vocabulary tax where the
> model already knows the answer.

That is a dose-response claim on an axis we can measure directly — see M6.

**A complication to state up front:** an abstraction helps through *two*
channels — runtime delivery (what finding 3 measures) and **training-corpus
enrichment** (CDK's docs are themselves in the corpus, so the abstraction may
have already taught the model, invisibly, and that improves even the raw-HCL
arm). Only the first is visible in a trial. M6 separates them.

## 4. Measurement roadmap

### M1 — finish the profile (cheap, no new trials)
Land `blast radius` (needs the plan/changeset persisted as a trial artifact),
wire `metrics/extract_signals.py` into the metrics pipeline with tests, and emit
rbw / escape-hatch as first-class result fields rather than post-hoc extraction.

Blast radius reads **`resource_changes[]`**, not `planned_values`: it is already
flat, carries `module_address` and instance-keyed addresses, and holds the
`change.actions` the metric counts. That is the same read the `hcl_modules` plan
normaliser needs (M3 phase 3, `docs/design/tf-modules-arm.md` §1), so the
artifact is captured once and serves both.

### M2 — equipping factorial: does materialized discovery erase the tax?
The harness is **already built for this**: `gates/equipping.py` hashes
skills/MCP/plugins into trial identity, so `arm × equipping` is a legitimate
factorial design today.

- **H1:** giving the awscdk arm a CDK skill collapses rbw from ~33% toward the
  single digits, and tokens-to-green follows.
- **H2 (the staleness cost):** a deliberately outdated skill *increases* error
  rate relative to no skill at all — the con of caching discovery, measured
  rather than asserted.

Pre-register both before running. Equipping changes the equipping hash, so these
rows are a distinct cell by construction and cannot silently pool. The hash
amendment that row labelling depended on is **done** (Amendment 47, hash scheme
2): `task.toml [environment] mcp_servers`/`skills_dir` and
`environment/docker-compose.yaml` are in the hash, the holdout gate reads the same
channel, and `cli_equipping` records content digests rather than flag paths.

The **tuned** cell for both TF arms is the **bench-owned index tool**, not
`hashicorp/terraform-mcp-server` (v1.3.0 hard-codes the public registry URL,
`pkg/client/registry.go:24`) — `docs/design/registry-index-tool.md` design B, with
its own phases after the `hcl_modules` arm lands: the index tool in the sidecar,
then the tuned-row equipping developed on the **train** split only, then the
amendment that re-registers prereg §2.2's tuned cell. Provider *docs* on those
arms come from AWS Docs MCP.

### M3 — the `hcl-modules` arm (treat as a falsification test, not an enhancement)
Raw HCL is arguably a strawman: Terraform best practice is community modules
(`terraform-aws-modules/*`), chosen precisely for future maintenance. **If we do
not run this, the most obvious practitioner objection to our headline stands
unanswered.**

Honest prior: those modules are among the most-represented IaC artifacts in any
training corpus, so their discovery tax may be near zero — an abstraction with
the compression benefit and *without* the learning cost. **If that is what the
data shows, it is the most important result this benchmark can produce.**

Design note: seed the workspace with both relevant *and* less-relevant popular
modules, so module **selection** cost is measured, not assumed away.

**Settled** (Amendment 46, closing open decision 4 below): `hcl_modules` is a
**fourth arm**, gated per spec exactly like terraconstructs, never a scenario
treatment attribute — module use changes the authoring substrate the way a
construct library does, so it is judged with identical metrics per arm. Design:
`docs/design/tf-modules-arm.md`.

Phases, each landing on its own:

1. **done** — the Python verifier, where the plan normaliser lives (Amendment 44).
2. **done** — this amendment: the arm in the schema and the closed enums,
   `arms.hcl_modules {enabled, reason}` disabled everywhere,
   `predicted_tier_caught.hcl_modules_override`, the factorial and the equipping
   rows restated, `arms/hcl-modules/README.md`. No image, no enabled spec, no
   generated byte moved.
3. The **plan normaliser**, split in two because only the first half can be
   proven without the vendored modules:
   * **3A — done.** `tiers.py::normalise_plan` in the generated verifier on both
     Terraform-shaped arms: every `child_modules` resource hoisted into
     `planned_values.root_module.resources` with `x_module_path` and
     `after_unknown` carried from `resource_changes`, `configuration` annotated
     with `x_unresolved` and never resolved into a value slot, and
     `ENGINE_ERROR` rather than a silent pass when it cannot produce a document.
     Behind `make normaliser-parity` (docs/gates.md), the zero-drift gate over
     every existing Terraform fixture: a module-free plan normalises to itself
     byte-for-byte, so the corpus grades identically before and after.
   * **3B — done, with phase 5's offline half.** The pilot's own fixtures are
     the module-shaped ones: three references and their per-catch negatives now
     plan through `gates/tf_registry.py` on the host, so
     `make normaliser-parity` grades real module plans rather than hand-written
     plan JSON. A module-shaped artifact is held to the gate's OTHER contract —
     an assert may move OFF `unresolvable` (the resource becoming visible is the
     mechanism working) and never ONTO it — while every module-free fixture
     keeps the byte-identity requirement.
     What 3B measured that reading the normaliser could not: the hoist is a
     VALUES-side mechanism, so a tier-1 policy keyed on
     `configuration.root_module.resources` grades a module plan against an
     EMPTY resource set and denies nothing. All three pilot policies were that
     shape, and all three had to gain a configuration-side module walk
     (`oracles/rego/README.md`).
4. **Module delivery — done.** 21 `module@version` trees committed under
   `arms/hcl-modules/environment/modules/`, pinned by upstream commit sha plus a
   per-file sha256 the image build re-checks; the responder as a compose sidecar
   running the arm's own image with a different command, serving
   `versions`/`download`, `/v1/modules/search` and the `/mcp` skeleton M2's index
   tool fills in; a deny-list sweep over the one bench-authored file in the tree;
   an eight-provider filesystem mirror carrying the union the vendored bytes
   declare. Proven under `docker run --network none`: `terraform init` succeeds
   for all 21 vendored modules with no service-discovery request, an unlisted
   version is refused, and `kms` resolves at both 4.2.2 and 4.0.0 (the pin `eks`
   and `route53` carry) against the `hcl-raw` provider pin of Amendment 48. No
   spec enables the arm and no generated byte moved.
5. **Arm plumbing and the pilot** — **offline half done; the live trials are
   not.** The generator emits the arm (per-arm writers, the toolchain and live
   tier maps, `normalise_plan` on), the verifier denies a root `module` call
   whose source is not the registry's, and generation refuses a spec that
   enables the arm with `allow_internet: false` (the sidecar is on the compose
   network Harbor's no-network compose removes). The three pilot specs
   — `acm-dns-validation-record-wiring`,
   `iam-managed-policy-exclusive-vs-attachment`,
   `s3-bucket-hardening-decomposition` — carry module-composed references and
   per-catch fixtures, with `falsifiability`, `grading-proof`,
   `normaliser-parity` and `tier1-coverage` green on all four arms.
   **Still owed: one live promotion trial per arm form**, which needs the
   operator's own environment (shards re-provisioned, `make build-arms`, the
   compose sidecar reachable inside a real trial). Amendment 46 stays DRAFT
   until those run.
6. **Corpus roll-out**, in three slices because the three have different
   blockers.
   * **Slice A — done, offline. Nine read-only greenfield specs decided, eight
     of them enabled**, each with a module-composed reference, a negative
     fixture per catch that applies, and the red-green verdict recorded beside
     every catch a module default moves: `s3-lambda-log-retention`,
     `s3-notification-custom-resource-tax`, `ddb-gsi-attribute-definitions`,
     `caller-identity-arn-as-principal`,
     `lambda-log-group-ownership-and-retention`,
     `asg-launch-template-tag-propagation`,
     `apigwv2-route-settings-zero-vs-unset`, `apigw-openapi`. The ninth,
     `ecs-swappiness`, is REFUSED in writing: full module fit, but its trap is
     property semantics inside one resource, which this rung cannot measure.
     `falsifiability`, `grading-proof` and `tier1-coverage` are green on every
     enabled arm of all eight, plus the three pilots as regression; three
     policies needed a configuration-side module walk and one needed the
     module-output-edge reading the pilots' acm lesson names. Two rules are new
     and now enforced: an enabled arm with no catch in any `applies_to` is
     refused at spec load, and an arm's shared `environment/**` is prompt
     surface for every scenario on that arm
     (`generator/tests/test_scenario_identity.py`).
   * **Slice B — one spec, owner decision owed.**
     `s3-notification-authoritative-singleton` is refused by
     `Spec._hcl_traversal_excludes_hcl_modules`: its oracle resolves symbols out
     of the `.tf` the AGENT wrote, and on this arm the graded resource is
     declared inside an installed module body that merge never reads. Either the
     merge learns to read `.terraform/modules/` (a new capability, and the
     agent's own file is no longer the unit graded) or the spec stays off the
     arm with that stated as the reason. `sfn-jsonata` is the one further
     read-only spec with no slice and no decision yet.
   * **Slice C — the six mutating/brownfield specs, blocked on two things.**
     `apigw-redeploy`, `ecr-repo-destroy-force-delete`,
     `lambda-alias-tracks-unpublished-latest`, `named-resource-replacement`,
     `s3-acl-vs-object-ownership-log-delivery`,
     `singleton-child-resource-clobber`. A brownfield spec cannot enable the arm
     at all until `workspace_seed.entry_file` gains a per-arm `hcl_modules`
     field with a hand-authored, plan-green module-based seed — the refusal
     `test_a_brownfield_spec_cannot_enable_it_yet` pins. And each of these runs
     live, so the fourth arm's tasks have to be promoted on the five shards
     (`generator/shards.toml`) with the compose sidecar reachable inside a real
     trial, which is the same operator environment Amendment 46's promotion
     needs.

### M3 sharpening — modules and L2s capture *different* knowledge
Community modules encode **composition** knowledge ("how to wire N resources
into a working system"); vendor L2s encode composition **plus per-property
semantics** via the doc surface the agent reads at the point of use. A module
that exposes `swappiness` as a pass-through variable would **not** have saved
finding 3 unless its author had personally hit the bug. Prediction to test:
**modules win on composition traps and lose on property-semantics traps.** That
split is the most interesting thing M3 can measure, and it is worth choosing the
Batch-A/B/C scenarios covered by the modules arm to span both kinds.

### M4 — scale dose-response (the biggest live limitation)
Every scenario today is 1–2 files — the regime where abstraction pays off
*least*, because the whole thing fits in the agent's head. The maintainability
argument for typed constructs is fundamentally an argument about scale.

Rather than extrapolating or staying silent, measure the curve: brownfield
scenarios seeded with deliberately varied codebase sizes, with error rate and
rbw as functions of seeded size. `aws-bench`'s own scenario-provisioning CDK app
is a useful real-world calibration point for the upper end.

### M5 — oracle authority
See `docs/design/oracle-authority-proposal.md`. Decide **after** a full battery,
using the measured divergence rate between static-green and live-green.

### M6 — closed-book knowledge probe (cheap, no AWS, no trials)
Operationalizes the §3 law. For every scenario's trap, ask the model the
underlying question **closed-book** — no workspace, no docs, no tools — and
record whether it knows (e.g. *"in an ECS task definition, does setting
memorySwappiness alone take effect?"*). Then:

| closed-book | with abstraction | reading |
|---|---|---|
| knows | correct | abstraction adds only vocabulary cost → expect it to **lose** |
| does not know | correct | abstraction **delivered** the knowledge at runtime (channel 1) |
| knows | — | may itself be corpus enrichment from the abstraction's docs (channel 2) |
| does not know | wrong | the abstraction failed to encode it — an abstraction-quality finding |

This turns "abstractions help" into a per-trap prediction with a stated
mechanism, costs no AWS and no trials, and is the cheapest high-value
experiment on this roadmap. Probe results must be dated: model knowledge is a
moving target, and a trap that is tail-knowledge today may be head-knowledge in
the next model generation — which is itself a finding worth tracking.

### M7 — split the aws-bench scenario (throughput, isolation, hash blast radius)

**Status: DONE — sharded at N = 4, `env setup` green on all four shards, Amendment 33
ACCEPTED 2026-09-09 on its first promotion run.** `generator/shards.toml` holds the single `shard_count` knob; `make shards`
materializes `scenarios/anchor-1..3` from the *tracked* files of
`scenarios/anchor` plus the registry's `scenarios[]`; `generator/gen.py` stamps
`scenario_id` per task and places it under `tasks/<scenario_id>/`, relocating
hand-authored `solve.sh`/`live_check.py` when a task changes shard; both
`check-shard-drift` and `check-scenario-artifacts` stand in `make check`. Rule
and rationale: `specs/SCHEMA.md` §8.3, `DECISIONS.md` Amendment 33 (DRAFT).

The three shard accounts were created by hand, not by `env init`: aws-bench
derives a new account's root email from the management account's domain
(`<scenario>-<tag>-<timestamp>@<domain>`), and that domain is a public mail
provider, so the generated addresses would belong to whoever registered them.
Hand-created accounts use plus-addresses the owner controls, sit in the
`cdktn-anchor` OU and carry the `aws-bench:scenario = anchor-k/PRIMARY` tag
that makes `env init` reuse them.

| shard | account | holds |
|---|---|---|
| anchor | 886312446417 | read-only specs + smoke |
| anchor-1 | 182715287880 | mutating, one arm per spec |
| anchor-2 | 218484443800 | mutating, one arm per spec |
| anchor-3 | 015454941261 | mutating, one arm per spec |

Owner steps that remain (env lifecycle is `aws-bench`, not the fork; only
`run` needs `cdktn-bench`):

```sh
export TMPDIR=$HOME/.awsbench-tmp && mkdir -p "$TMPDIR"   # colima: /var/folders is not shared
aws-vault exec --no-session tcons-mgmt -- uv run aws-bench env init \
  --env-name cdktn-anchor --registry-path ./local-registry.json \
  -d cdktn-bench-anchor@0.1.0 --n-concurrent 4 --wait-for-quotas
aws-vault exec --no-session tcons-mgmt -- uv run aws-bench env setup \
  --env-name cdktn-anchor --registry-path ./local-registry.json \
  -d cdktn-bench-anchor@0.1.0
```

Check before step 2: the Organizations account quota (default 10; closed
accounts count against it for 90 days) and that the role-protection SCP is
attached at **OU** level so the new accounts inherit it. `env setup` must be
re-run for shard 0 too — deleting `node_modules`/`cdk.out`/`dist` moves
`anchor`'s own source hash.

**Today: one scenario, `anchor`, and every task resolves to `scenario_id = "anchor"`
because `shard_count = 1`.**
That is a framework-*sanctioned* degenerate use, not a mistake: aws-bench
hard-requires a member account per task (`_staged_credentials` raises on an empty
`account_mapping`, `aws_trial.py:183-186`). Every trial runs against that live
account (Amendment 32: live AWS is the only trial mode) but the tasks build their
own infra, so anchor's *deployed footprint* is deliberately near-empty: one SSM
parameter plus two IAM roles, median deploy ~230 s against upstream's 10-30 min.
The corpus-level intent is the opposite of offline grading: live validation,
day-2 operations and brownfield are what the hypothesis is about, and the
greenfield-static majority of today's corpus is the imbalance M7 and the
rebalance below correct. **There is no amortization argument for or against splitting** — the
framework has no per-scenario AWS cost accounting anyway (the only `cost_usd` in
the codebase is LLM tokens, `metrics/run_data.py:326-397`).

For reference, upstream runs **8 scenarios / 134 tasks (~17:1)**, split by
*deployed infra shape* (`serverless-apps` = VPC/ALB/RDS/MSK/ECS;
`troubleshooting-multiservice` = 30 stacks across 7 regions), not by account
shape — every scenario is single-account by construction
(`aws_bench/scenario/config.py:51-53`).

**Three reasons to split anyway, all measured:**

1. **Mutating trials serialize account-wide, with the reset inside the lock.**
   `_ScenarioAdmissionGate` (`task/queue.py:32-77`) is keyed by `scenario_id` and
   held across the whole trial *including its reset*. Six mutating trials × ~8.5
   min reset ≈ **51 min strictly serial, regardless of `-n`**. Splitting
   `apigw-redeploy` and `named-resource-replacement` onto separate scenarios
   halves that immediately. (The gate is reader-preferring, so a stream of
   read-only trials can also park a waiting mutating one.)
2. **Contamination is account-global.** A failed reset tags the account
   (`account_management/manager.py:317`) and every later trial on that scenario
   is refused (`aws_trial.py:272-286`) until a clean `env cleanup`. With one
   scenario, one bad mutating trial hard-stops **all 45 tasks**; with two, the 39
   read-only tasks keep running.
3. **Scenario hashing has no blast-radius boundary.** `compute_scenario_hash`
   SHA256s *every* file under the scenario dir (`scenario/hashing.py:32-44`) —
   currently **218 MB / 8,291 files**, of which 8,254 are `node_modules`, plus
   committed `cdk.out/` and `dist/`. Any `npm install` or synth refresh silently
   invalidates the POST_SETUP baseline (the standing `env setup` debt in §1 is
   exactly this), and the tree is re-hashed on every mutating trial's reset.
   Hashing does not cross-contaminate *between* scenarios — but with one
   scenario, "within a scenario" means everything, so that isolation is worth
   zero today.

**What will force it regardless** — three queue items cannot be served by
`workspace_seed` (a file in the agent container) or by multi-step `pre_invoke`
(per-trial), because they need infra that pre-exists the trial:
`rds-blue-green` (a live RDS instance — cannot live in a $0 anchor shared by 45
tasks), `cross-stack-export-deadly-embrace` (≥2 deployed stacks with a live
export/import edge), and `s3-notification-on-unowned-bucket` — the sharpest
case, since anchor's agent role is `AdministratorAccess`, making "a bucket this
principal does not own" **unrepresentable in this account at all**. That one
needs a second account, i.e. a second scenario, by definition.

**Mechanism (parked 2026-08-27, evaluated against aws-bench's account layer).**
Parallelism is the number of *scenarios*: `_ScenarioAdmissionGate` is keyed by
`scenario_id`, and `env init` creates one member account per
`(scenario, account_tag)` from the management account via Organizations
(`account_management/manager.py::ensure_scenario_accounts`). A second
`account_tag` on `anchor` adds nothing. So a split means:

1. N identical shards of `scenarios/anchor` (`anchor-0 … anchor-N-1`; same CDK
   app, different `scenario.toml name`), listed in `local-registry.json`.
2. `generator/gen.py` emits `scenario_id` per task: read-only specs may share a
   shard (they co-run); mutating specs spread across shards so one spec's three
   arms land on different accounts.
3. `env init --n-concurrent N --wait-for-quotas` then `env setup` (which
   `cdk bootstrap`s each account). Check first: the org account quota (default
   10; closed accounts count for 90 days), and that the role-protection SCP is
   attached at OU level so new accounts inherit it (aws-bench attaches the
   region SCP itself).
4. No assert or Rego may hardcode an account id — plans on shard k carry
   shard k's account. Already required by Amendment 32 (live-only AWS).
5. `scenario_id` is trial identity: sharded rows are a new stratum. Land in the
   same amendment window as Amendment 32 so the churn happens once.

Runner, queue and credential staging need no code change.

**Cheap first step, independent of any split:** shrink the hashed/Docker-context
tree (`node_modules`, `cdk.out`, `dist` out of `scenarios/anchor/`), which
removes most spurious baseline invalidation and 218 MB of I/O per reset.

**Note:** one-scenario vs many was asserted as a premise in
`scenarios/anchor/README.md`, `scenario.toml`, `local-registry.json` and
`SCHEMA.md` §8.3 and never argued, until **Amendment 33 (DRAFT)** weighed it.
`scenario_id` is part of task identity, so raising `shard_count` is that
amendment's promotion, not a bare code change.

---

## 5. Scenario authoring queue

From the 225-candidate mining pass, graded to 26 by the operator
(`docs/scenario-grades/2026-08-20-summary.md`). Batched by form.

### Batch A — greenfield, ready with today's harness (12)

**Status 2026-08-24: 8 of 12 authored and committed**, each passing
`make falsifiability` on every arm it declares. Remaining 4:
`caller-identity-arn-as-principal`, `lambda-function-url-partner-scoped-invoke`,
`apigwv2-route-settings-zero-vs-unset`, `ecr-repo-destroy-force-delete`.

Blueprints: `docs/design/batch-a-greenfield-blueprints.md` (identity, lean
prompt, tier plan, catches, verified evidence, arm predictions, per-arm risk).
Authoring order: §1 → §6 → §2 → §9 → §10 → §4 → §8 → §11 → §3 → §7 → §5 → §12.

`s3-bucket-hardening-decomposition`, `ddb-gsi-attribute-definitions`,
`iam-managed-policy-exclusive-vs-attachment`,
`s3-notification-authoritative-singleton`, `s3-notification-custom-resource-tax`,
`caller-identity-arn-as-principal`, `acm-dns-validation-record-wiring`,
`lambda-log-group-ownership-and-retention`,
`asg-launch-template-tag-propagation`,
`lambda-function-url-partner-scoped-invoke`,
`apigwv2-route-settings-zero-vs-unset`, `ecr-repo-destroy-force-delete`.

Harness deltas this batch needs: offline STS for hcl-raw (§4), a literal AMI id
(§3), `verifier.teardown` (§12). Provider-mirror delta: add
`hashicorp/archive` — which lets every Lambda-bearing scenario seed **nothing**,
keeping the packaging differential measurable.

### Batch B — brownfield (4 remaining) — **UNBLOCKED 2026-08-26**

**Was blocked 2026-08-25 on `docs/brownfield-seed-not-deployed.md`** — the
template scenario's seed was never actually deployed, so the agent got config
describing infrastructure that did not exist and a replacement trap with
nothing to replace could not fire.

**Unblocked** by the single-step seed-deploy mechanism (`specs/SCHEMA.md`
§2.7.1, `DECISIONS.md` Amendment 31) and confirmed by the first complete live
brownfield row — three arms, zero exceptions, every arm `seed_deployed` / live
`pass` / idempotence `converged`. Amendment 28 is now **ACCEPTED**, so a
brownfield row may be published, subject to §6 (separate stratum, never pooled
with greenfield).

**Status 2026-08-26: 3 of 4 authored and committed** (`ea2c38b`), each
passing `make falsifiability` and `make seed-parity`, all three carrying a
`workspace_seed.deploy` block:

| scenario | split | note |
|---|---|---|
| `s3-acl-vs-object-ownership-log-delivery` | holdout | authored |
| `singleton-child-resource-clobber` | train | authored |
| `lambda-alias-tracks-unpublished-latest` | train | authored **single-step** — see below |
| `policy-json-string-normalization-diff` | — | **NOT authored**, marked BLOCKED by its author; the blocking evidence is itself unsound (§5b.2) |

`lambda-alias-tracks-unpublished-latest` was designed
(`docs/design/poisoned-workspace-design.md` §6) to need pre-deployed *state* via
multi-step `pre_invoke`. It is expressed **single-step**, because the seed
deploy now performs a real apply before the agent's first token. So multi-step
remains a one-scenario capability (`apigw-redeploy`) and
`pre_invoke.deploy_prior` is still exercised by no real spec.

**These three carry oracle debt — see §5b.2.** No brownfield row from them may
be published until the two metric-biasing findings are resolved.

### Batch C — multi-step (5; `apigw-redeploy` is the template)
`drift-blindness`, `sg-inline-vs-standalone-rules`,
`cross-stack-export-deadly-embrace`, `rds-blue-green`,
`s3-notification-on-unowned-bucket`.

### Empirical gates (need AWS; run outside a measurement battery)
- `default-tags-vs-tags-all`: does the perpetual diff still reproduce on
  provider v6?
- `auto-created-security-groups-allow-all-egress`: does aws-cdk-lib still do
  this, and what is terraconstructs' posture?

### M8 — OPA as the grading engine on all three arms; cfn-guard as a measured capability

**Status: DONE.** Every one of the 20 scenarios grades awscdk tier-1 with
`oracles/rego-cfn/<id>/policy.rego` over the synthesized template, read by the
same `opa eval ... deny` line the TF arms run over plan JSON. `cfn_guard` is no
longer a selectable engine — a spec declaring it fails validation — and
`oracles/cfn-guard/` is deleted. cfn-guard stays installed in the awscdk image
as an arm capability. DECISIONS.md Amendment 45; `make falsifiability` and
`make grading-proof` green on the whole corpus before and after.

**Problem, proven by execution.** cfn-guard 3.2.0 cannot express a cross-resource
join (no logical-id join between a role and the policy that names it), so the
awscdk tier-1 for `iam-managed-policy-exclusive-vs-attachment` degraded into a
count-equality proxy that is unsound **in both directions**: a policy reaching
only one role scores **1.0** (false PASS, defeating that scenario's own catch)
while a policy attached to both roles from both sides scores **0.0** (false FAIL,
contradicted by the template). The byte-equivalent terraconstructs solutions
score the opposite way in each case. Three opus fix rounds could not close it —
this is a **tooling ceiling**, not fixer error, and Amendment 29 §4 makes
equal-strictness grading binding.

**Fix.** Make **OPA/Rego the grading engine on every arm**, including awscdk
(synth → `ScenarioStack.template.json` → the same OPA engine the TF arms already
use). One policy language, one identity domain, parity by construction —
converted scenario by scenario, then made the only engine once the last one
landed.

**cfn-guard is retained, but reclassified.** It stays supported as an arm
capability — it is a real tool an awscdk team actually has. It just cannot be
the *authority* in a cross-arm comparison, because it grades at a different
strictness than the engine used on the other arms.

**Caveat on the capability claim.** "awscdk has more guardrail tooling" should
NOT be evidenced by cfn-guard's existence: Terraform has conftest/OPA, Checkov,
tfsec and Sentinel, and arguably a richer policy ecosystem.

**Decision (owner, 2026-09-09): cdk-nag and `@aws/cloudformation-validate` are
outside the bench design.** They are neither oracles nor oracle complements.
The validate plugin that `aws-cdk-lib` bundles (2.262.0+, and so the pinned
2.263.0) runs on every awscdk synth by default; that is a shift-left feedback
loop the awscdk arm has and the other arms do not, which is **by design** and
part of what the arm comparison measures. The bench's only obligation is to
never prevent the agent from running such tooling (no `allow_internet: false`,
no plugin suppression in the arm image). The one thing worth keeping from the
evaluation is a citation: AWS shipping Rego as the rule language for
CloudFormation validation independently corroborates M8's engine choice.

### M9 — brownfield ADOPTION scenarios (import existing infrastructure)

Distinct from Amendment 28 brownfield, which seeds *code*. Adoption means the
agent must **import real, already-deployed resources** (`terraform import` /
`import` blocks, CloudFormation resource import) and then change them. It is the
one legitimate case for a fixed physical name (Amendment 29 §6: the name is
*given*, not chosen), and it is a large, under-tested slice of real IaC work —
most teams adopt infrastructure long before they green-field it.

**It cannot be served by `workspace_seed` (a file) or multi-step `pre_invoke`
(per-trial): it needs infrastructure that pre-exists the trial.** It therefore
joins the M7 cases forcing a **second aws-bench scenario** — and is arguably the
most compelling of them, since a whole task family depends on it rather than a
single scenario.

### M11 — agent access mode as a measured dimension (after M10; opt-in per spec)

Owner alignment 2026-09-11 and 2026-09-17. Today `verifier.live_check.enabled`
welds two things together: whether the verifier makes AWS calls, and whether
the agent gets the admin role in mutating mode. `sfn-jsonata` already breaks
the weld (a read-only evaluating live check, agent deploys nothing) and the
generator disambiguates with a second condition. The measurement wants them
separate: the same spec, prompt body and tier-0/tier-1 oracles, run once with
validate/plan only (read-only role, shard co-run) and once with apply and
iterate (admin role, mutating, shard-exclusive with reset), so that the
difference per arm is the deploy tax and nothing else.

The amendment that opens this milestone says:

1. `agent_access` is a run dimension with values `read-only` and `read-write`,
   declared per SPEC (never per arm: every arm is judged with identical
   metrics even where one arm's catch cannot fire in a mode). A spec lists the
   modes it supports; the generator emits one task per (arm, mode); the
   read-write ticket carries the self-verify sentence, so prompt parity is
   checked within a mode.
2. Verification depth is separate from agent access. Tier 0 and tier 1 run in
   both modes. `live_check` gains `needs_deployment` (false only for evaluating
   checks such as `states:TestState`); a check that needs a deployment runs in
   read-write cells only. Idempotence (deploy, then re-plan) and the teardown
   tier are read-write-only by definition; declaring them on a spec that also
   supports read-only means "in read-write cells".
3. `cell_key` gains `agent_access`, derived from task.toml (role + concurrency),
   never from `live_check.enabled`. A results directory holding both modes is
   sectioned per (scenario_form, agent_access) with no combined headline, the
   same refusal `scenario_form` already applies. The mode-1-versus-mode-2
   contrast is an explicit secondary contrast paired by (spec, arm) within one
   form, not a pooling. The prereg's "no real apply in v1" and "green = tier
   stack" lines are superseded per mode; the output-token headline stays so
   deploy output verbosity does not leak into the measure.
4. A (spec, arm, mode) cell is graded only where `make grading-proof` proves
   the arm gradeable under that mode; a mode where an arm has no reachable
   catch records that in tier attribution rather than dropping the arm.

Migration of today's 20 specs is mechanical: 14 declare `[read-only]`, 6
declare `[read-write]`, `sfn-jsonata`'s check sets `needs_deployment: false`,
nothing regenerates differently. Adding `read-write` to a static spec is a
per-spec decision with its own self-verify sentence and promotion trial;
`apigwv2-route-settings-zero-vs-unset`'s behavioural live check is the first
candidate. Sequenced after the current runs and after M10's clean-up.

### M10 — one Rego engine for every tier; evaluate `microsoft/regorus`

After the day-2 work. Design memo: `docs/design/m10-one-rego-engine.md`
(engine spike first, tier-0 translation second, parity gates before any
removal). **Spike result (`docs/design/m10-regorus-spike-results.md`): stay on
OPA 1.19.0.** regorus 0.12.0 diverged on 50 of 504 (policy, fixture, query)
pairs: `sprintf` `%q` is unimplemented (22 pairs lose the whole deny set, so
broken fixtures would score 1.0), its scheduler rejects `some _, x in v` inside
comprehensions and comprehensions in `else :=` heads, and its strictness
default is the inverse of OPA's; exit codes and the undefined-query envelope
also differ. Its `--coverage` report is the one capability worth revisiting.
Tier-0 translation therefore targets OPA. The `hcl2json` + locals question
is answered in `docs/design/m10-opa-extension-hcl-locals.md`: the HCL parse
cannot be replaced by plan JSON (no `locals` there) and must not be replaced
by evaluation (the traversal reads raw `${…}` source because the referents
are plan-time-unknown); a custom `opa` binary with Go builtins is possible
(`rego.RegisterBuiltin`, seen by `opa eval` without a capabilities file) but
rejected for one opt-in step on one arm; the recommended move is to lift the
embedded merge Python out of the heredoc into a generated `tests/hcl_merge.py`.
`docs/design/shell-inventory.md` lists the remaining shell surface.

**Owner decisions 2026-09-11.** Decision A is approved in the memo's shape:
`generator/jsonpath_rego.py` as a sibling of `jsonpath_jq.py` over the same
grammar, emitting `tests/tier0.rego` under OPA 1.19.0, landing dark behind
`oracle.tier0_engine` (default `jq`) with the three-way parity matrix and the
all-artifacts parity target before the default flips. The generated Python
verifier is part of the same track and starts with the `hcl2json` merge:
the embedded merge Python leaves the shell heredoc for a generated
`tests/hcl_merge.py`, gated on a byte-for-byte diff of
`/logs/verifier/oracle-input.json` for the reference and six broken fixtures.
**Clean-up is a required final step, not an option:** once the Rego tier 0 is
verified (parity matrix green, all-artifacts parity green, one live battery
graded under it), the jq backend, `_assert_lib.sh`, and the bash that hosted
them are removed, and the arm images drop `jq` from the verifier toolchain.
The track ends when the static oracle is Python, Rego and Go only. Rego was
then not adopted, so the clean-up ran the other way: the bash went and jq
stayed as the path language (Amendment 43).

**Status — Rego tier 0 evaluated and NOT adopted (DECISIONS.md Amendment
42).** `generator/jsonpath_rego.py` compiles the same grammar to
`tests/tier0.rego`, and the emitted policy was then read against the jq script
it would replace: five asserts unroll into hundreds of lines of node chains
where jq is one readable line per assert. jq stays the shipped grader and the
default never flips. What remains available: the compiler, the emitted-policy
path behind `oracle.tier0_engine: rego` (no spec selects it, so no task dir
ships a policy), and `make tier0-parity`, which compiles one on the fly for any
spec — an ON-DEMAND cross-check, removed from `make ci`, with zero divergences
over 305 artifacts. `oracles/tests/test_op_parity.py` keeps three columns,
with the Python driver in the retired bash grader's place.
One divergence class the artifact gate cannot see was found and closed by
refusal: Oniguruma's `$` also matches before one trailing newline and its
`\w`/`\d` are Unicode-aware where RE2's are neither, so the compiler screens
each pattern and reports UNRESOLVABLE for a resolved value the two flavours
would read differently. The `hcl2json` merge Python lift to a generated
`tests/hcl_merge.py` landed and stays.

**Status — the tier-0 driver landed (DECISIONS.md Amendment 43, DRAFT).** The
bash op table is now a generated stdlib `tests/ops.py` plus a per-arm
`tests/tier0.py` assert table over the same, unchanged jq filters
(`docs/design/tier0-assert-libraries.md` §6); `tests/_assert_lib.sh` is gone
from every task dir and from `pre_invoke/`, and Python `re` is the single tier-0
regex flavour. `make tier0-parity-all` graded the whole corpus with the retired
bash library and the driver side by side — 305 artifacts, 1,506 assert
evaluations per column, zero divergences, 70 of them regex. It stays DRAFT until
one live read-only trial is graded by the driver.

**Next, in order.** (1) DONE — `jq` 1.7.1 is pinned by sha256 in all three arm
images and dropped from `apt-get install`, so the tier-0 grading engine is fixed
the way `opa` and `cfn-guard` are and matches the 1.7.x the host gates run
(DECISIONS.md Amendment 43, "`jq` pinned"); the equipping hash moves for all
three arms. (2) ~~The bash in `tests/static_tiers.sh` and `tests/test.sh`~~ --
DONE, DECISIONS.md Amendment 44 (ACCEPTED 2026-09-22): the verifier is `tests/tiers.py` +
`tests/verify.py`, and the two `.sh` files are shims because harbor executes
one and every hand-authored `solve.sh` ends with the other. What is left of
`docs/design/shell-inventory.md` class 2 is the brownfield `pre_invoke/*.sh`.

Two decisions, one independent of the other:

* **Tier 0 is translated to Rego, compiled from the same spec YAML.** At the
  time this was written the generator compiled a spec's JSONPath asserts into jq
  and the three-valued outcome lived in `_assert_lib.sh`; tier 1 is already
  Rego with an explicit
  `not_verifiable` rule set. Compiling tier 0 to Rego from the same YAML keeps
  one assert source and removes the bash between the spec and the verdict. The
  risk is operator parity (`set_eq`, `absent_or_eq`, `not_regex`, unresolvable
  paths): each operator gets a fixture that must produce the identical
  three-valued outcome on both compilers before the jq path is removed.
* **Evaluate `microsoft/regorus`** (Rust Rego, OPA 1.2 compliant, the engine
  behind `@aws/cloudformation-validate`): can it run the existing policy set
  written against OPA 1.19 unchanged, can stateful Rust builtins replace the
  `hcl2json` + locals-aggregation shell, and is the verifier image smaller and
  faster for it. The evaluation runs the whole `oracles/rego*` suite and the
  grading-proof fixtures under both engines; any divergence is a finding, not
  a migration step. `@aws/cloudformation-validate` itself stays out of the
  bench design — the awscdk arm's bundled validate plugin is an arm capability
  the bench never blocks (M8).

### Pre-registered test of Amendment 29 (physical identity not load-bearing)

**`stack-deployed-twice-in-one-account`** — deploy the same stack twice into one
account/region. Fixed physical names collide and fail; generated names pass.
Arm-neutral (every arm can do either), cheap, and it makes the Amendment 29
tenet **falsifiable rather than assumed**. If it does not separate the shapes,
that amendment's premise is weaker than claimed and should be revisited.

### A family the evidence suggests adding
**L2-lag by feature age** — pick features by how recently the L2 wrapped them
and measure the discovery tax as a function of that age. Finding 2 (§3) is a
single accidental instance of exactly this.

---

## 5b. Technical debt — reference-resolution heuristics

**`config_reaches_arn_of` and its dependents are retired debt, not design.**
Recorded here so they are never copied into a new scenario as a pattern.

`terraform show -json` does not carry the `locals` map, and for an attribute of
a resource being *created* the value is unknown at plan time — so the plan shows
only a SYMBOL (`local.arns.media_bucket`), never its referent. Lacking a way to
resolve that, `oracles/rego/s3-notification-authoritative-singleton/policy.rego`
grew a family of proximity heuristics:

| symbol | what it actually asked | why that is wrong |
|---|---|---|
| `config_reaches_arn_of` | "does the plan depend on SOME `aws_s3_bucket.*["arn"]` anywhere?" | attaches no symbol to the attribute, so an ordinary unrelated resource satisfies it for a laundering symbol |
| `references_bucket` clause 2 | same proximity test, second use site | inherits the defect |
| `bucket_denoting_indirections` | treats a symbol as bucket-denoting if the above holds | launders a wrong-type ARN into an accepted one |
| `references_this_topic` clause 2 | corroboration: the symbol must ALSO appear in a slot that wires the topic | denies a *correct* mixed spelling (hoisted for one slot, direct in another) |

Both directions were proven by execution: a wrong-type ARN behind a local scored
**1.0** as soon as any ordinary correct resource touched the real bucket ARN,
and a fully correct solution scored **0.0**. See
`docs/design/conftest-hcl-traversal-spike.md` §1.

**RESOLVED (2026-08-24, `dd789e3` + `460629a`).** Superseded by `hcl2json`-based
static traversal resolution (the memo's verdict: adopt the technique, drop
conftest — its HCL2 parser *is* `hcl2json`, byte-identical output at 4.1 MB vs
68 MB, and `opa` stays the engine). Every heuristic in the table above is
**deleted, not deprecated** — `grep` finds no live call site; only history
comments remain. The capability is `oracle.hcl_traversal: true`
(`SCHEMA.md` §4.6), hcl_raw-only, default false, so it is dormant for every
scenario that does not opt in.

**The rule this leaves behind:** a reference-resolution question must be
answered from the artifact that actually carries the referent — resolved
traversal on the TF arms, the explicit `Ref`/`Fn::GetAtt` logical id on the CFN
arm. A proximity test ("something nearby mentions the right resource") is not a
resolution and must not be graded as one. Where resolution is genuinely
impossible, the honest outcome is a three-valued verdict —
resolved / **ambiguous** / **unresolvable** — with the latter two *denying and
naming what failed*, never guessing in either direction.

**The residual recorded here is CLOSED.** The same-type/wrong-instance defect —
a notification on bucket A with the permission scoped to bucket B's ARN — scored
**1.0** under every layer when this section was written. It now scores 0.0,
direct and behind a local, and the fixtures that pin it are checked in
(`lambda-permission-scoped-to-a-decoy-bucket-directly`,
`...-with-a-literal-notification-bucket`, `...-decoy-for-each-instance`). Closing
it needed two fixes the first attempt missed: the type-only widening in
`slot_names_arn_of` clause 2, and `instance_of` slicing only two path segments,
which collapsed every `for_each`/`count` key of one block into a single
"instance".

**What four adversarial rounds actually taught — carry this forward.** Each
round closed its blocker and the next found a NEW one in the same family: the
launder survived by MOVING (clause 2 → `for_each` → mention-not-position → the
condition's OR-ed value list). The generalisable lesson is not any one fix but
the shape of the mistake: **grading a policy document by provenance instead of
by position**, and **using one quantifier where the domain uses two** (IAM
AND-s distinct condition positions and OR-s the values within one — `some`
across positions, `every` within one). Both were written into the oracles as
virtues before they were found to be defects.

**And the cost is a signal, not just a bill.** The result is a 2,677-line policy
plus a 952-line shared library for ONE scenario, still with no proof that a
fifth round would find nothing — falsifiability proves every *declared* catch
fires, never that no undeclared hole remains. That is the strongest evidence
yet for the oracle-authority inversion (M5): where a property is behavioural,
re-deriving it structurally approaches the "slowly reimplementing the evaluator"
boundary, and a live check would be both cheaper and more authoritative.

### 5b.1 Live oracles have no retry — a transient AWS error becomes a verdict

**Done** (DECISIONS.md Amendment 35, bounded retry on transient AWS errors —
`tests/_live_lib.py` for live checks, `cdktn_bench/aws_transient.py` for the
post-trial reset; contract in `specs/SCHEMA.md` §5 and `docs/runner.md`
"Post-trial reset retry"). The finding it records is kept below because the
amendment's promotion criterion is a live trial that logs a transient retry,
and until one lands this is the evidence.

A single failed AWS call was treated as an answer: `tests/live_check.py`
classified any non-zero `aws` exit it did not recognise as `not_verifiable`,
and fail-closed gating turned that into reward 0.0 — so an infrastructure
hiccup was recorded as an agent result.

Measured 2026-08-26, `jobs/live-brownfield-seed/2026-08-26__14-19-22` (awscdk):
seed `seed_deployed`, idempotence `converged`, the requested rename correctly
applied — scored **0.0** because one `aws ec2 describe-security-groups` call
timed out. A direct account scan afterwards found the security group present
and correctly renamed. Ground truth contradicted the verdict and nothing in the
harness could notice.

The same class hit cleanup four times the same day: `Read timeout on endpoint
URL: "None"` failed two post-trial resets and one `env reset`; the reset that
succeeded was the third attempt of an unchanged command against an unchanged
account.

**Fix, shipped.** Classify AWS failures into TRANSIENT (timeout, throttling,
5xx) versus RESOLVED, retry the transient class with bounded backoff, and only
then fall to `not_verifiable`. The three-valued contract already distinguishes "I could not
tell" from "it is wrong"; what is missing is that one timed-out call jumps
straight to a verdict. Fail-closed is preserved — after exhausting retries the
oracle still refuses to award reward. This makes the oracle stricter about its
own uncertainty, not looser about correctness.

Related: `/logs/seed-deploy-receipt.json` is not downloaded into job artifacts
(Amendment 31), so the anti-vacuity channel cannot be audited post-hoc.

### 5b.2 Batch B oracle debt — 8 major findings, two of which bias the metric

**Open. No brownfield row from these three scenarios may be published until the
two metric-biasing findings are resolved.** Raised by adversarial verification
of the scenarios landed in `ea2c38b`; all three verdicts were
`sound_with_caveats`, zero blockers.

The two that matter most are not oracle bugs but **measurement confounds**:

* **`s3-acl` cross-arm seed asymmetry.** Both Terraform seeds contain the
  literal `object_ownership = "ObjectWriter"` — the exact knob the change
  request targets — while the awscdk seed synthesizes that fact invisibly from
  `accessControl`. Two of three arms are handed the answer to step 1. That is a
  discovery-cost difference injected by the SEED, not by the abstraction, and
  tokens-to-green is the measurement it corrupts.
* **`lambda-alias` arm-asymmetric definition of green.** awscdk's tier-0 carries
  two asserts; both TF arms carry three. An agent that edits the env var,
  deploys, then repoints the alias with the AWS CLI — never touching IaC —
  scores 1.0 on awscdk and 0.0 on the TF arms. Not an L2 affordance; a hole in
  one arm's oracle, biasing toward the arm the thesis is about.

The remaining six: deleting the ownership control scores 1.0 on every offline
tier on every arm (and is the most natural awscdk edit); `live_check` step E
converts a transient AWS error into 0.0 for an already-correct solution (see
5b.1); `singleton`'s idempotence tier is claimed as one of four grading
instruments but cannot observe the headline catch, reporting `converged` on the
poisoned shape; no tier-0 or tier-1 assert joins a prefix to the action
performed on it, so a swapped solution scores green on all three arms;
`policy-json-string-normalization-diff`'s BLOCKED verdict rests on an offline
probe with only identical-value controls and no negative control, inside a
window containing 50 provider crashes; and `lambda-alias`'s awscdk seed poison
is pinned by nothing — its one `seed_assert` is satisfied by both the poisoned
and the disarmed shape.

## 6. Backlog

- **#12 community contribution path** — CONTRIBUTING.md, proposal template,
  credential-free CI gates. Note the tension with M5: full behavioural oracles
  would make the bench unrunnable without an AWS account.
- **#17 equipping-hash gap** — the bare-tag image-digest fallback blinds the
  hash to `environment/`-only changes when docker is absent; needs a
  `HASH_SCHEME_VERSION` bump, so batch it with the next hash-scheme change.
- **#8 differential oracle-strictness check.**
- Variance repeats (`-k`) once the scenario set is broad enough for the cost to
  be worth it; `MAX_TOKENS` censor pilot-set from observed output distributions.

---

## 6b. Owner priorities, in order (set 2026-09-09)

1. ~~Sidecar / environment rework~~ — superseded by Amendment 32 (no mocks
   left to host); recorded in `mock-endpoints.html`.
2. ~~Scenario split (M7)~~ — Amendment 33, ACCEPTED.
3. ~~Drop tier 0.5~~ — Amendment 34, ACCEPTED (live `TestState` check).
4. **Rebalance the corpus toward day-2 / brownfield.** Every greenfield spec
   stays in the corpus; results are reported per form and never pooled. The
   form label is mechanical: Amendment 36 (`scenario_form` REQUIRED on every
   row, first dimension of `cell_key`, composite `…-brownfield` labels,
   mixed directories refuse a combined headline). Batch A is authored:
   `caller-identity-arn-as-principal` (static, tier 0; Amendment 40 moved the
   gate stub to an assumed-role identity for it),
   `apigwv2-route-settings-zero-vs-unset` (shipped STATIC, terraconstructs
   disabled: the plan-shape probe showed an omitted burst limit is a known
   null in `planned_values`, so the plausible-wrong solution is a tier-0
   catch; see the blueprint's correction note), and
   `ecr-repo-destroy-force-delete` — the teardown tier's first gating use
   (Amendment 41, ACCEPTED 2026-09-17).
   `lambda-function-url-partner-scoped-invoke` is dropped. The split was
   re-run once for the three (Amendment 41, split re-computation).
5. Before the first full battery, in this order:
   * ~~§5b.1 bounded retry on transient AWS errors~~ — Amendment 35, DRAFT
     until one observed retry succeeds.
   * ~~Agent commands in the foreground~~ — Amendment 38, ACCEPTED 2026-09-10 (a
     deploy longer than 120 s completes inside one foreground Bash call. This
     replaces the "distinct verifier outcome for a deploy left running"
     idea: with backgrounding off the condition cannot recur.
   * Node 22 floor on the awscdk and terraconstructs images (aws-cdk-lib and
     cdk-terrain raised theirs; cdk-terrain's base image is
     `bookworm-slim-node22`, open-constructs/cdk-terrain PR #394):
     `node:22.23.2-bookworm-slim` digest-pinned, smoke environment synced,
     `make build-arms`, one smoke trial.
   * ~~Teardown tier~~ — Amendment 37, ACCEPTED 2026-09-10 (`specs/SCHEMA.md` §5.2,
     `gen.py::TEARDOWN_COMMAND`, `generator/tests/test_teardown_tier.py`).
     `named-resource-replacement` opts in NON-GATING as the promotion vehicle;
     promotion needs one live trial writing `teardown-result.json` with outcome
     `clean` on at least one arm. First gating use:
     `ecr-repo-destroy-force-delete`.
   * ~~`predicted_tier_caught: "teardown"`, and the first GATING teardown~~ —
     Amendment 41, ACCEPTED 2026-09-17 (`jobs/amend41-promotion`: reference
     1.0 with teardown `clean` on all three arms, hcl_raw fixture 0.0 with
     `destroy_failed`, awscdk completion line captured).
   * ~~`grading-proof` accepting an observed live-tier catch as proof of
     gradeability~~ — Amendment 39, ACCEPTED 2026-09-10
     (`gates/grading_proof.py::live_tier_proof`,
     `gates/tests/test_grading_proof.py`, `docs/gates.md#grading-proof`).
     Unblocks `lambda-alias-tracks-unpublished-latest`, red in `make ci`
     because it declares no tier-1 catch and a tier-1 rule there is vacuous on
     awscdk.
   * ~~Rows lost to Harbor's trajectory conversion~~ — DONE: the audit gate
     falls back to `agent/claude-code.txt` per step when Harbor's converter
     left no `trajectory.json`, tagging the row `audit_source:
     "claude-code-stream"` (`gates/audit.py::steps_from_claude_code_stream`,
     `gates/tests/test_audit_stream_fallback.py`, `docs/gates.md#audit`);
     both affected rows now emit valid at reward 1.0, and the step-id gap is
     filed in `docs/upstream/harbor-trajectory-step-id-gap.md`.
   * ~~Image builds blocked by the release CDN~~ — DONE: the pinned build-time
     assets are mirrored on the host and served to build containers
     (`scripts/asset_mirror.py`, `scripts/prebuild-tasks.sh`,
     `docs/asset-mirror.md`); the sha256 pins still gate every fetch.
6. Comment clean-up continues as part of every change (rules in CLAUDE.md
   "Comments"); remaining hot spots are `generator/gen.py` bodies, the
   emitted template strings, hand-authored `solve.sh` files, `arms/*/README.md`,
   `scripts/run-bench.sh` and `oracles/rego*`.
7. After the day-2 work: M10. Decision A (tier 0 compiled to Rego from the
   same YAML) was built and NOT adopted — the emitted policy is unreadable
   beside the jq script, so jq stays the grader; see M10's status note for what
   stays available and what comes next (the generated `tests/tier0.py` driver
   and the sha256-pinned `jq` have landed; the bash removal has not).
   `microsoft/regorus` was evaluated and rejected against the existing policy
   set (`docs/design/m10-regorus-spike-results.md`).

## 7. Open decisions

1. Adopt the oracle-authority inversion (M5)? — decide on battery data.
2. Is the §3 law ("abstraction advantage = encoded experience − vocabulary
   cost") pre-registered as **the** thesis, replacing the flatter
   "typed L2s beat raw HCL" framing? It is better supported by the evidence and
   it is falsifiable in a way the flat version is not — but it was derived
   post-hoc from n=1 pairs, so M6 should test it before it is promoted.
3. Do the profile metrics (rbw / escape-hatch / blast radius) become
   **pre-registered headline** columns, or exploratory secondary ones? They were
   found post-hoc, which is exactly the situation pre-registration exists to
   discipline.
4. ~~Does `hcl-modules` become a **fourth arm** (all scenarios) or a
   **treatment** applied to a chosen subset?~~ **Closed** by Amendment 46: a
   fourth arm, gated per spec (so it phases in scenario by scenario rather than
   arriving on all of them at once), because module use changes the authoring
   substrate and must be judged with identical metrics per arm.
5. Is the fresh-session-per-step choice pre-registered as *modelling
   maintenance-by-a-different-engineer* (§3 finding 3), and does an
   explicitly-cached variant become an M2 condition?
