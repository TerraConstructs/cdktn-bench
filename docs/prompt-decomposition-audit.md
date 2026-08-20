# Prompt-decomposition audit — no foreshadowing in a first-step prompt

> ## ⚠ POINT-IN-TIME AUDIT (2026-08-20)
>
> This is the **audit record** for the six instruction bodies that existed on
> the date in the title — the evidence behind `DECISIONS.md` **Amendment 27**,
> including verbatim quotes of the offending sentences and the falsification of
> the test that now guards them. The findings are settled and the fixes shipped.
>
> Two things follow from that:
>
> - **It is not a running inventory.** Specs added after 2026-08-20 are not
>   covered here. A new spec is audited against the *rule*, not against this
>   table; the rule and the procedure live in `docs/adding-scenarios.md` §6.4
>   and §1 item 2b.
> - **The authority is Amendment 27**, plus `specs/SCHEMA.md` §2.6/§0.1 for the
>   spec surface. Where this doc and those disagree, they win.
>
> The one finding worth carrying forward verbatim is §6.1's: the
> no-foreshadowing check has **two surfaces, not one** — the step-1 prompt and
> everything under `environment/`. Auditing only the prompt is how a leak
> shipped. Amendment 28 §3 rule 7 later widened that same lesson again, to
> *every byte the Dockerfile `COPY`s*.

**Date:** 2026-08-20
**Scope:** every spec under `specs/` plus the generator-testing fixture
`specs/_toy/toy-ssm-parameter.yaml` (6 instruction bodies in total).
**Trigger (operator directive, verbatim):** *"extend the trial to allow multi
step first - we also need a pass on the existing scenarios to break down the
prompts (no foreshadowing, first step prompt should not know the future)"*.
**Companion records:** `DECISIONS.md` Amendment 26 (multi-step semantics,
draft) and Amendment 27 (the scenario-form change this audit motivates);
`docs/design/multistep-trial-investigation.md` §5 (task-dir shape and the
`tests/` visibility hole).

---

## 0. The rule this audit applies

A benchmark scenario whose prompt says *"build X, **then** change it to Y"* is
not measuring day-2 iteration. It is measuring day-1 authoring **with perfect
foreknowledge**, which is the one condition a real day-2 change never has. An
agent told about Y up front can (and a good one will) design X so that Y is
trivial — or skip the intermediate state entirely and author the final shape in
one pass. Either way the trap that only fires on a *second* apply against an
*existing* deployment never fires at all.

`docs/scenario-grades/2026-08-20-summary.md` records the operator's own framing
of why this matters, from the scenario-grading pass:

> Needed when the *second intent must not be visible at step one* (else the
> agent avoids the trap by planning ahead) [...] `sg-inline-vs-standalone-rules`
> (step 1 wants inline rules → deploy; step 2 adds a rule as a separate
> resource → deploy; **revealing both upfront defeats the trap**)

**Classification used below**

| Class | Meaning | Action |
|---|---|---|
| **(a)** | Genuinely single-step. No future intent revealed. | Stays single-step, byte-identical output. |
| **(b)** | **Foreshadowing.** A later ("day 2") change is revealed in the initial prompt. | Decompose into `[[steps]]`. |
| **(c)** | Better served by a poisoned workspace (brownfield seed + change-request prompt). | Classify only — task #15, out of scope here. |

