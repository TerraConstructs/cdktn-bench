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

The aggregator enforces this: every row carries a REQUIRED `scenario_form`,
`cell_key` is `(scenario_form, arm, model, harness)`, and a results directory
holding more than one form gets one section per form and **no** combined
headline at all (`pooling_refused: true`) — Amendment 36, resting on Amendment 28 §6.

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
(12 mutating trials, 3h54m wall-clock, strictly serial behind the scenario gate
with a reset after each):

| arm | reward | output tok | num_turns | cost $ | live_check |
|-----|-------:|-----------:|----------:|-------:|:----------:|
| awscdk | 1.0 / 1.0 | 8,447 / 10,314 | 56 / 65 | 0.47 / 0.55 | pass |
| hcl_raw | 1.0 / 1.0 | 13,480 / 13,781 | 49 / 64 | 0.48 / 0.56 | pass |
| terraconstructs | 1.0 / 1.0 | 16,040 / 18,846 | 116 / 130 | 1.09 / 1.41 | pass |

**Brownfield, mutating** — `named-resource-replacement`, same job dir:

| arm | reward | output tok | num_turns | cost $ | live_check | idempotence |
|-----|-------:|-----------:|----------:|-------:|:----------:|:-----------:|
| awscdk | 1.0 / 1.0 | 3,103 / 2,514 | 18 / 16 | 0.14 / 0.14 | pass | converged |
| hcl_raw | 1.0 / 1.0 | 4,502 / 10,487 | 17 / 56 | 0.16 / 0.49 | pass | converged |
| terraconstructs | 1.0 / 1.0 | 11,024 † / 10,937 | 75 / 59 | 0.66 / 0.63 | pass | converged |

All 18 mutating + read-only rows valid on the first attempt; the only harness
event of note is the † token gap. Within-arm attempt variance on
`named-resource-replacement-hcl_raw` (4,502 vs 10,487) is the largest in the
battery — n=2 per arm is still directional for tokens, solid for reward.

† `result.json` carried `None` for every token field on this row (harbor
trajectory-conversion failure, see Amendment 32 "What the run CORRECTED");
values are from the transcript's terminal `result` event via
`gates/emit_result.py`'s `claude-code-stream` fallback.

## Amendment 33 promotion run — 2026-09-09 (sharded scenarios, N = 4)

`jobs/amend33-promotion/2026-09-09__19-09-38`; claude-sonnet-5, k=1, `-n 4`,
`max_turns=100`. Four trials, zero exceptions, three concurrent resets on three
accounts, 21 min wall for the whole run.

| scenario | arm | shard | reward | output tok | turns | cost $ | live_check | idempotence |
|---|---|---|---:|---:|---:|---:|:---:|:---:|
| ecs-swappiness (read-only) | awscdk | anchor | 1.0 | 3,850 | 13 | 0.21 | — | — |
| named-resource-replacement | awscdk | anchor-1 | 1.0 | 2,506 | 10 | 0.12 | pass | converged |
| named-resource-replacement | hcl_raw | anchor-2 | 1.0 | 3,383 | 8 | 0.12 | pass | converged |
| named-resource-replacement | terraconstructs | anchor-3 | **0.0** (invalid-infra) | 5,588 | 23 | 0.32 | fail_stale | not_verifiable |

The terraconstructs 0.0 is `invalid-infra`, excluded from every stratum
(DECISIONS.md Amendment 38, foreground-only agent commands): the harness moved
the deploy to the background after Claude Code's 120 s Bash timeout, then
killed it when the agent's turn ended, so the apply still held the Terraform
state lock when the verifier ran. Turn counts here are the transcript's
`num_turns`.

## Amendment 34 promotion run — 2026-09-09 (tier 0.5 retired; TestState live check)

`jobs/amend34-promotion/2026-09-09__21-19-05`; claude-sonnet-5, k=1, both
trials read-only on `anchor`, 3 min 14 s wall, zero exceptions.

| scenario | arm | reward | output tok | turns | cost $ | tier-1 | live_check |
|---|---|---:|---:|---:|---:|:---:|:---:|
| sfn-jsonata | awscdk | 1.0 | 6,040 | 26 | 0.37 | PASS | pass |
| sfn-jsonata | hcl_raw | 1.0 | 3,360 | 7 | 0.13 | PASS | pass |

