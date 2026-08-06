# Pre-Registration: Do typed intent-level constructs beat raw HCL for AI-assisted IaC?

**Status:** Pre-registered design. All decisions below are fixed *before* data collection. Any deviation during execution is logged as a documented amendment with rationale.

**Purpose:** Supply empirical weight to **driver #4 ("the AI inflection")** of the AWS CDK × Terraform/OpenTofu PRD — the claim that mature, strongly-typed, intent-level constructs are a more *token-efficient* and *reliable* substrate for AI-assisted infrastructure than verbose, weakly-typed HCL.

> **All design decisions are locked** (full list in §10). Trials: **Sonnet n = 10, Opus n = 5 per cell** (Opus is the cost driver; the unequal n is handled in the analysis plan, §7). `terraform-aws-modules` is a **distinct authoring arm**, not folded into tuned-HCL.

---

## 1. Hypotheses (falsifiable, directional)

**H1 (primary — the bold claim).** For a fixed scenario and model, **even *empty*-CDK reaches green at a lower median tokens-to-green than *tuned*-HCL** (raw or modules). Predicted ordering: **tuned-CDK ≤ empty-CDK ≤ tuned-HCL ≤ empty-HCL.** The strong form is that the typed-construct substrate beats equipped HCL *before* CDK itself is equipped. (Conservative fallback the data may force: tuned-CDK still wins, but empty-CDK lands between the HCL conditions rather than ahead of both — reported honestly if observed.)

**H2 (mechanism, refined).** CDK's advantage is **largest on type-preventable catches** (enum value-traps, attribute nesting), where the type system relocates failure from apply-time to compile-time. On the **anti-L2 catch** (a property the L2 has not yet surfaced), CDK is predicted to be **at parity, not penalized**: the L1 escape hatch is the same out-of-the-box primitive layer raw HCL already lives at, and a community TF module is unlikely to have surfaced a brand-new API faster than AWS's own (CFN-spec-generated, often day-one) L1. The catch is retained precisely to **detect a penalty if that assumption is wrong**; the magnitude depends on the specific property and the L2-adoption timeline, so the scenario must name a concrete real example.

**H3 (reliability).** **Success-rate-within-budget** is higher for CDK arms, and the gap **widens with scenario difficulty**.

**Exploratory (not committed):** The empty→tuned token reduction may be *larger for HCL* (which leans more on retrieved examples/modules) than for CDK (which carries more patterns in-weights). Reported descriptively, not tested.

**What would falsify the core claim:** If **empty-CDK ≈ empty-HCL** on tokens-to-green, the "intrinsic abstraction" claim collapses and only the harness matters. If **empty-CDK > tuned-HCL** (more tokens), the *bold* form of H1 fails even if the conservative form holds. Both outcomes are reported as-is.

---

## 2. Design

A fully-crossed factorial run inside a single agentic harness (**Claude Code**, held constant — not a variable).

| Factor | Levels |
|---|---|
| Model | Claude Sonnet, Claude Opus |
| Harness | Empty shell, Tuned |
| Authoring arm | Raw HCL → TF/OpenTofu · TF modules (`terraform-aws-modules`) → TF/OpenTofu · AWSCDK L2 → CloudFormation |

**12 cells** (2 models × 2 harness × 3 arms). **Trials: Sonnet n = 10, Opus n = 5 per cell.** **10–15 scenarios.**
Total trajectories ≈ (6 Sonnet cells × 10 + 6 Opus cells × 5) × 12 scenarios = **~1,080**.

### 2.1 Arms

- **Raw HCL → TF/OpenTofu.** Hand-written resource-level HCL, no modules. `validate` + `plan` feedback loop.
- **TF modules → TF/OpenTofu.** Composition over `terraform-aws-modules` registry modules — the Terraform-native best-practice rung. `validate` + `plan` feedback loop.
- **AWSCDK L2 → CloudFormation.** TypeScript L2 constructs, `tsc` + `cdk synth` feedback loop.

Three rungs form a gradient: **floor (raw HCL) → TF best-practice (modules) → typed intent (CDK L2).** **No CDKTN/tf.json arm** in v1 (see §6 for the backend confound and its defense).

### 2.2 Harness conditions (symmetric recipe — the only difference is substrate)

Both conditions, both arms, always include the **execute-and-read-error loop** (that is baseline agentic capability, not an advantage).

Both conditions keep the execute-and-read-error loop. **Tuned** adds each ecosystem's real, shipping equipping — concrete MCP servers + authoring skills, not abstract "examples":