**Strictness rule applied.** Any *"then modify / then update / then add X"*
construction in a first prompt is foreshadowing, full stop. Realistic day-1
context that does **not** name a specific future change (e.g. "this API will
evolve", "other teams will consume this") is acceptable — *realism is fine,
prophecy is not*. None of the six specs contains the acceptable-realism form;
the distinction is recorded so a future spec author has the line drawn.

---

## 1. Verdict table

| Spec | Live? | Class | Verdict |
|---|---|---|---|
| `specs/apigw-openapi.yaml` | no | **(a)** | Single-step. No future change named. |
| `specs/apigw-redeploy.yaml` | **yes** | **(b)** | **DECOMPOSED** — 2 steps. Pilot. |
| `specs/ecs-swappiness.yaml` | no | **(a)** | Single-step. Explicitly definition-only. |
| `specs/s3-lambda-log-retention.yaml` | no | **(a)** | Single-step. Three create-only clauses. |
| `specs/sfn-jsonata.yaml` | no | **(a)** | Single-step. One state machine, one authoring pass. |
| `specs/_toy/toy-ssm-parameter.yaml` | no | **(a)** | Single-step. Generator fixture, deliberately boring. |

**One offender out of six.** Five specs' generated task directories are
byte-identical to `HEAD` after this slice (proven in §5).

---

## 2. Class (b) — `apigw-redeploy`: the evidence

`specs/apigw-redeploy.yaml` `instruction.shared_body` is a single prompt that
narrates *both* days. Four separate leaks, quoted verbatim from the spec as it
stood before this slice (`git show HEAD:specs/apigw-redeploy.yaml`):

### Leak 1 — the task's own opening sentence announces the change

> "Build a REST API on Amazon API Gateway, deploy it for REAL to this AWS
> account, confirm it serves, **apply a prescribed configuration change, and
> re-deploy it** -- all inside this one task."
> — `specs/apigw-redeploy.yaml` L52-54 (`shared_body` opening paragraph)

### Leak 2 — the "Step 2" paragraph specifies the day-2 change in full

> "**Step 2 -- apply the prescribed modification and re-deploy: add ONE more
> route, `GET /status`, using a MOCK integration (no Lambda) whose response is
> the fixed JSON body `{"status": "ok", "routes": 3}` for every request.**
> Re-run your toolchain's real deploy command so the SAME stage (`prod`, same
> REST API) now serves this new route too."
> — `specs/apigw-redeploy.yaml` L66-70

This is the worst of the four: the entire second intent — route, integration
type, and the exact response body the step-2 oracle asserts on — is delivered
before the agent writes a single line of revision 1. An agent that reads this
authors the three-route API in one pass and never performs a second deploy at
all, which is precisely the loop the scenario exists to measure
(`docs/apigw-redeploy-mechanics.md` §6(c)).

### Leak 3 — the trap is *named* (answer-key leakage, not merely foreshadowing)

> "A second deploy that does not actually create a new, live-serving deployment
> behind the stage -- so the stage keeps serving stale content despite your
> deploy command exiting successfully -- **is exactly the mistake this task
> exists to test for**; make sure your redeploy genuinely takes effect, not just
> that the command you ran returned success."
> — `specs/apigw-redeploy.yaml` L76-81

Independent of the multi-step question, this paragraph hands the agent the
catch. `stale-deployment-no-triggers` and `triggers-incomplete-hash` are the two
catches this scenario is built on; a prompt that says "the mistake is X, don't
make X" measures instruction-following, not the abstraction's ability to prevent
X by construction. It is deleted, not relocated — **neither** step's instruction
carries it in the decomposed form.

### Leak 4 — the awscdk `language_line` names `MockIntegration`

> "Author this as an AWS CDK (TypeScript) app using aws-cdk-lib L2 constructs
> (apigateway.RestApi, LambdaIntegration, **MockIntegration**). Deploy for real
> with `npx cdk deploy`."
> — `specs/apigw-redeploy.yaml` L105 (`per_arm.awscdk.language_line`)

A subtle one, and the reason the schema needed **per-step, per-arm** language
lines rather than one spec-level line reused by every step: the arm-specific
construct hint for the *day-2* integration type leaks into the *day-1* prompt on
exactly one arm. Left unfixed it would also have been an **arm-parity** defect —
awscdk's step-1 agent would learn a mock integration is coming while the hcl-raw
and terraconstructs agents would not.

### Leak 5 (bonus, non-foreshadowing) — the JSON-contract fence

> "Write `/logs/agent/agent-output.json` (see the JSON contract below) recording
> the deployed stage's real invoke URL, so it can be independently re-checked
> afterward." — L83-85

Not foreshadowing (nothing about the future change), and it is required by
*both* steps' live checks, so it is carried into both step instructions
unchanged.

### The decomposition

