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
3. **Discovery materializes as code and survives a session reset.** In
   multi-step `apigw-redeploy`, CDK's rbw halves from step 1 to step 2
   (43%→18%, 35%→17%) *despite a fresh session with no memory*. The step-1 code
   in the workspace is the cache. Consequence: our fresh-session design does
   not measure un-amortized cost — it measures cost amortized **through the
   artifact**, which is how real maintenance works.
4. **CDK required an escape hatch on `apigw-redeploy`, both steps** — first
   mechanical escape-hatch evidence, from a scenario not designed to test it.

---

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
2. Do the profile metrics (rbw / escape-hatch / blast radius) become
   **pre-registered headline** columns, or exploratory secondary ones? They were
   found post-hoc, which is exactly the situation pre-registration exists to
   discipline.
3. Does `hcl-modules` become a **fourth arm** (all scenarios) or a **treatment**
   applied to a chosen subset?
4. Is the fresh-session-per-step choice pre-registered as *modelling
   maintenance-by-a-different-engineer* (§3 finding 3), and does an
   explicitly-cached variant become an M2 condition?