| | Empty shell | Tuned |
|---|---|---|
| Model knowledge + execute/validate loop | yes | yes |
| **Raw HCL** & **TF modules** arms | bare | HashiCorp **Terraform MCP server** + **Anton Babenko** Terraform authoring skills / best practices · **AWS Docs MCP** for `terraform-provider-aws` attribute & valid-string lookup |
| **AWSCDK L2** arm | bare | **AWS MCP** + AWSCDK agent-tool plugins / **Kiro Powers** + **AWS Docs MCP** |

Symmetry principle: each arm gets the *same kind* of equipping — an ecosystem docs/MCP layer plus an authoring skill — differing only in substrate. Note both TF arms additionally get AWS Docs MCP so the comparison is not handicapped on provider-attribute lookup; that is a deliberate fairness choice, logged. What makes the comparison unriggable is that no arm gets a capability class the others are denied.

### 2.3 Scope boundary — authoring, not day-2 state management

v1 measures **authoring**: one-shot tokens-to-green from scratch. It deliberately does **not** measure day-2 **state refactoring** (logical-ID stability, unintended replacements under change), for a reason that matters to the PRD:

- State refactoring is a *mutation* task with a different metric — does a change produce a clean plan with no collateral resource replacement — not a generation task.
- The AWSCDK→CFN arm carries **CFN's** state semantics, not Terraform's. A refactoring scenario on this arm would expose the exact CFN state-management weakness the PRD exists to fix — arguing *for* CDK-on-Terraform but *against* the arm currently under test. You cannot demonstrate "CDK-on-TF has better state management" without a CDKTN→tf.json arm (cut from v1).
- Counter-nuance worth recording (the PRD's own argument): HCL is not obviously better here — `for_each` over computed maps, `flatten`/list comprehensions, and stacked `locals` to absorb variable-input combinations produce their own brittle logical identities and painful state moves. CDK's state pain is largely **inherited from CFN**, which is precisely why landing CDK on Terraform's superior state tooling and ecosystem is the proposal.

**Therefore:** the state-management argument is a **separate PRD pillar**, not a v1 result. It is **pre-committed as a Phase-2 mutation/refactoring track** (adds a CDKTN→tf.json arm; logical-ID-stability oracle); full design in §11.

---

## 3. Oracle (tiered, deployment-free)

No real apply in v1. **LocalStack/moto explicitly excluded** — they return false greens on exactly the value-rejection class the study targets (moto accepts invalid enums/attributes).

- **Tier 0 — compile/synth (free, instant).** CDK: `tsc` + `cdk synth`, plus **structural assertions on the synthesized artifact** (e.g., attribute at correct nesting level). HCL: `terraform validate`.
- **Tier 1 — plan + intent (cheap, seconds).** HCL: `plan` + **Rego/OPA** intent matched against the resource dependency graph (IaC-Eval method). CDK: `cfn-lint` + `cfn-guard` + a CloudFormation-graph intent check.
- **Optional residual probe.** EC2 `DryRun` (real API, free) only if a future catch is genuinely API-only and statically undetectable.

**"Green" = passes the full applicable tier stack for that arm.**

**Oracle-equivalence requirement (mandatory control):** Two arms (raw HCL, TF modules) emit TF graphs and **share one Rego oracle**; the CDK arm emits a CFN template needing a **separate cfn-guard oracle**. The TF and CFN oracles must encode the **same intent at the same strictness**. Each scenario's intent is authored once in natural language, implemented in both Rego and cfn-guard, and cross-checked on a known-good reference of all three arms before any trial runs. Divergent strictness invalidates that scenario.

---

## 4. Metrics

**Primary headline: tokens-to-green.** Total trajectory tokens (input + output + tool results: doc reads, MCP responses, plan/validate output fed back) until first green. **Not** the final artifact's token count.

**Censoring & anti-survivorship (non-negotiable):** Runs that never reach green within the budget cap are **right-censored**, not dropped. tokens-to-green is reported as a censored distribution (median + IQR, Kaplan–Meier style), **always paired with success-rate-within-budget** — otherwise the arm that fails more looks artificially cheap.

**Budget cap:** `MAX_ITERS = 8` feedback cycles **or** `MAX_TOKENS` per trajectory (pre-set from a pilot), whichever first. Hitting either = fail (censored).

**Secondary:** `pass@1` (one-shot, no feedback — comparable to IaC-Eval literature); `iterations-to-green` (where enum-steering should show up as fewer cycles); per-tier catch attribution (at which tier each planted catch was caught, per arm = at what cost).

---

## 5. Scenarios & catch taxonomy

**10–15 scenarios** spanning a difficulty gradient (single-resource → multi-resource wiring → cross-service), each embedding at least one planted catch. Composition: the **three real-world catches** below + **one anti-L2 catch** for falsifiability. Scenarios are drawn from / aligned with IaC-Eval difficulty tiers where possible for comparability, but authored to be catch-rich.

| Catch | Example | Caught at tier | Why it discriminates |
|---|---|---|---|
| **Typed value-trap** | `retention_in_days` / log-retention not in the allowed enum set | CDK: Tier 0 (`tsc` rejects non-enum) · HCL: Tier 1 (provider `ValidateFunc`) | CDK enum **steers the model to a valid value before emission**; HCL model may emit an invalid magic number → costs a plan-fail iteration. Advantage shows as fewer iterations / fewer tokens. |
| **Cross-resource graph dependency** | Missing implicit/explicit dependency edge (ordering) | Tier 1 (Rego edge assertion) | Tested **structurally** (assert edge A→B exists), **never** as a flaky real-apply race — races are non-deterministic and would wreck reproducibility. |
| **Nested-attribute misplacement** | ECS task-def Linux `memory` at task level vs. container level | Tier 0 (structural assert on synthesized artifact) | CDK's typed `taskDefinition.addContainer({ memoryLimitMiB })` makes misplacement **nearly unrepresentable**; HCL lets it sail through `validate`. |
| **Anti-L2 (falsifiability)** | Concrete, named property a current L2 has not yet surfaced → forces an L1 / escape-hatch drop | Tier 0/1 | Tests L2's known lag (the weakness that motivated CDK Mixins). **Predicted parity, not penalty** (H2): L1 ≈ the primitive layer raw HCL lives at, and modules rarely lead AWS's own L1. Retained to **detect a penalty if that prediction is wrong** — its presence is what makes every other result credible. |

**Failure-mode hygiene:** Catches must be **type-preventable** (enum/shape errors — where L2 legitimately wins). **Environmental** failures (S3 global-name collision, regional capacity, account quota, eventual-consistency races) hit both arms equally, are pure noise, and are **excluded or held constant** across arms.

---

## 6. Confounds & controls

- **Training-data exposure (the dominant threat).** Addressed by *arm selection*: AWSCDK L2 is a 7-year, AWS-maintained, TypeScript-dense, enum-typed codebase — it carries the abstraction benefit **without** the data-scarcity penalty that afflicts tf.json/CDKTN. This is *why* AWSCDK→CFN (not CDKTN→tf.json) is the high-level arm.
- **Backend confound (CFN vs. TF apply semantics).** The arm choice confounds abstraction-level with backend. Defense: published cross-format evidence shows near-identical LLM retry profiles (CloudFormation ≈ Terraform), so the backend is not the explanatory variable. Cited, not merely asserted. (Cost of declining a CDKTN arm: the oracle-equivalence burden in §3.)
- **Harness asymmetry.** Controlled by the symmetric tuned recipe (§2.2).
- **"Raw HCL is a strawman" rebuttal.** Pre-empted by the explicit **TF-modules arm**: CDK is compared not just to raw HCL but to Terraform-native best practice. If CDK still wins over the modules arm, the abstraction effect is robust to HCL quality.
- **Survivorship.** Controlled by censoring + paired success-rate (§4).
- **Scenario authoring bias.** Intent specs authored arm-blind; catches bucketed by tier-caught before results are seen; anti-L2 catch included.
- **Prompt parity.** Identical natural-language task prompt per scenario across arms; only the target-language instruction differs.

---

## 7. Analysis plan

- Per cell: median tokens-to-green (censored) + IQR; success-rate-within-budget with Wilson intervals.
- **Unequal n.** Opus cells carry n = 5, Sonnet n = 10. The headline tokens-to-green aggregates across scenarios, so each cell still holds ~120 (Sonnet) / 60 (Opus) observations — adequate for the cell-level comparison; the *per-scenario* Opus breakdown is thin and flagged as such. Cross-model (Sonnet vs. Opus) contrasts are secondary and use unequal-n-aware intervals.
- Primary test: tokens-to-green, tuned-CDK vs. empty-HCL, per model — paired by scenario, non-parametric (the distribution is skewed and censored); report effect size, not just p.
- Decompose the empty→tuned and HCL→CDK main effects and their interaction.
- Per-catch tier-attribution table (the "where did it fail, at what cost" result — the most PRD-persuasive artifact).
- All trajectories, prompts, oracle specs, and seeds published for reproducibility.

### 7.1 Eval harness — built on Anthropic's skill-creator methodology

The run/grade/aggregate machinery reuses the **skill-creator** eval loop rather than reinventing it. The mapping is near one-to-one:

- **Paired with-skill / baseline runs → tuned vs. empty harness.** skill-creator's core move (spawn a with-skill run and a no-skill baseline for the same prompt) *is* the empty-vs-tuned axis. Same prompt, two equippings, compared head-to-head.
- **`evals.json` schema → scenario spec.** Each scenario is an eval (`id`, `prompt`, `expected_output`, `files`, `assertions`); the oracle checks (§3) are the **assertions** — objectively verifiable, descriptively named so they read clearly in the viewer.
- **`timing.json` → tokens-to-green capture.** skill-creator already persists `total_tokens` and `duration_ms` per run from the task notification — that is exactly the headline metric's raw signal.
- **`aggregate_benchmark` → per-cell stats.** Produces `benchmark.json`/`benchmark.md` with pass-rate, time, and tokens per configuration as **mean ± stddev with deltas** — the per-cell table this study needs, for free.
- **grader + `grading.json` (`text`/`passed`/`evidence`) → oracle grading.** Programmatic assertions run as scripts (reused across iterations), matching the Tier-0/1 checks.
- **eval-viewer (`generate_review.py`) → human review surface** for qualitative inspection of trajectories alongside the quantitative benchmark.
- **Overfitting control (imported, important):** skill-creator splits eval sets **60% train / 40% held-out** and selects by *test* score to avoid overfitting a description to its evals. The same discipline applies here: the **tuned skills/MCP equipping must be developed on a held-out scenario split**, never tuned on the benchmark scenarios themselves — otherwise the tuned arms are overfit and the comparison is inflated. This is the methodological safeguard most likely to be skipped and most damaging if it is.

---

## 8. Cost

~1,080 trajectories (Sonnet n = 10, Opus n = 5), **API tokens only** (AWS resource cost ≈ $0 — no apply). The cost-balanced split already halves the Opus contribution, which is the dominant term. Order **low-four-figures**. Verify against current model pricing before committing; the remaining lever, if needed, is scenario count toward the lower bound (10).

---

## 9. Prior work anchored

- **IaC-Eval** (Kon et al., NeurIPS 2024) — 458 AWS Terraform scenarios; two-phase no-deploy oracle (compile + Rego/OPA intent on the dependency graph); GPT-4 < 20% pass@1. *The oracle method this study reuses.*
- **IaCGen** — iterative framework: ~80% passItr@1 → 100% passItr@7, ~1.58 iters (Claude-3.5). *Validates iterations-to-green as a discriminating metric.*
- **Multi-IaC-Eval** — cross-format (CFN + TF) retry parity. *The backend-confound defense.*
- **TerraFormer** — documents HCL scarcity → hallucinated resource/attribute names. *The data-scarcity confound, empirically.*
- **ParEVO** ("alignment of abstraction") — high-level functional primitives reduce attention/state-tracking burden. *The mechanism for H1/H2.*
- **AWS Blocks** (preview, Jun 2026) + **CDK Mixins** (GA) — AWS itself betting on intent-level composable blocks for AI coding tools. *External corroboration of driver #4.*
- **Stakpak** — open-source Rust DevOps agent + MCP server + "Rulebooks"/Paks skills; **context-aware synthesis grounded in provider docs with real-time schema validation**, reporting **~95% one-shot validity for Terraform** (1,900/2,000 passing syntax + schema). *The closest shipping instance of the "tuned-HCL harness" this study constructs — strong design reference, and the **Phase-2 external comparison point** (§11).* **Caveat with teeth:** Stakpak's 95% is **syntax + schema validity**, i.e. roughly this study's Tier-0/1 *compile* bar, **not** intent satisfaction (Rego) and not apply-time. A high validity number is therefore not a high *green* number — the same gap IaC-Eval found between compile-pass and intent-pass. The study's bar is deliberately higher. Stakpak's **DevX/CUE** layer (strongly-typed config → TF/K8s/Compose) is itself an abstraction analog reinforcing the thesis.
- **Anthropic skill-creator** — the eval methodology this benchmark's harness is built on (paired with/without-skill runs, assertions, `timing.json` token capture, mean±stddev aggregation, train/held-out overfitting control). *See §7.1.*

---

## 10. Decision log (locked)

| Decision | Choice |
|---|---|
| Claim framing | Mature typed L2 beats raw HCL; type system relocates failure to the cheapest tier |
| Authoring arms | Raw HCL · TF modules (`terraform-aws-modules`) · AWSCDK L2 → CFN — 3 rungs |
| High-level arm | AWSCDK L2 → CloudFormation (no CDKTN/tf.json arm in v1) |
| Oracle | Tiered (compile/synth + plan/Rego·cfn-guard); no apply; **no LocalStack/moto** |
| Headline metric | tokens-to-green (censored) + paired success-rate |
| Harness (tuned) | TF arms: HashiCorp Terraform MCP + Anton Babenko skills + AWS Docs MCP · CDK arm: AWS MCP + Kiro Powers + AWS Docs MCP. Claude Code only |
| Models | Sonnet + Opus → **12 cells** (× 3 arms) |
| Trials/cell | **Sonnet n = 10, Opus n = 5** (cost-balanced) |
| Modules | **distinct arm** (TF-native best-practice rung) |
| Scenarios | 10–15: difficulty spread + 3 catches + 1 anti-L2 |
| Eval harness | built on Anthropic **skill-creator** (paired runs, assertions, timing.json, train/held-out split) |
| Scope (v1) | **authoring only** — one-shot tokens-to-green from scratch |
| Phase 2 (pre-committed) | day-2 state/mutation track; adds **CDKTN→tf.json** arm; logical-ID-stability oracle (§11) |
| Stakpak | **Phase-2 external comparison** (cross-harness reference, not a v1 arm) |

---

## 11. Phase 2 (pre-committed) — day-2 state &amp; mutation track

**Status:** Pre-registered now, executed after v1. v1 stays authoring-only; this track tests the *operational* pillar of the PRD — that CDK on Terraform's state engine refactors more cleanly than CDK on CloudFormation, and at least as cleanly as hand-written HCL.

**Why it needs different arms.** The day-2 argument is unprovable on v1's arms: AWSCDK→CFN carries CFN's state semantics, so it can only show the *problem*, not the fix. Phase 2 adds the arm v1 cut:

| Arm | State engine | What it isolates |
|---|---|---|
| Raw HCL | Terraform | TF state engine + `for_each`/`locals` brittleness |
| TF modules | Terraform | module-level refactor behavior |
| AWSCDK L2 → CFN | CloudFormation | the CFN state pain the PRD exists to fix (baseline) |
| **AWSCDK L2 → tf.json (CDKTN)** | Terraform | **the proposal's payoff — CDK ergonomics on TF state** |

The decisive contrast is **CDKTN→tf.json vs. AWSCDK→CFN**: same authoring model, different state engine. A cleaner refactor profile on the TF side is direct evidence for landing CDK on Terraform.

**Hypotheses (Phase 2).**
- **H4.** CDKTN→tf.json produces **cleaner refactors** (fewer collateral resource replacements) than AWSCDK→CFN on the same change — isolating the state-engine benefit from the authoring model.
- **H5.** CDKTN→tf.json is **at least at parity** with raw HCL / TF modules on refactor cleanliness — the abstraction's logical-ID management is no worse than hand-rolled `for_each`/`locals`, and often better.

**Mutation scenarios.** Each starts from a *known-green* v1 artifact and applies a refactor prompt from the real pain set: add the Nth element to a `for_each`/collection, rename a resource, move a resource between modules/constructs/stacks, split one stack into two. Identical-intent starting artifacts across arms.

**Oracle — logical-ID / plan-diff stability.** Parse the post-change plan for resource actions:
- TF arms: `terraform show -json` on the plan → count `create`/`destroy`/`replace`/`update`; a clean refactor shows only the *intended* actions and **zero collateral replacements**.
- CFN arm: CloudFormation change-set analysis → count resource replacements.
- Pass = no unintended replacement of unrelated resources.

**Metrics.** Refactor-cleanliness rate (fraction of refactors with zero collateral replacement) + tokens-to-clean-refactor. Same censoring / survivorship discipline as v1.

**External comparison — Stakpak.** The same mutation scenarios run through **Stakpak's agent** as an external reference for the shipping "tuned-HCL" ceiling. Treated as a **reference point, not a controlled cell**: Stakpak is a different agent (own model routing, Rulebooks, schema-validation loop), so a difference cannot be attributed purely to substrate — the Claude-Code-held-constant property of v1 does not hold for it. Reported alongside, clearly labeled cross-harness.

**Phase-2-specific confounds.**
- **CDKTN data-scarcity re-enters.** tf.json/CDKTN is training-rare; Phase 2 must give the CDKTN arm a tuned harness (skill + examples) or it measures scarcity, not state behavior.
- **Prior-state requirement (the one cost wrinkle).** Refactoring needs a state to refactor *from*. Unlike v1, this requires either a one-time **cheap-subset real apply** (S3/Lambda/SQS/DDB) to establish state/stack, or pre-built **state fixtures**. This is the only place Phase 2 may incur small real-apply cost.
- **Starting-artifact parity.** All arms refactor from the same intent; the v1 oracle certifies each starting artifact is green before mutation.