| | Step `01-initial-deploy` | Step `02-change-request` |
|---|---|---|
| Prompt knows about | a 2-route API (`GET /hello`, `GET /version`), deploy to stage `prod`, confirm both serve | a 3rd route `GET /status`, MOCK integration, fixed JSON body, re-deploy the SAME stage, no regression |
| Prompt does **not** know about | anything in the step-2 column — no "you will later", no "this will change" | — |
| Oracle (`steps/<n>/tests/`) | `rest-api-exists`, `deployment-exists`, `lambda-function-exists`, `proxy-integration-wired`, `deployment-triggers-present`, `deployment-depends-on-all-methods` + a 2-route live check | the **full** tier suite (all 7 asserts incl. `mock-integration-wired`) + the current 3-route live check |
| `min_reward` | `1.0` — hard gate (Amendment 26 §3) | unset (last step) |

**Why the step names are generic.** `01-initial-deploy` / `02-change-request`,
not `02-add-status-route`. Step names live in `task.toml` and on disk — host-side
only, never uploaded to the agent's container — but a name that spells out the
day-2 change is one stray log line or future feature away from being a leak, and
costs nothing to avoid.

`mock-integration-wired`'s own `description` in the spec reads *"backing the
day-2 /status route -- proves the prescribed modification is present"*. It is
therefore **step-2-only oracle text by construction** and lives exclusively in
`steps/02-change-request/tests/`, never in the shared root `tests/` (memo §5
generator rule 1).

---

## 3. The design call: who deploys the prior step's work?

