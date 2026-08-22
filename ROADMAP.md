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
| **brownfield / poisoned workspace** (`workspace_seed`) | shipped, **not yet live-proven** | Amdt 28 (DRAFT) |
| identity separation (`workspace_id`, deny-listed agent-visible names) | shipped | Amdt 28 §10 |
| idempotence tier (2nd plan / `cdk diff --fail`) | shipped, **not yet live-exercised** | Amdt 28 |
| teardown-grading oracle | **not built** | blocks one Batch-A scenario |

**Immediate operational debt:** the 2026-08-20 battery was stopped mid-flight
for an OS restart. The AWS account may hold orphaned resources; 4 trials died
with `AgentSetupTimeoutError` (infra, not agent — invalid rows, not zeros) and
must be re-run, and `named-resource-replacement` (the first live brownfield run,
which takes Amdt 28 out of draft) never started.

Re-run priority: **`ecs-swappiness-awscdk`** first — it is the missing third arm
of §3 finding 3, the session's strongest thesis evidence; then `apigw-openapi`
×3 (whose prompt also carries the §1-item-3a quality caveat), then
`named-resource-replacement` ×3.

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
rows are a distinct cell by construction and cannot silently pool.

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

**Today: one scenario, `anchor`, and all 45 tasks hardcode `scenario_id = "anchor"`.**
That is a framework-*sanctioned* degenerate use, not a mistake: aws-bench
hard-requires a member account per task (`_staged_credentials` raises on an empty
`account_mapping`, `aws_trial.py:183-186`) while cdktn-bench grades ~100 %
offline, so anchor exists to satisfy that precondition at ~$0. It deploys one
SSM parameter plus two IAM roles; median deploy ~230 s against upstream's
10-30 min. **There is no amortization argument for or against splitting** — the
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

**Cheap first step, independent of any split:** shrink the hashed/Docker-context
tree (`node_modules`, `cdk.out`, `dist` out of `scenarios/anchor/`), which
removes most spurious baseline invalidation and 218 MB of I/O per reset.

**Note:** no DECISIONS entry has ever weighed one-scenario vs many — it is
asserted as a premise in `scenarios/anchor/README.md`, `scenario.toml`,
`local-registry.json` and `SCHEMA.md` §8.3, never argued. A split needs a
pre-registered amendment, not just a code change, because `scenario_id` is part
of task identity.

---

## 5. Scenario authoring queue

From the 225-candidate mining pass, graded to 26 by the operator
(`docs/scenario-grades/2026-08-20-summary.md`). Batched by form.

### Batch A — greenfield, ready with today's harness (12)
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

### Batch B — brownfield (4 remaining; `named-resource-replacement` is the template)
`s3-acl-vs-object-ownership-log-delivery`, `singleton-child-resource-clobber`,
`policy-json-string-normalization-diff` (idempotence oracle, no re-prompt
needed), `lambda-alias-tracks-unpublished-latest` (hardest — needs pre-deployed
*state* via multi-step `pre_invoke`).

### Batch C — multi-step (5; `apigw-redeploy` is the template)
`drift-blindness`, `sg-inline-vs-standalone-rules`,
`cross-stack-export-deadly-embrace`, `rds-blue-green`,
`s3-notification-on-unowned-bucket`.

### Empirical gates (need AWS; run outside a measurement battery)
- `default-tags-vs-tags-all`: does the perpetual diff still reproduce on
  provider v6?
- `auto-created-security-groups-allow-all-egress`: does aws-cdk-lib still do
  this, and what is terraconstructs' posture?

### A family the evidence suggests adding
**L2-lag by feature age** — pick features by how recently the L2 wrapped them
and measure the discovery tax as a function of that age. Finding 2 (§3) is a
single accidental instance of exactly this.

---

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
4. Does `hcl-modules` become a **fourth arm** (all scenarios) or a **treatment**
   applied to a chosen subset?
5. Is the fresh-session-per-step choice pre-registered as *modelling
   maintenance-by-a-different-engineer* (§3 finding 3), and does an
   explicitly-cached variant become an M2 condition?
