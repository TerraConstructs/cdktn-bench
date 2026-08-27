# Live trial results (running log)

Append-only log of real, billed, live-verified trials. Headline denominator is
**output tokens** (DECISIONS.md Amendment 23); `cost_usd` reported alongside as
cost-of-ownership. These are PILOT data points (n small) — not a scored result
until enough trials exist per cell for the pre-registered estimators
(Kaplan-Meier tokens-to-green, Wilson success-rate). Do not aggregate into a
headline before the census is adequate.

All trials: `claude-code` / `claude-sonnet-5`, env `cdktn-anchor`, account
886312446417 us-east-1, 100-turn backstop, `MAX_TOKENS` unset (token-uncensored
pilot), mutating scenarios run the agent as `QALocalInvocationApplicationAdmin`
(Amendment 24).

## apigw-redeploy — SINGLE-STEP form (live: apply → add /status route → re-apply → verify)

**FORM: single-step (pre-Amendment-27).** Every row in this table was produced
under the **single-step** form of `apigw-redeploy`, whose one prompt named the
day-2 change up front. **DECISIONS.md Amendment 27 §2 forbids pooling these with
any multi-step-form result, in any estimator, at any n** — the two forms are
different scenarios (different prompt content, and Amendment 26 §4 already
refuses cross-shape tokens-to-green comparisons). They remain valid pilot
evidence *for the single-step form*; nothing here is retracted. Multi-step-form
rows go in the separate table below — never in this one.

| date | arm | reward | output tok | num_turns | cost $ | live_check | job |
|------|-----|-------:|-----------:|----------:|-------:|:----------:|-----|
| 2026-08-13 | awscdk          | 1.0 |  9,403 | 33 | 0.75 | 3/3 pass | jobs/g-live-awscdk-1/2026-08-13__18-11-19 |
| 2026-08-13 | terraconstructs | 1.0 | 24,218 | 80 | 3.34 | 3/3 pass | jobs/g-live-tcons-1/2026-08-13__18-36-36 |
| 2026-08-13 | hcl-raw         | 1.0 | 45,535 | 49 | 2.28 | 3/3 pass | jobs/g-live-hcl-2/2026-08-13__15-34-38 |

**First full three-arm read (n=1 per arm — directional only, NOT significant):**

- **Output tokens (the denominator) order the arms exactly as the thesis
  predicts:** awscdk 9.4k < terraconstructs 24.2k < hcl-raw 45.5k. aws-cdk-lib
  (most mature L2) needs the least authoring; terraconstructs (typed, but younger
  L2 over a Terraform backend) sits in the middle (~2.6x fewer than HCL, ~2.6x
  more than awscdk); raw HCL needs the most.
- **Turns tell a different, independent story:** terraconstructs took the MOST
  turns (80) despite writing far fewer tokens than HCL (49) — it authored less
  but *iterated more*, likely wrestling with `cdktn synth`/coverage friction.
  Output-tokens (authoring effort) and turns (interaction friction) are separate
  axes; the thesis rides on the former.
- **Cost inverts vs tokens:** terraconstructs is the MOST expensive ($3.34 >
  hcl-raw $2.28) despite fewer output tokens, because 80 turns → 7.48M cache-read
  (context replayed each turn dominates billed cost). This is exactly why
  Amendment 23 put the metric on output tokens, not cost/cache — cost tracks
  turn count, not authoring skill.

**Caveats.** n=1 per arm; no variance. This scenario is CDK-favorable by
construction — its catch is the salted-deployment logical-id that CDK's `RestApi`
L2 emits automatically but HCL must wire by hand (`aws_api_gateway_deployment`
triggers). Expect gaps to narrow on scenarios without such a sharp L2 advantage.
Next: repeat trials for variance; more scenarios for generality.

### Superseded / context
- The very first live trial (`apigw-redeploy-hcl-raw`, 8-turn budget) was
  right-censored by a config bug (`error_max_turns` at 8 turns), reward 0.0 —
  NOT a real failure. Motivated the turn-budget fix (Amendment 22). Excluded.

## apigw-redeploy (multi-step form, 2026-08-20+)

**FORM: multi-step (Amendment 27).** Two steps, `01-initial-deploy` →
`02-change-request`, with no foreshadowing in step 1. This is a **new
pre-registered comparison with its own census** (Amendment 27 §2): rows here
start at n=0 and must never be pooled with the single-step table above.
Headline metric is **tokens-to-green-across-steps** (Amendment 26 §4: the
cumulative sum of per-step agent OUTPUT tokens up to and including the step at
which the final oracle first passes), so the token column is cumulative across
steps, not per-step.

Amendment 26 is **DRAFT until the first live multi-step run**, and no
multi-step result may be published while it is — record rows here, publish
nothing from them yet.

*(No trials yet.)*

| date | arm | reward | output tok (cum.) | num_turns | cost $ | live_check | job |
|------|-----|-------:|------------------:|----------:|-------:|:----------:|-----|

## named-resource-replacement — BROWNFIELD form (2026-08-20+)

**FORM: brownfield (Amendment 28).** Single-step, but the workspace does **not**
start empty: each arm ships a hand-authored, plan-green, already-deployed
configuration (`workspace_seed`) and the prompt is a change request against it.
This is a **third stratum**, and Amendment 28 §6 forbids pooling it with
greenfield rows — either table above — for the same reason the two tables above
are separate: a brownfield trial is graded on a change to code the agent did not
write, a greenfield one on authoring from empty. Averaging them produces a
number that describes neither.