`DECISIONS.md` Amendment 26 §2 makes the harness the **default** deployer
(`steps/<name>/pre_invoke/pre_invoke.sh` runs `terraform apply` / `cdk deploy`
of the previous step's IaC with staged credentials) and explicitly allows a spec
to **opt into agent-deploys** where the deploy loop is itself the measurement.

**`apigw-redeploy` opts into agent-deploys in BOTH steps. Step 02 declares no
`pre_invoke` at all.** Justification:

1. **The deploy loop IS the measurement.** This scenario's headline catch,
   `triggers-incomplete-hash`, is `predicted_tier_caught: "live"` *by
   construction*: "catching this requires comparing the triggers hash ACROSS TWO
   REVISIONS, which no single-artifact static tier can express"
   (`specs/apigw-redeploy.yaml`, catch description). The discriminating event is
   *the agent's own second `terraform apply` producing no new deployment*. If
   the harness ran the apply, the harness — not the agent — would own the exact
   action under measurement, and an agent whose config is missing `triggers`
   would be indistinguishable from one whose config is correct: both would have
   "a deploy that the harness ran".
2. **It preserves the single-step pilot's construct.** The already-recorded live
   green (Amendment 23: `apigw-redeploy-hcl-raw`, reward 1.0, 49 turns, 45,535
   output tokens) measured an agent-driven `apply → curl → modify → apply →
   curl` loop. Keeping the agent as deployer means the *only* thing this slice
   changes is when the second intent is revealed — the cleanest possible
   comparison for the operator to read.
3. **Agent-side deploy failures should count against the agent here.** That is
   the stated consequence of the opt-in in Amendment 26 §2, and it is correct
   for a scenario whose instruction explicitly says "Actually run your
   toolchain's real deploy command against this account (not just synth/plan)".

**Workspace carry-over — verified, not assumed.** The opt-in only works if
step 2's agent finds step 1's files still on disk. It does:

- `MultiStepTrial._run` (`harbor/trial/multi_step.py`) iterates every step and
  calls `_stop_agent_environment()` **once, after the loop** — the container and
  its filesystem survive every step boundary.
- `_prepare_step` (`multi_step.py`) only uploads `steps/<name>/workdir/` **if
  that directory exists**, and runs `setup.sh` only if it exists
  (`_upload_step_workdir` / `_run_step_setup`). The generator emits neither for
  `apigw-redeploy`, so nothing overwrites `/app/project` between steps.
- Only `/logs/agent` is relocated between steps
  (`_archive_step_outputs` → `ArtifactHandler.move_dir_contents`), which is what
  gives each step clean per-step token attribution (Amendment 26 §1/§4). The
  workspace is untouched by that move.
- The one call to `_stop_agent_environment` that *is* inside `_run_step` fires
  only for a **separate-environment verifier on the last step** — which
  `cdktn_bench/trial.py::validate_multi_step_layout` refuses outright, per step
  (aws-bench's phase scripts run in the agent container).
- All three properties are pinned against the *installed* rev by
  `generator/tests/test_multistep_emission.py::test_harbor_still_keeps_one_container_across_steps`
  (source-level: exercising them for real needs a docker daemon and an AWS
  account), and the "no `workdir/`, no `pre_invoke/`" half by
  `::test_apigw_redeploy_emits_no_pre_invoke`. An aws-bench/harbor pin bump
  that changed any of them fails there rather than at the next live run.

So step 2's agent opens a workspace that already contains its own revision-1
`main.tf` / `lib/scenario-stack.ts` and, on the TF-shaped arms, the
`terraform.tfstate` its own step-1 apply wrote. **No `pre_invoke` is needed and
none is emitted.** (The `-refresh=false` handling that residual state requires
was already in place — `gates/tests/test_apigw_redeploy_offline_state.py`, B3
fix — and is unchanged by this slice.)

Amendment 26 §1's consequence is respected: because sessions are fresh per step,
step 2's instruction is **self-contained** and never says "what you just built".
It re-states the API name, the stage, and the existing routes as *observable
facts about the workspace*, not as recall.

---

## 4. Class (a) — the five specs that stay single-step

Each was read in full (`shared_body` **and** every `per_arm.<arm>.language_line`)
and searched for a named future change.

### `specs/apigw-openapi.yaml` — (a)

Every clause is one authoring pass against a seeded, read-only OpenAPI document:

> "Implement an Amazon API Gateway REST API that provides every route the
> specification describes [...] For each route, create a Lambda function to
> handle it and wire a Lambda proxy integration from that route to its function
> [...] Deploy the API to a stage so all three routes are reachable."

No second revision, no "then". Its `deployment-missing-integration-dependency`
catch is a *structural* fact about a single synthesized artifact, so it needs no
second apply to fire. **Note for a future author:** this spec is the static
sibling of `apigw-redeploy` and shares a catch name; it must stay single-step
precisely so the pair isolates "structural dependency edge" (static, here) from
"redeploy actually took effect" (live, there).

### `specs/ecs-swappiness.yaml` — (a)

> "This is a definition-only task: nothing needs to be deployed, started, or
> attached to a cluster or service."

Explicitly terminal. Nothing to iterate on.

### `specs/s3-lambda-log-retention.yaml` — (a)

Three create-only clauses ("Create a new S3 bucket", "Create a new AWS Lambda
function", "Ensure the Lambda function's logs are retained for 10 days"). The
third is a property of the resource being created in the same pass, not a
subsequent change to a deployed resource — no `then` construction, no revision 2.

### `specs/sfn-jsonata.yaml` — (a)

One state machine, authored once. The `QueryLanguage: JSONata` clause is a
constraint on how the single artifact is written, not a later migration of an
existing one.

> **Class (c) candidate, recorded not acted on:** a *JSONPath → JSONata
> migration* variant of this scenario — poisoned workspace seeded with a working
> classic-JSONPath state machine, prompt = "migrate this to JSONata" — is a
> genuinely different and probably stronger measurement than greenfield
> authoring, and needs **no** multi-step machinery (the second `plan` is the
> oracle, not a second prompt). Filed under task #15; see
> `docs/design/poisoned-workspace-design.md`. The current greenfield spec is
> untouched.

### `specs/_toy/toy-ssm-parameter.yaml` — (a)

Generator-testing fixture (SCHEMA.md §7: "Never register it as a benchmark
scenario"). Two create-only clauses; deliberately boring so a generator bug
reads as a generator bug. It also serves as this slice's **regression control**:
it exercises the 3-arm generator path and must emit byte-identically.

---

## 5. Class (c) — poisoned-workspace notes (classification only)

No existing spec is *better served* by a poisoned workspace than by its current
form; the notes below are recorded so task #15 inherits them.

1. **`sfn-jsonata` migration variant** — see §4 above. The strongest class-(c)
   candidate in the current set.
2. **`apigw-redeploy` step 1 — considered and rejected.** A poisoned workspace
   could replace step 1 entirely (seed an already-authored 2-route API, prompt
   only the `/status` change), which would be cheaper: one prompt, one deploy.
   Rejected for two reasons. (i) *It changes what is measured.* Step 1's
   authoring cost is a real addend of `tokens-to-green-across-steps`
   (Amendment 26 §4); a seeded workspace erases it and, worse, erases the
   **arm-specific** part of it — the whole point of a 3-arm comparison is that
   each arm authors revision 1 in its own idiom, and a seeded revision 1 would
   have to be hand-written per arm anyway (i.e. the operator, not the agent,
   would be choosing how idiomatic each arm's starting point is — a direct
   thumb on the scale). (ii) *It needs pre-deployed live state, not just code.*
   The trap fires on a second apply against an existing **deployment**, so a
   seeded workspace would additionally need the harness to deploy it —
   re-introducing the harness-deploys shape §3 rejects, plus a `terraform.tfstate`
   the harness would have to hand the agent. The graded-scenario summary already
   flags this class ("needs pre-deployed *state*, not just code — heavier").
3. **General rule extracted for task #15:** poisoned-workspace replaces a step
   whose authoring cost is *not* part of the measurement. Where step 1's
   authoring cost **is** an addend of the headline metric, multi-step is the
   correct instrument and poisoned-workspace is a measurement change, not an
   optimisation.

---

## 6. Hostile re-read of the emitted step-1 prompts

Required self-check: *would an agent seeing only `steps/01-*/instruction.md` and
the workspace have any hint of step 2's intent?*

Checked against the generated files (all three arms), for the pilot:

| Probe | Result |
|---|---|
| Word "status" anywhere in a step-1 instruction | absent |
| Word "mock"/"MockIntegration" anywhere in a step-1 instruction | absent |
| Words "later", "step 2", "afterwards", "will change", "for now", "change request", "modification" | absent |
| "re-deploy"/"redeploy" | absent **except** inside the API's own required name `apigw-redeploy-api` (once per prompt, verified by `grep -io 'redeploy[a-z-]*'` → only `redeploy-api`) — see the accepted-residual note below |
| Route count stated | "two routes" — true and terminal, no "for now" |
| `{"status": "ok", "routes": 3}` (the step-2 oracle's expected body) | absent |
| The trap paragraph (Leak 3) | absent from **both** steps |
| Step-1 workspace (`environment/`) contains step-2 material | **no, after a fix** — this row originally claimed "the workspace is the arm's empty skeleton, identical to every other spec's". That was **wrong**: the skeleton header is `spec.title`-interpolated, so it is *not* identical across specs, and this spec's whole-arc title leaked. See §6.1. |
| Shared root `tests/` contains any oracle material | no — a single `README.md` explaining the rule; every oracle lives in `steps/<name>/tests/` |
| `/tests` during step-1's agent phase | **empty** — Harbor uploads test sources inside `Verifier.verify()`, which runs *after* that step's agent (`harbor/verifier/verifier.py`); `MultiStepTrial._reset_shared_step_verifier_dirs` then empties `/tests` at the start of each later step's verification |

The mechanical version of this table is
`generator/tests/test_multistep_emission.py`, whose
`test_step_one_instruction_leaks_nothing_about_step_two` /
`test_step_one_environment_leaks_nothing_about_step_two` /
`test_step_one_oracle_leaks_nothing_about_step_two` /
`test_shared_root_tests_holds_no_oracle` grep the real generated files for two
deny-lists, so a future spec edit that reintroduces foreshadowing turns the
generator suite red rather than shipping. The lists are split by scope:

- **CONTENT tokens** (`/status`, `mock integration`, `"routes": 3`, the exact
  body) name step 2's substance. Banned in the step-1 prompt, in step 1's own
  `tests/`, in the shared `tests/`, and in `environment/`.
- **TEMPORAL tokens** (`later`, `step 2`, `re-deploy`, `change request`,
  `for now`, `revision 2`, `day-2`, `iteration`, …) are the grammar of
  foreshadowing. Banned in the **prompt** and in **`environment/`** — the two
  things the step-1 agent actually reads — and permitted in generator/meta
  commentary, which the agent never sees: a `tests/README.md` saying "readable
  by a later step's agent" documents Harbor's upload ordering, it does not hint
  at the task.

### 6.1 Leak found and fixed after the first hostile read: the scenario title in `environment/`

The original version of the table above asserted the workspace was clean. It
was not, and the claim was made without a scan. What a verifier found:

`generator/gen.py` interpolated `spec.title` into **five** skeleton headers —
`awscdk_stack_skeleton()` (`lib/scenario-stack.ts`), `awscdk_bin_app_ts()` (the
CloudFormation stack `description:`, which also lands in the synthesized
template), `hcl_raw_main_tf()` (`main.tf` line 1),
`terraconstructs_main_ts()` and `terraconstructs_stack_skeleton()`. This spec's
`title` is *"API Gateway REST API: deploy, confirm, modify, re-deploy (day-2
iteration)"*. So the first line of the very file the step-1 prompt says the
agent owns read:

```
# API Gateway REST API: deploy, confirm, modify, re-deploy (day-2 iteration)
```

and each arm's Dockerfile `COPY`s that into the agent image
(`COPY workspace/main.tf ./main.tf`; `COPY workspace/bin ./bin` +
`COPY workspace/lib ./lib`; `COPY app/main.ts ./main.ts` + `COPY app/lib ./lib`),
so it reached the container, not merely the host. The step-1 prompt was clean
and the leak still shipped — an agent reading "modify, re-deploy (day-2
iteration)" anticipates a second apply, which is exactly the anticipation the
redeploy-trigger trap exists to defeat. Amendment 26 §7 rule 2 /
`docs/design/multistep-trial-investigation.md` §5 rule 2 forbid precisely this:
*never place later-step material in `environment/` — that IS the image the
agent lives in.*

**Root cause, generalised:** `environment/` was treated as metadata-free
scaffolding, so no rule and no test covered it, while the *prompt* had both.
The one field that flows from the spec into the skeleton is the field that
describes the whole arc.

**Fix (three parts, so it cannot recur silently):**

1. **Schema** — new optional top-level `workspace_title` (`specs/SCHEMA.md`
   §0.1). It is the header stamped into the skeletons; `title` stays the
   registry/`task.toml` metadata (host-side, never uploaded). It is **required**
   on a multi-step spec and **forbidden** on a stepless one
   (`Spec._multi_step_requires_workspace_title`, `generator/spec_model.py`).
   Required rather than defaulted, so the author must *choose* a step-1-safe
   header instead of inheriting a foreshadowing one by omission; forbidden on
   stepless specs so the byte-identity guarantee for the other five specs
   cannot be traded away for a rename.

   > **Superseded 2026-08-20 (Amendment 28 §3 rule 7).** Scoping the field to
   > `steps:` turned out to be too narrow, and the narrowness was itself a leak:
   > a **stepless BROWNFIELD** spec (`workspace_seed:`, `SCHEMA.md` §2.7) has a
   > `title` that names the change — and in the pilot's case both halves of its
   > own pitfall — with no way to override the header. `workspace_title` is now
   > required on multi-step **or** brownfield specs and the validator is called
   > `Spec._workspace_title_required_where_header_is_prompt_surface`. The
   > forbidden-on-plain-greenfield half is unchanged, and so is the
   > byte-identity guarantee it protects.
2. **Generator** — the five sites now call `spec.workspace_header()`
   (`workspace_title or title`), and `specs/apigw-redeploy.yaml` declares
   `workspace_title: "API Gateway REST API (live)"` — terminal, implying no
   second change. Note "API Gateway REST API: live deploy and day-2 change
   request" would still leak; the accepted header names only what step 1 builds.
3. **Test** — `test_step_one_environment_leaks_nothing_about_step_two` runs the
   full CONTENT+TEMPORAL deny-list over *every* file under each multi-step
   task's `environment/` (excluding `package-lock.json`, machine-written), and
   `test_skeletons_use_workspace_title_not_title` pins the five emitter
   functions directly. Falsified before being trusted: re-inserting the old
   header into `main.tf` fails the test with
   `leaks step-2 intent: ['re-deploy']`. The TEMPORAL list also gained
   `day-2`/`day 2`/`day-two`/`iteration`/`subsequent`/`follow-up`/`second
   apply`, because the pre-existing list matched only *one* token of that
   four-token leak. `modify` is deliberately **not** a token: the arm skeletons
   and the step-1 ownership note both legitimately say "do not modify
   provider.tf".

One TEMPORAL hit survives in `environment/` and is allowlisted: the arm
Dockerfile comment *"for later task slices"*. It is shared arm-image text
predating every scenario, and
`test_environment_boilerplate_is_really_boilerplate` requires each allowlisted
phrase to also appear under a **stepless** spec's `environment/` — so the
allowlist cannot be used to smuggle this scenario's own words past the scan.

### Known, accepted residual: the API's own name

The step-1 prompt must say *"a REST API named EXACTLY `apigw-redeploy-api`"* —
the name is load-bearing (`live_check.py` discovers the deployed API by it on
both steps; every reference and broken fixture writes it). That name, and the
spec id in every generated file header, contain the substring **"redeploy"**.

> **[Updated 2026-08-20, Amendment 28 §10]** The second half of that sentence
> is no longer true: generated file headers no longer cite the spec id (or any
> spec filename), and the spec id is no longer stripped before deny-list scans
> — agent-visible identity now comes from `workspace_id`
> (`hello-version-api` for this scenario). The API name remains the single
> accepted residual, and `test_the_accepted_residual_is_really_prompt_content`
> now checks mechanically that it appears in step 1's own prompt.

Accepted, and stripped before the deny-list scan rather than the scan being
weakened, because: it reveals no step-2 *content* — not the route, not the
integration type, not that a second prompt is coming — and "redeploy" is
ordinary API Gateway vocabulary for a thing every API Gateway API does. The
alternative (renaming the API) would touch ~1,800 lines of hand-authored
reference and negative fixtures across three arms to remove a signal weaker
than the word "deploy" already present in the same sentence. Recorded here so
the exemption is a decision, not an oversight.

### Known, accepted residual: step-1 tests are visible in step 2

**Residual, accepted:** during **step 2's** agent phase `/tests` still holds
step 1's uploaded oracle (memo §5, Harbor's own ordering). That is a *backward*
exposure only — step 1's oracle describes a 2-route API the step-2 agent has
already built and whose existence step 2's own prompt states outright — so it
reveals nothing. It is recorded here rather than mitigated because mitigating it
(emptying `/tests` from a `pre_invoke`, memo §5 rule 4) would cost a
`pre_invoke` script this scenario otherwise does not need.

---

## 7. What the decomposition does NOT change

- **The oracle.** Every one of the 7 `structural_asserts` and both policy
  bundles survive verbatim; the final step runs the identical full tier suite,
  so `tests/static_tiers.sh`'s content for step 02 is byte-for-byte what the
  single-step task's `tests/static_tiers.sh` was.
- **Falsifiability.** The whole-scenario reference solution and every
  `solution/broken/<catch>/` fixture stay at the task root and are run by
  `gates/oracle_falsifiability.py` against the **final** step's oracle — the same
  script, the same asserts, the same expected rewards. A new, additional
  obligation is added (each non-final step needs its own reference solution
  scoring 1.0 against its own oracle), which is strictly more proof, not less.
- **The five class-(a) specs.** Byte-identical task directories.

## 8. What it DOES change, that a reader of old results must know

The single-step and multi-step forms of `apigw-redeploy` are **different
scenarios**. The three-arm live results of 2026-08-13 (`docs/live-results.md`:
awscdk 9,403 / terraconstructs 24,218 / hcl-raw 45,535 output tokens, all
reward 1.0) were produced under the **single-step** form. They remain valid as
pilot evidence *for that form* and must not be pooled with any multi-step-form
result. See `DECISIONS.md` Amendment 27 for the pre-registered statement of that
rule.