The broken `jsonata-expression-correctness` fixture, run live from the host in
the hcl-raw image, scored `fail_stale` on both CheckBudget threshold cases.

## Amendment 38 promotion run — 2026-09-10 (foreground-only agent commands)

`jobs/amend38-promotion/2026-09-10__00-41-59`; claude-sonnet-5, k=1, one
mutating trial on `anchor-3`, 55 min 05 s wall including a 9 min 51 s reset.

| scenario | arm | shard | reward | output tok | turns | cost $ | live_check | idempotence |
|---|---|---|---:|---:|---:|---:|:---:|:---:|
| named-resource-replacement | terraconstructs | anchor-3 | 1.0 | 16,796 | 47 | 0.97 | pass | converged |

No command was moved to the background. The agent's own 10 min deploy
timeout returned in the foreground (`Exit code 143 Command timed out after
10m 0s`); it then ran the deploy under `nohup`, polled the log inside its
turn, read `Still destroying... 15m05s elapsed`, added `createBeforeDestroy`
and redeployed to `Apply complete`. The first attempt
(`jobs/amend38-promotion/2026-09-09__23-57-37`) is `invalid-infra`: Harbor's
`FORCE_AUTO_BACKGROUND_TASKS`/`ENABLE_BACKGROUND_TASKS` are not read by Claude
Code 2.1.266, so the deploy was still backgrounded at 900 s and killed at turn
end.

## Amendment 37 promotion run — 2026-09-10 (teardown tier, non-gating)

`jobs/amend37-promotion/2026-09-10__02-53-43`; claude-sonnet-5, k=1, the three
arms of `named-resource-replacement` on their shards concurrently, 47 min 03 s
wall. The tier ran after the live check and idempotence on every arm and
destroyed what the agent deployed; every reset afterwards found an already
empty stack and finished in about 4 min instead of 10.

| scenario | arm | shard | reward | output tok | turns | cost $ | live_check | idempotence | teardown |
|---|---|---|---:|---:|---:|---:|:---:|:---:|:---:|
| named-resource-replacement | awscdk | anchor-1 | 1.0 | 3,393 | 10 | 0.15 | pass | converged | clean |
| named-resource-replacement | hcl_raw | anchor-2 | 1.0 | 3,144 | 9 | 0.21 | pass | converged | clean |
| named-resource-replacement | terraconstructs | anchor-3 | 1.0 | 12,148 | 32 | 0.59 | pass | converged | clean |

`awscdk`'s completion line `✅  ScenarioStack: destroyed` is now measured
against the arm's pinned CLI; `teardown.log` on the Terraform arms ends in
`Destroy complete! Resources: 4 destroyed` (hcl_raw) and `6 destroyed`
(terraconstructs).

## Amendment 41 promotion run — 2026-09-17 (first gating teardown)

`jobs/amend41-promotion/2026-09-17__12-33-18` (awscdk, hcl_raw) and
`2026-09-17__13-00-13` (terraconstructs, rerun after the arm image lost its
HashiCorp apt source; the first attempt was `invalid-infra`, Harbor's
`apt-get update` failed on a rotated signing key before the agent ran);
claude-sonnet-5, k=1, `ecr-repo-destroy-force-delete` on its shards. Reference
half of the criterion:

| scenario | arm | shard | reward | output tok | turns | live_check | teardown |
|---|---|---|---:|---:|---:|:---:|:---:|
| ecr-repo-destroy-force-delete | awscdk | anchor-2 | 1.0 | 3,542 | 22 | pass | clean |
| ecr-repo-destroy-force-delete | hcl_raw | anchor-3 | 1.0 | 2,036 | 14 | pass | clean |
| ecr-repo-destroy-force-delete | terraconstructs | anchor-1 | 1.0 | 3,282 | 26 | pass | clean |

The live check pushed its probe image (`verifier-probe`) into every deployed
repository and told it apart from the CDK bootstrap repository by scan-on-push;
`ecr:GetRegistryScanningConfiguration` reports `BASIC` with zero rules on all
three shard accounts, so repository-level scan-on-push is unambiguous there.
`awscdk`'s `teardown.log` ends in `✅  ScenarioStack: destroyed` for this stack
shape; the Terraform arms end in `Destroy complete! Resources: 2 destroyed`.

Broken half (`2026-09-17__13-15-33`): the hcl_raw
`repository-not-emptied-on-delete` fixture, applied through Harbor's oracle
agent with a temporary solve.sh that runs `terraform apply` (not committed;
the hand-authored file was restored afterwards), on anchor-3:

| fixture | arm | static | live_check | teardown | reward |
|---|---|:---:|:---:|:---:|---:|
| repository-not-emptied-on-delete | hcl_raw | tier0_pass=1 | pass | destroy_failed (exit 1) | 0.0 |

`teardown.log` carries the provider's own message: `ECR Repository
(service-image-registry) not empty, consider using force_delete`. Every static
tier and the live check passed this fixture, and only the teardown tier cost it
the reward, which is the split Amendment 41 predicted. The oracle-agent route
does not work for a mutating scenario as shipped: a hand-authored solve.sh runs
`bash tests/static_tiers.sh` from a working directory that has no `tests/` in a
trial, and it never applies, so the reference half used the real agent.

## Amendment 43 promotion run — 2026-09-21 (the Python tier-0 driver)

`jobs/amend43-promotion/2026-09-21__00-34-05`; claude-sonnet-5, k=1, the three
arms of `ecs-swappiness` on `anchor`, read-only (no live check, no teardown).
The trial the driver had to be graded by:

| scenario | arm | shard | reward | output tok | turns | tier0 | tier1 |
|---|---|---|---:|---:|---:|:---:|:---:|
| ecs-swappiness | awscdk | anchor | 1.0 | 3,654 | 15 | pass | PASS |
| ecs-swappiness | hcl_raw | anchor | 0.0 | 1,182 | 6 | pass | FAIL |
| ecs-swappiness | terraconstructs | anchor | 1.0 | 6,408 | 28 | pass | PASS |

`awscdk`'s counts are the Claude Code transcript's own
(`agent/claude-code.txt`: `output_tokens` 3654, `num_turns` 15, cost 0.27437);
that trial has no `agent/trajectory.json` and `result.json` carries null token
counts, because Harbor's ATIF conversion failed validation on a `step_id` gap
(`trial.log`: `steps[16].step_id: expected 17 … got 18`).
`gates/emit_result.py` VOIDS that row — `invalid-infra`, kind
`audit-unavailable` — before its own transcript-recovery path can price it; the
other two rows come out `valid`, with `n_llm_calls` 6 and 28 matching the
transcripts' `num_turns`.

`hcl_raw`'s 0.0 is the scenario's planted `swappiness-requires-maxswap` catch
firing at tier 1, exactly where `specs/ecs-swappiness.yaml` predicts it for this
arm (`hcl: "1"`). The agent wrote `linuxParameters = { swappiness = 42 }` with
no `maxSwap`, and `opa eval` on the reconstructed `plan.json` denies with:
`aws_ecs_task_definition.app: container "app" sets linuxParameters.swappiness
but no linuxParameters.maxSwap -- AWS ECS silently ignores swappiness without
maxSwap, so the tuned value has no effect`. Tier 0 passed on all three arms.

Parity half: each workspace was reconstructed offline from its
`agent/agent-output.txt` (the `_run_solve` sandbox, `gates/aws_stub.py`, no AWS
call), and the graded artifact — `cdk.out/ScenarioStack.template.json`,
`plan.json`, `cdktf.out/stacks/ecs-swappiness/plan.json` — regraded by both
drivers:

| arm | assert | bash | driver | identical |
|---|---|:---:|:---:|:---:|
| awscdk | taskdef-exists | PASS | PASS | yes |
| awscdk | taskdef-ec2-compatible | PASS | PASS | yes |
| awscdk | swappiness-value-correct | PASS | PASS | yes |
| hcl_raw | taskdef-exists | PASS | PASS | yes |
| hcl_raw | taskdef-ec2-compatible | PASS | PASS | yes |
| hcl_raw | swappiness-value-correct | PASS | PASS | yes |
| terraconstructs | taskdef-exists | PASS | PASS | yes |
| terraconstructs | taskdef-ec2-compatible | PASS | PASS | yes |
| terraconstructs | swappiness-value-correct | PASS | PASS | yes |

`tier0_pass=1` under both columns on all three arms, and each reconstruction's
`== tier-0 … ==` through `== summary: … ==` block diffs clean against the
trial's own `verifier/test-stdout.txt`. The bash column is the retired
`assert_check`, recovered from `3ce3f12:generator/gen.py` with the
`assert_check` call lines from that revision's `tests/static_tiers.sh` — never
from the working tree.