Note the aggregator does **not** enforce this: its cell key is
`(arm, model, harness)` and carries no scenario-form dimension, so `make
metrics` must not be run over a results directory holding more than one form.
Aggregate each stratum separately until that changes (Amendment 28 §6).

This scenario also carries the gating, fail-closed **idempotence** tier
(Amendment 28 §4). It was first exercised live on 2026-08-26 and returned
`converged` on all three arms; that row promoted **Amendments 28 and 31 to
ACCEPTED**.

**The rows below are publishable, subject to Amendment 28 §6: brownfield is a
SEPARATE STRATUM and is never pooled with greenfield.** n=1 per arm — the
reward column is solid, the token column is directional (two hcl_raw failures
earlier in this project differed 54% in tokens on the same scenario).

| date | arm | reward | output tok | num_turns | cost $ | live_check | idempotence | job |
|------|-----|-------:|-----------:|----------:|-------:|:----------:|:-----------:|-----|
| 2026-08-25 | awscdk | 1.0 | 2,727 | 9 | 0.16 | pass | converged | `live-brownfield-seed/2026-08-25__22-21-37` |
| 2026-08-25 | hcl_raw | 1.0 | 5,382 | 14 | 0.23 | pass | converged | `live-brownfield-seed/2026-08-25__22-21-37` |
| 2026-08-26 | terraconstructs | 1.0 | 11,558 | 28 | 0.64 | pass | converged | `live-brownfield-seed/2026-08-26__08-54-19` |

**Read alongside the rows, or they will be misread:**

* **All three arms are GREEN.** This scenario does not discriminate on reward;
  it discriminates on cost. terraconstructs spent **4.2×** awscdk's tokens and
  3× its turns, with read-before-write at 4% vs awscdk's 22%.
* The terraconstructs row is a RE-RUN. Its first attempt scored 0.0 on an
  idempotence tier that re-synthesized without `CDKTN_BENCH_LIVE=1` and died
  against the offline mock-STS fixture — a harness defect, not an agent result.
  That run also used 13,072 tokens over 36 turns AND hit the escape hatch; with
  the tier fixed, the escape hatch disappeared and tokens fell to 11,558. So a
  broken tier was feeding thrash back into the agent's loop, but most of the
  gap is a real arm characteristic, not contamination.
* **VOID, never to be pooled:** the 2026-08-25 `rerun-named-resource-replacement`
  rows (awscdk 1.0/2,696 · hcl_raw 0.0/4,678 · terraconstructs 0.0/5,404). The
  seed was never deployed, so the live check passed vacuously and the trap could
  not fire — `docs/brownfield-seed-not-deployed.md`.
* **NOT a valid row:** 2026-08-26 `live-brownfield-seed/2026-08-26__14-19-22`
  (awscdk, new equipping hash after the baked-`tsc` image change). Seed
  deployed, idempotence converged, rename correctly applied — scored 0.0 because
  one `describe-security-groups` call timed out. A direct account scan
  afterwards found the group present and correctly renamed. See ROADMAP §5b.1.


## 2026-08-27 — Amendment 32 promotion battery (`jobs/amend32-promotion`)

First battery under live-only AWS access (DECISIONS.md Amendment 32, promoted
2026-08-28 on these rows). claude-sonnet-5, k=2, `max_turns=100`, arm images
rebuilt (`make build-arms`) and `env setup` re-run beforehand — new equipping
and environment hashes; rows are a new stratum relative to everything above.
Every trial valid on its first attempt; zero harness-archaeology strings in
any agent trajectory.

**Greenfield, read-only** — `2026-08-27__21-38-21`, 6 trials in 6m54s wall-clock:

| arm | reward | output tok | num_turns | cost $ |
|-----|-------:|-----------:|----------:|-------:|
| awscdk | 1.0 / 1.0 | 3,815 / 4,245 | 22 / 20 | 0.19 / 0.17 |
| hcl_raw | **0.0 / 0.0** | 1,244 / 1,158 | 9 / 10 | 0.09 / 0.06 |
| terraconstructs | 1.0 / 1.0 | 6,099 / 3,947 | 44 / 25 | 0.40 / 0.22 |

`ecs-swappiness`: the Amendment 22 thesis row replicates on both attempts.
hcl_raw's `terraform plan` was green against the real account on the agent's
first command; tier-1 caught the swappiness-without-maxSwap trap.

**Multi-step, mutating** — `apigw-redeploy`, `2026-08-27__21-50-09`
(second attempts appended as they land):

| arm | reward | output tok | num_turns | cost $ | live_check |
|-----|-------:|-----------:|----------:|-------:|:----------:|
| awscdk | 1.0 / 1.0 | 8,447 / 10,314 | 56 / 65 | 0.47 / 0.55 | pass |
| hcl_raw | 1.0 / 1.0 | 13,480 / 13,781 | 49 / 64 | 0.48 / 0.56 | pass |
| terraconstructs | 1.0 | 16,040 | 116 | 1.09 | pass |

**Brownfield, mutating** — `named-resource-replacement`, same job dir:

| arm | reward | output tok | num_turns | cost $ | live_check | idempotence |
|-----|-------:|-----------:|----------:|-------:|:----------:|:-----------:|
| awscdk | 1.0 | 3,103 | 18 | 0.14 | pass | converged |
| hcl_raw | 1.0 | 4,502 | 17 | 0.16 | pass | converged |
| terraconstructs | 1.0 | 11,024 † | 75 | 0.66 | pass | converged |

† `result.json` carried `None` for every token field on this row (harbor
trajectory-conversion failure, see Amendment 32 "What the run CORRECTED");
values are from the transcript's terminal `result` event via
`gates/emit_result.py`'s `claude-code-stream` fallback.
