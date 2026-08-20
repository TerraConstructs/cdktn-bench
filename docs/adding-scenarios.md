# Adding scenarios and tasks

A practical, step-by-step guide for adding a new scenario (or a new task
variant of an existing one) to this benchmark. Companion reading:
`specs/SCHEMA.md` (the full field-by-field spec contract this doc assumes
you have open alongside it), `specs/_toy/toy-ssm-parameter.yaml` (a worked
example exercising every field at minimum cardinality), and `DECISIONS.md`
(the amendment log — several of the rules below exist because an earlier
version of this repo got them wrong and had to fix them; the amendment
entries cited are the "why," not just the "what").

This doc lives at `docs/adding-scenarios.md` rather than as a new section of
`specs/SCHEMA.md` because `SCHEMA.md` is a field-by-field *reference*
(what each key means, its type, its default) — this doc is a *procedure*
(what order to do things in, which command to run, what to do when a
scenario needs something the current setup doesn't grant). Keeping them
separate means `SCHEMA.md` stays skimmable as a reference and this doc stays
skimmable as a checklist; cross-linked from both directions (`SCHEMA.md`'s
`agent_role_name`/`concurrency_mode` entries in §5 point here, and every
section below cites the exact `SCHEMA.md` section it expands on).

**Three scenario forms exist** — greenfield single-step, **multi-step**
(`steps:`, §6.4) and **brownfield** (`workspace_seed:`, §6.5) — and they
compose. §1 item 2b is the decision point; §8 is the rule about which
resulting rows may be pooled. If you are adding a plain single-step greenfield
scenario you can read §§1–7 and skip §6.4/§6.5, but read §1 item 2b first to
be sure that is what you have.

---

## 1. Author the intent spec

One new file: `specs/<scenario-id>.yaml`, `<scenario-id>` kebab-case,
matching the filename stem (the generator enforces this at load time —
`specs/SCHEMA.md` §0). Copy `specs/_toy/toy-ssm-parameter.yaml` as a
starting skeleton — it's deliberately boring (a create-only SSM parameter
plus a scoped-read IAM role) so its own structure, not its subject matter,
is what you're supposed to copy.

Fill in, in this order (each corresponds to a `SCHEMA.md` section):

1. **Top-level shape** (`id`, `title`, `difficulty` 1-3, `services`) —
   `SCHEMA.md` §0.
2. **`arms`** — `awscdk`/`hcl_raw` are always `true`; decide
   `terraconstructs.enabled` by checking real coverage against
   `arms/terraconstructs/README.md` §3/§4 (grep the actual
   `node_modules/terraconstructs/lib/aws/<service>/` tree if the README
   table doesn't answer it directly — that's how `apigw-redeploy`'s own
   `arms.terraconstructs.reason` was verified, see that spec's own comment
   block). A `reason` that isn't independently checkable against the arm's
   own README fails review — `SCHEMA.md` §1.
2b. **Which scenario FORM is it?** Three forms exist, and the choice is made
   here, before any prose is written, because each one changes what the
   scenario measures and which metric stratum its rows land in:

   | Form | Spec trigger | Starts from | Measures |
   |---|---|---|---|
   | greenfield single-step | *(neither key)* | empty `entry_file` skeleton (§2.4) | day-1 authoring |
   | **multi-step** | `steps:` (§2.6) | empty skeleton, N prompts | day-2 iteration *without foreknowledge* |
   | **brownfield** | `workspace_seed:` (§2.7) | hand-authored, plan-green, already-deployed config | a change to code the agent did not write |

   The forms compose (a spec may be both), and **rows from different forms are
   never pooled** — see §8 below.

   *Does it need `steps:`?* Ask: *does this scenario's prompt describe more
   than one point in time?* If it says "build X, then change it to Y", or
   "deploy it and then …", it is a **multi-step** scenario and must be
   decomposed (`SCHEMA.md` §2.6, DECISIONS.md Amendments 26/27). A single
   prompt narrating both days measures day-1 authoring with perfect
   foreknowledge, which is the one condition a real day-2 change never has —
   the agent designs X so Y is trivial, or authors the final shape in one pass,
   and a trap that only fires on a *second* apply never fires at all.
   `docs/prompt-decomposition-audit.md` is the worked audit of the six specs
   that existed on 2026-08-20 against that rule — a point-in-time record, not a
   running inventory, but the best worked example of how the judgement is made,
   including the four separate leaks the one offender had. Realistic day-1
   context that names no specific future change ("this API will evolve") is
   fine: **realism is fine, prophecy is not.**

   The full multi-step procedure is §6.4; the full brownfield procedure is
   §6.5. Two rules belong here, though, because they constrain the very first
   lines you type:

   **(i) `workspace_title` — required on a multi-step OR brownfield spec**
   (`SCHEMA.md` §0.1; Amendment 27 §5.1, widened by Amendment 28 §3 rule 7).
   It replaces `title` as the header stamped into each arm's skeleton entry
   file under `environment/`, which the arm Dockerfile copies into the agent
   image. A multi-step `title` describes the whole *arc*; put it in the
   skeleton and step 1's agent reads the day-2 plan on line 1 of its own
   `main.tf` — which is exactly what shipped once. A brownfield `title`
   describes the *change*, and the natural way to write it names the property
   carrying the pitfall: `"Rename an explicitly-named, in-use security group
   and roll it out"` put both halves of that scenario's poison into the awscdk
   arm's CFN description and the terraconstructs arm's `main.ts` header — and
   *not* into hcl-raw's, whose entry file is the seed itself. Arm-asymmetric
   hints do not just make a task easier, **they bias the cross-arm number**.
   So a multi-step `workspace_title` is *terminal* (only what step 1 builds,
   implying no future change); a brownfield one says only what the workspace
   already **is** ("Internal services network").

   **(ii) Separate the operator-facing identity from the agent-visible one.**
   The scenario `id` is operator-facing and **may name the pitfall** — that is
   useful for whoever reads `specs/`, `make falsifiability` output or a results
   table. The agent must never see it. Where the id would otherwise reach the
   agent (workspace/stack/module naming under `environment/`), a spec declares
   **`workspace_id`** — the agent-visible identity — exactly as
   `workspace_title` separates the agent-visible header from `title`. Same
   rule, same reason, one layer down; see `specs/SCHEMA.md` §0.1 for the field
   contract and which emitter sites consume it.

   **Where trap detail is allowed to live:** spec YAML comments, `task.toml`
   `[metadata]`, reference/negative solutions under `solution/**`, `DECISIONS.md`
   and `docs/`. All of those are host-side and are never uploaded to the agent
   environment. **Where it is forbidden:** anything under `environment/`, any
   step's `instruction.md`, and the seed itself. See §6.5 rule 2 for the
   hostile-read procedure that enforces the line.

3. **`instruction`** — one `shared_body` (identical prose across arms; the
   generator diffs it post-placeholder-substitution and fails the build if
   arms' instructions diverge outside the language line, `SCHEMA.md` §2/
   §8.2 point 2) plus one `per_arm` block per enabled arm (`language_line` +
   `output_contract`). Decide `verifier.live_check` (see §3 below) before
   writing the instruction body — a mutating scenario's instruction needs
   explicit language about whether the agent should clean up after itself
   (see `specs/apigw-redeploy.yaml`'s own instruction for the pattern: "Do
   NOT delete... leave every resource you created running").
3a. **Prompt-writing rules (the ticket test).** The `shared_body` is a
   *work request*, not a specification of the solution. Before freezing it,
   read it as if you were the engineer receiving the ticket, and apply:

   - **Write the goal the way a real ticket would.** State what the business
     needs and what "done" looks like. Nothing else.
   - **No oracle-defensive spec-ese.** Never add a constraint whose only
     purpose is to force the implementation shape your asserts happen to
     expect. `apigw-openapi`'s original prompt is the cautionary example: it
     said "each route is its own API Gateway resource and method,
     individually reachable and individually wired -- not an API whose routes
     exist only inside an imported OpenAPI document body." That sentence
     existed solely because the asserts counted per-route resources; it told
     the agent the answer and it measured nothing. **Forbidden.**
   - **Resolve alternative shapes oracle-side, not prompt-side.** If a
     competent engineer could satisfy the ticket two ways (e.g. API Gateway
     body-import vs per-route resources), you have exactly two legitimate
     options: (a) **behavioralize** the asserts so any working shape scores
     1.0, or (b) add **at most one in-world sentence** that motivates the
     shape the way a real ticket would ("the platform team needs per-route
     metrics"). Never enumerate what not to do.
   - **Never mention grading.** No "its contents are not graded", no
     "the verifier checks…", no tier vocabulary. The agent is doing a job,
     not sitting an exam.
   - **Never coach around toolchain differences.** "…if your toolchain
     requires an existing code archive rather than inline source" hands the
     hcl-raw agent the discovery that *is the measurement*: that Terraform
     makes you solve packaging yourself while CDK bundles for free. Coaching
     it away deletes the arm differential the scenario exists to measure.
   - **Seeded files: path + one line, no usage instructions.** "A `<what>` is
     at `<path>`." Stop there. What it is for is the agent's problem.

   **Seed-artifact neutrality.** A seeded input must not bias an
   implementation shape. If the artifact is the idiomatic input for exactly
   one shape — a machine-readable `openapi.json` all but *demands*
   body-import — then either that shape is oracle-accepted, or the artifact
   is replaced with a shape-neutral one (e.g. a PRD-voice markdown API design
   doc: routes, purposes, expected responses, written for a human). For every
   seeded file, state in the spec's comments **what shape it nudges toward
   and whether the oracle tolerates that shape**. A trap worth keeping is
   usually shape-invariant anyway (`apigw-redeploy`'s deployment-consistency
   trap fires under body-import *and* per-resource authoring).

   **The cost this rule buys, stated honestly.** Tolerating N shapes means
   proving the oracle in N shapes: each accepted shape needs its own
   reference solution scoring 1.0 and its own broken fixtures proving each
   catch still fires, so falsifiability cost scales with the number of
   shapes. That cost is the price of measuring authoring, not compliance.
   Where it becomes unaffordable, prefer a **behavioural** oracle (does the
   deployed thing do what the ticket asked?) over widening structural asserts
   shape by shape — see §5.

4. **`catches`** and **`oracle.structural_asserts`** — the planted-mistake
   taxonomy (prereg §5) and the tiered checks that catch them. Write
   `oracle.intent` (the natural-language ground truth) FIRST, then derive
   the structural asserts from it — not the other way around; see §5 below
   ("oracle-authoring steps") for the full sequence, which is the same
   sequence whether you're adding a whole new scenario or extending an
   existing one's catch list.
5. **`verifier`** — `budget.max_iters`, `live_check` (§3 below) and, for a
   brownfield scenario, `idempotence` (§6.5 item 7). `budget.max_iters` is the
   pre-registered feedback-cycle cap and a spec may only ever *lower* it
   (`SCHEMA.md` §5) — it is a budget, not a per-scenario knob to tune away a
   hard scenario. Note that the spec-level cap and the runner's own
   `MAX_ITERS`/`--max-turns` backstop are **different quantities**: turns are
   agent steps, not feedback cycles, and the runner default was raised
   accordingly (DECISIONS.md Amendment 22; `CLAUDE.md` "Turn budget" carries
   the monitor-and-trim rule). Do not copy one number into the other.
6. **`provenance`** — `author`, `date`, `prereg_section_refs` citing the
   specific prereg section(s) this scenario implements.

Validate as you go, before running the full generator:

```bash
make validate-spec SPEC=specs/<scenario-id>.yaml
```

This runs `generator/spec_model.py`'s pydantic model against your YAML with
no side effects — the fastest feedback loop for field-shape mistakes.

Once it validates, generate for real and check prompt parity:

```bash
make gen SPEC=specs/<scenario-id>.yaml
make parity SPEC=specs/<scenario-id>.yaml
```

`make gen` is the **only** thing allowed to write into
`tasks/<scenario-id>/{awscdk,hcl-raw,terraconstructs}/` and
`oracles/{rego,cfn-guard}/<scenario-id>/` — never hand-edit generated
output (`SCHEMA.md`'s own top-of-file rule). Files marked hand-authored in
the spec (see §5 below) are the one exception: the generator writes them
once, then never overwrites an existing one.

---

## 2. Choose the agent role

`SCHEMA.md` §5 documents the field; this is the decision procedure.

Every generated task's `task.toml [scenario] agent_role_name` names an IAM
role the agent's own AWS credentials are staged from
(`docs/slice-g-recon.md` §1 traces the exact mechanism through
`aws_bench/task/aws_trial.py` if you need the plumbing detail — not required
reading for this decision). Two roles exist today, both defined in
`scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts` — the same
two-tier model aws-bench itself uses (DECISIONS.md Amendment 24):

| Role | Grants | Use when |
|---|---|---|
| `QALocalInvocationApplicationRole` | `ReadOnlyAccess` + a handful of read-only managed policies (S3Tables, Redshift, Athena, Bedrock, a custom S3-Vectors-read policy) | The scenario's agent phase never mutates AWS — synth/plan-only, which is every scenario except the two live ones (`apigw-redeploy`, `named-resource-replacement`) as of this writing. This is the **default**: a spec that leaves `verifier.live_check.agent_role_name` unset (`null`) gets this role automatically (`generator/gen.py::build_task_toml`). |
| `QALocalInvocationApplicationAdmin` | `AdministratorAccess` + `AmazonBedrockFullAccess` | The scenario's agent phase performs **any** real AWS mutation (a live deploy/apply loop). Broad by design — this is deliberate, not a fallback. |

**The rule: read-only scenarios get the read-only role; mutating scenarios
get the admin role.** There is intentionally **no** per-scenario least-privilege
deploy role — that was tried (`QADeployApplicationRole`) and retired in
Amendment 24, because a too-tight deploy role (a) turns *harness* permission
gaps into fake *agent* failures and (b) breaks arm parity (one arm's deploy
mechanism silently getting more authority than another's). Concretely:

1. Does the scenario's agent phase ever call a mutating AWS API? If no,
   leave `agent_role_name` unset (`null`) — you get
   `QALocalInvocationApplicationRole` for free and don't need to read
   further.
2. If yes, set `agent_role_name: "QALocalInvocationApplicationAdmin"`. Both
   arms then deploy with identical (admin) authority, so a deploy failure is
   unambiguously the agent's. Safety comes from the disposable, reset,
   SCP-guarded account (region-restriction + role-protection SCPs), **not**
   from narrowing this role. Do **not** reintroduce a bespoke scoped deploy
   role per scenario.

---

## 3. Decide read-only vs. mutating

`SCHEMA.md` §5 documents `verifier.live_check` in full; this is the decision
rule.

- **Read-only (`verifier.live_check.enabled: false`, the default)**: the
  scenario is graded entirely from the FINAL delivered file — synth/plan
  output, never a real deploy. This is every scenario except the two live
  ones, `apigw-redeploy` and `named-resource-replacement`. Leave
  `verifier.live_check` at its defaults; the generator sets `[concurrency]
  mode = "read-only"` automatically, which lets trials of the shared `anchor`
  scenario co-run without a reset cycle.
- **Mutating (`verifier.live_check.enabled: true`)**: the scenario's whole
  point is a runtime fact a static artifact cannot express — e.g.
  `apigw-redeploy`'s "did the SECOND deploy actually take effect, or does
  the stage keep serving stale content", or `named-resource-replacement`'s
  "did the change actually converge, or does the plan still show pending
  work". Setting this `true` requires:
  - `verifier.live_check.hand_authored: true` and a real
    `tests/live_check.py` you write by hand (the generator's own stub is
    inert scaffolding, never overwritten once you've hand-authored the real
    file — same convention as `solution/solve.sh`).
  - `verifier.live_check.concurrency_mode: "mutating"` — this is what
    actually triggers aws-bench's post-trial scenario-account reset
    (`aws_bench/task/aws_trial.py`'s `ConcurrencyMode.MUTATING` handling).
    Forgetting this while `enabled: true` leaves deployed resources in the
    shared account after every trial — a real operational risk, not just a
    style nit.
  - Deciding `verifier.live_check.gating` (default `false`, non-gating —
    the live check's result is written to
    `/logs/verifier/live_check-result.json` for out-of-band analysis but
    never overrides `reward.txt`). Set `gating: true` only if some catch in
    your scenario is `predicted_tier_caught: "live"` by construction (every
    static tier passes it identically to a correct solution) — otherwise
    that catch can never cost a real trial any reward. `gating: true`
    folds `live_check.py`'s own `.outcome` field into `reward.txt` with AND
    semantics (fail-closed: `"fail_stale"`/`"not_verifiable"`/`"run_invalid"`
    all force reward to `0.0`) — see `SCHEMA.md` §5 for the exact contract.
  - Whether to also opt into **`verifier.idempotence`** (`SCHEMA.md` §5.1,
    Amendment 28 §4) — "after the solution is green, does the agent's own
    toolchain report a converged state against what it deployed". It is
    **live-only by necessity**, not by preference: a static tier plans an
    empty directory, and `terraform plan -detailed-exitcode` is always `2`
    against empty state, so no meaningful second-plan signal exists offline.
    `idempotence.enabled` therefore *requires* `live_check.enabled`. It is
    gating and fail-closed (both `pending_changes` and `not_verifiable`
    downgrade to `0.0`), and offline it is **skipped with a recorded reason,
    never fake-passed**. Per-arm commands are injected by the generator and
    are deliberately not a spec key — see §6.5 item 7.
  - Cleanup story: **you do not need a scenario-specific `reset/reset.sh`.**
    Two independent live proofs (`DECISIONS.md` Amendments 17/18,
    `docs/teardown-experiment-results.md`) confirmed the framework's
    generic post-trial reset (`ResourceManager.reset_scenarios` →
    `ResetManager.reset_account`, `ccapi_fallback=True`) is
    type-comprehensive and stack-membership-agnostic — it diffs the
    account against the POST_SETUP baseline across the full CFN
    resource-type registry and deletes anything new, including resources
    with CFN-random physical names a fixed-name sweep could never
    predict. `apigw-redeploy` originally shipped its own `reset.sh`
    fixed-name sweep on the (disproven) assumption that the framework had
    no delete handler for its resource types (Amendments 14/15) — that
    assumption did not hold up and the script was removed as dead code
    (Amendment 18, executed 2026-08-13). Budget the generic reset's real
    per-trial wall-clock cost (~8.5–9 minutes, dominated by two full
    account-wide fastscans, not deletion — see
    `docs/teardown-experiment-results.md` "Runtime cost") into any
    `mode = "mutating"` scenario's throughput/cost estimates. A scenario
    `reset/reset.sh` remains a supported, optional escape hatch
    (`aws_bench/scenario/scenario.py`'s own layout docstring; absence is
    valid — `has_phase_script` just returns `False` and the generic reset
    still runs unconditionally) if some future resource type is ever
    proven uncovered by the generic sweep — but treat that as the
    exception, not the default, and prove the gap first (grep
    `aws_bench/resource_management/cleanup/handlers/` AND confirm the
    CloudControl/CCAPI fallback genuinely can't reach the type) before
    adding one.
  - The matching agent role from §2 above, and, if it needs to be a new or
    extended role, the procedure in §4.

---

## 4. When and how to extend the roles

**Read §2 first: for a mutating scenario the answer is almost always
`QALocalInvocationApplicationAdmin`, and this section does not apply.** Since
Amendment 24 there is no per-scenario least-privilege deploy role, and
reintroducing one is explicitly out of bounds — the retired
`QADeployApplicationRole` is the worked example of why (fake `AccessDenied`
"agent failures", and one arm's deploy mechanism silently holding more
authority than another's). A new scenario needing AWS power it does not have
is therefore a **read-only-role** problem, not a deploy-role problem.

The remaining legitimate case: a scenario whose agent phase genuinely never
mutates AWS still needs a *read* or *describe* action that
`QALocalInvocationApplicationRole` does not grant. That role may be extended
with read-only actions; it must not grow mutating ones (extending it that way
defeats its purpose — use the admin role instead). Do not create a fourth ad
hoc role. Procedure:

1. **Propose the diff.** Write out exactly which new actions/resources the
   scenario needs and why, scoped as tightly as the service allows (prefer
   a resource-ARN or path-prefix scope over `Resource: "*"`; if the service
   genuinely has no resource-level ARN for the action in question — API
   Gateway's own control-plane actions are the precedent, see
   `qa_roles_stack.ts`'s own statement comments — say so
   explicitly rather than silently widening). A short markdown doc under
   `docs/` (the pattern `docs/slice-g-iam-proposal.md` set, now superseded
   but readable for the shape) or just a clear paragraph in the scenario's
   own spec-authoring PR/commit message is enough — the point is a reviewable,
   written diff, not a specific file format.
2. **Get operator authorization, explicitly, in writing.** This repo does
   not add or widen IAM grants in the deployed `QARolesStack` without it —
   see `DECISIONS.md`'s own "Adding a `QADeployApplicationRole`" amendment
   for what that authorization looked like in practice (the operator's
   exact quote is recorded there; the role it authorized was later retired
   by Amendment 24, but the *authorization pattern* is the precedent). A
   proposal with no sign-off stays a proposal (see the superseded
   `docs/proposals/qa_deploy_application_role.proposed.ts` for what an
   unapproved proposal looks like while it waits — kept deliberately
   OUTSIDE `scenarios/anchor/scenario/cdk_app/`, which has no `tsconfig.json`
   `include` allowlist and will compile/deploy anything dropped under its
   `stacks/` directory).
3. **Extend `QARolesStack`.** Once authorized, edit
   `scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts` directly —
   widen the target role's existing `ManagedPolicy` statements or add a new
   statement to it, following the file's existing
   conventions (custom `ManagedPolicy` per role, `AccountPrincipal` trust,
   `roleName` a fixed literal). Type-check before committing:
   ```bash
   cd scenarios/anchor/scenario/cdk_app && ./node_modules/.bin/tsc --noEmit
   ```
4. **Re-run env setup so the scenario account picks it up.** A role
   definition change in `qa_roles_stack.ts` is not live until
   `aws-bench env setup` (or the equivalent `cdk deploy` this scenario's
   own `deploy/deploy.sh` wraps) actually runs against the target account —
   generating a task with a new `agent_role_name` does **not** by itself
   create that role anywhere. This step touches real AWS and is
   deliberately NOT something the generator or `make gen`/`make check` ever
   does for you.
5. **Record it in `DECISIONS.md`.** New entry: the authorization (quote
   the operator's own words, as this doc's own precedent does), the exact
   scoping added/changed, and confirmation of the env-setup re-run (or an
   explicit note that it's still pending, if code+docs landed ahead of a
   live deploy — exactly the state this change itself is in, see that
   amendment's own "Verification" section for the pattern).

---

## 5. Oracle-authoring steps

Every catch needs to be caught **twice, at equal strictness** — once in
Rego (the TF-shaped arms) and once in cfn-guard (the CDK arm) — plus a
human-readable statement of ground truth they're both derived from.
Sequence (`specs/SCHEMA.md` §4/§8, `oracles/rego/README.md`,
`oracles/cfn-guard/README.md`):

1. **`oracle.intent`** in the spec YAML — a natural-language paragraph
   stating exactly what a correct final artifact looks like. Write this
   FIRST; both policy bundles below are derived from it, and
   `oracles/<scenario-id>/intent.md` (generated verbatim from this field)
   is the single human-readable source of truth both policies are checked
   against.
2. **`oracle.structural_asserts`** — the machine-checkable tier-0/tier-1
   facts that operationalize the intent, each with a `cfn_jsonpath` and a
   `tf_jsonpath` (both arm shapes, even though only one runs per arm) so
   the SAME logical assertion is expressed identically in both directions.
   Tier "0" is enforced automatically by the generated `tests/
   static_tiers.sh` (compiled jq, run on every trial); tier "1" needs a
   hand-authored policy per the next step.
3. **`make gen`**, then hand-author `oracles/rego/<scenario-id>/policy.rego`
   and `oracles/cfn-guard/<scenario-id>/policy.guard` for every tier-1
   assert — the generator scaffolds an inert `GENERATOR-STUB` skeleton for
   both (`oracles/emit.py`, the single writer for both file types); a
   scenario whose tier-1 policy is still a stub scores every trial's
   `tier1_status` as `SKIPPED_STUB`, which the reward gate treats as a HARD
   FAILURE once any tier-1 assert is declared (not a silent pass) — you
   cannot ship a scenario with real tier-1 asserts and an unauthored
   policy. Author both bundles to the SAME strictness — a rule one bundle
   enforces and the other doesn't is exactly the asymmetry `make
   tier1-coverage` (below) exists to catch.
4. **`make check-paths SPEC=specs/<scenario-id>.yaml`** — resolves every
   declared `structural_assert` (tier 0 AND tier 1) against a real
   synthesized/planned artifact built from a hand-authored, oracle-correct
   reference fixture under `generator/tests/fixtures/<scenario-id>/<arm>/`.
   Catches a JSONPath that resolves to nothing against real toolchain
   output — the class of bug that stays invisible until this check exists,
   per `DECISIONS.md` Amendment 5 finding G2.
5. **`make tier1-coverage SPEC=specs/<scenario-id>.yaml`** — a coarse,
   per-arm numeric floor (`count(catches) >= count(tier-1 asserts)`),
   catching a tier-1 assert with zero covering negative fixture.

---

## 6. Reference solution + negative fixtures + the grading-proof gate

A scenario is not done when its oracle policies exist — it must be PROVEN
gradeable. For every enabled arm:

1. **`tasks/anchor/<scenario-id>-<arm>/solution/solve.sh`** — a real,
   hand-authored reference solution. Must score reward `1.0` end-to-end (the
   actual generated `static_tiers.sh`, not a shortcut).
2. **`tasks/anchor/<scenario-id>-<arm>/solution/broken/<catch-name>/solve.sh`**
   — one per `catches[].name` your spec declares, each reproducing exactly
   that one planted mistake (and nothing else) starting from the reference
   solution. Must score reward `0.0`.
3. Run both gates:
   ```bash
   make falsifiability SPEC=specs/<scenario-id>.yaml
   make grading-proof SPEC=specs/<scenario-id>.yaml
   ```
   `falsifiability` (`gates/oracle_falsifiability.py`) is the Phase-2 exit
   criterion made executable: solve.sh scores `1.0` AND every catch's
   broken fixture scores `0.0`, or the gate fails — with a distinct
   `NOT_AUTHORED` status (non-gating) only for a scenario whose `solve.sh`
   is still a generator stub. `grading-proof`
   (`gates/grading_proof.py`) goes one step further per catch: a
   TIER-1-POLICY-FAMILY negative fixture must score `0.0` on every enabled
   arm, proving the scenario is gradeable for real, not just that some
   fixture happens to fail somewhere.

A scenario with an authored `solve.sh` and no broken fixtures, or fixtures
that don't actually reproduce the catch they're named after, will show up
as a gate failure here — that's the point; do not hand-wave past a red
`make falsifiability`/`make grading-proof` by editing the oracle to be
lenient instead of fixing the fixture.

---

## 6.4 Multi-step scenarios (`steps:`)

A **multi-step** scenario decomposes one arc into N prompts delivered to N
**fresh agent sessions** — there is no `--resume`, no conversational memory
across the boundary, and state carries through the *workspace*, which is the
artefact being graded (`SCHEMA.md` §2.6/§8.3, DECISIONS.md Amendments 26/27).
Worked example: `specs/apigw-redeploy.yaml`.

Everything in §§1–6 still applies. These are the **additional** obligations:

1. **Write every step's instruction to be self-contained.** Step 2's agent has
   no recall of step 1 — "now also add X to what you just built" lands on an
   agent that never built anything (Amendment 26 §1). This is a consequence of
   the fresh-session choice, which exists to keep per-step output-token
   attribution honest: a resumed session replays the prior history into its own
   transcript, and the denominator of tokens-to-green would double-count it.

2. **No foreshadowing, on BOTH surfaces.** A step-1 prompt must not name the
   later change *anywhere* — not in `shared_body`, and not in a per-arm
   `language_line` (one arm naming a step-2 mechanism is an arm-parity defect
   as well as a leak). And the check has **two surfaces, not one**: everything
   under `environment/` is `COPY`'d into the agent image, so the skeleton
   header, file names and comments are prompt surface too. Auditing only the
   prompt is exactly how a leak shipped once (Amendment 27 §5.1). See §1 item
   2b for `workspace_title`/`workspace_id`, and §6.5 item 2 for the
   hostile-read procedure — it is the same procedure, and it applies here.

3. **Every step's oracle goes in `steps/<name>/tests/`. The shared root
   `tests/` stays oracle-free** — the generator emits exactly one
   step-agnostic `README.md` there. This is not tidiness: Harbor uploads the
   root `tests/` during *every* step's verification and only empties `/tests`
   at the start of the *next* step's verification, so anything step-specific
   there is readable inside a later step's agent phase (Amendment 26 §7 rule 1,
   Amendment 27 §5).

4. **A multi-step task has no root `instruction.md`**, and the generator
   deletes one if it finds it. Consequence worth knowing: `gates/equipping.py`
   folds the per-step instructions into the equipping hash *only in the absence
   of a root one*, so a stray root file would silently revert the hash to the
   single-step key for text no agent ever saw (Amendment 27 §5).

5. **Oracle projections: the final step runs the FULL tier suite; every
   non-final step MUST name its subset.** The final step omitting its assert
   projection is what keeps a multi-step scenario's terminal grading identical
   to what the single-step form graded. Inheriting the full suite on an
   intermediate step would grade an intermediate state against the FINAL
   state's asserts, which no correct intermediate solution can satisfy — every
   trial would abort at the `min_reward` gate (Amendment 27 §4). Both are
   enforced in `spec_model`.

6. **`min_reward` is a hard gate and defaults to `1.0` on every non-final
   step.** A step that misses it aborts the remaining steps, so step 2's prompt
   never fires unless step 1 verified green — a change request whose starting
   state was never built is not a measurement of anything. "No gate" must be
   written explicitly (`min_reward: 0.0`); it must never be the result of
   forgetting a key (Amendments 26 §3, 27 §4).

7. **Every non-final step needs its own
   `steps/<name>/solution/solve.sh` scoring 1.0 against its own subset
   oracle.** This obligation was *added* by the stepped form, not inherited:
   without it nothing shows the intermediate oracle is satisfiable, and an
   unsatisfiable step-01 oracle aborts every trial at the `min_reward` gate
   quietly. Write these as thin wrappers around the arm's existing
   whole-scenario `solve.sh` rather than copying its heredoc — two definitions
   of the same revision drift apart the first time either is edited, and a
   step-01 oracle validated against a stale revision proves nothing (Amendment
   27 §6). The task-root `solution/` tree is otherwise unchanged, and
   `make falsifiability` still runs it against the final step's full suite.

8. **Decide who deploys, per spec, and declare it.** The harness is the
   **default** deployer — `steps/<name>/pre_invoke/pre_invoke.sh` runs before
   that step's agent and is where a `terraform apply`/`cdk deploy` of the prior
   step's work, or an out-of-band drift injection, lives. A spec may **opt into
   agent-deploys** where the deploy loop *is* the measurement, which is what
   `apigw-redeploy` does in both steps: its discriminating event is the agent's
   own second apply, so a harness-run apply would take the exact action under
   measurement out of the agent's hands. The consequence of the opt-in is that
   agent-side deploy failures count against the agent (Amendments 26 §2, 27 §3).

9. **If any step's `pre_invoke` deploys, set `[pre_invoke] timeout_sec`
   explicitly.** There is no per-step override — every step inherits the single
   task-level timeout, whose upstream default (600 s) a real deploy comfortably
   exceeds. Size it for the slowest step. A timeout here does not read as a
   slow deploy; it surfaces as a **scored-zero trial** (Amendment 26 draft
   addendum (a), Amendment 27 §4).

10. **Minimum 2 steps.** A 1-step "multi-step" task is refused — it moves every
    checksum and hash for no measurement gain. Existing single-step tasks are
    deliberately *not* normalized into 1-step multi-step shape for the same
    reason (Amendments 26 §6, 27 §4).

11. **Never pool multi-step rows with single-step rows** — including the
    single-step-form rows of the *same* scenario. Separate metric stratum, §8
    below.

**Running them.** `scripts/run-bench.sh` execs **`cdktn-bench`**, this repo's
own superset of the upstream runner: same flags, and a task declaring
`[[steps]]` builds a multi-step trial instead of being refused, while a
stepless task falls through to the untouched single-step path (Amendment 27
§7). You do not pass anything extra — the task shape selects the path.

---

## 6.5 Brownfield scenarios (`workspace_seed`)

A **brownfield** scenario's workspace does not start empty: `entry_file` ships
hand-authored, plan-green, already-deployed configuration that carries a latent
pitfall, and the prompt is a change request against it (`specs/SCHEMA.md` §2.7,
`DECISIONS.md` Amendment 28, `docs/design/poisoned-workspace-design.md`).
Worked example: `specs/named-resource-replacement.yaml`.

Everything in §§1–6 still applies. These are the **additional** obligations:

1. **Write one seed per enabled arm, and prove each one green.** There is no
   derivation path between the arms, so the seeds are hand-authored under the
   same discipline as `solution/solve.sh` and the reference fixtures
   (Amendment 28 §2). `make seed-parity SPEC=specs/<id>.yaml` runs the arm's
   real toolchain against the generated, **un-overlaid** workspace and resolves
   every declared `seed_asserts` entry against the artifact it produces,
   through the same jq compilation a real trial's tier-0 uses. Wire it per spec
   into `make ci`. A seed that does not build/synth/plan is a generation
   failure, not a hard scenario — it would score every trial on that arm 0.0
   before the agent typed anything.

   **"Equivalent" is behavioural, never a census.** Declared facts + green, not
   resource counts or types — a count check would fail every honest seed, since
   the benchmark's whole thesis is that one L2 construct decomposes into N
   Terraform resources. Two consequences to accept rather than engineer away:
   an assert's `applies_to` may legitimately differ per arm (CloudFormation has
   no `lifecycle` meta-argument, and expresses a graph edge as an `Fn::GetAtt`
   intrinsic where Terraform uses a reference string), and the gate proves the
   facts you declared, not sameness of system — `premise` is the human-readable
   equivalence claim and is reviewed the way `oracle.intent` is.

1b. **Know which files the agent may write.** The seed is the file the agent is
   *asked to change*, so it ships writable. `seeded_files` (§2.5) are the
   opposite — read-only reference inputs — and a path may not appear in both
   blocks. The two are deliberately separate keys with opposite semantics;
   `SCHEMA.md` §2.5/§2.7 carry the exact permissions. The seed also gets **no
   generator header at all** (§6.5 rule 2): a provenance banner tells the agent
   the file is bench scaffolding, which invites meta-reasoning about planted
   traps.

2. **Hostile-read the whole prompt surface — which is every byte the Dockerfile
   `COPY`s, plus every `instruction.md`.** Not just the seed. This scoping is
   the rule, and it is a rule because the narrower version failed in practice:
   the pilot's author ran a hostile self-check over "the seed and the
   instruction", and the leak was in **neither** — it was in a generator-stamped
   header derived from `title` (Amendment 28 §3 rule 7; the same lesson
   Amendment 27 §5.1 records for multi-step). Reading only the files you wrote
   is how both leaks shipped.

   So the unit of review is the emitted task, per arm:

   - **everything under `environment/`** — the seed, the skeleton entry files,
     generator-stamped headers and CFN `description`s, file and directory
     names, fixtures, preflight scripts;
   - **every `instruction.md`** (root, or each `steps/<name>/` one);
   - and the **`title`-derived and `id`-derived** strings that reach either of
     the above (which is what `workspace_title` and `workspace_id` exist to
     intercept — §1 item 2b).

   Ask, of each comment, name, header and premise sentence: *does this hint at
   the trap?* A comment near the poisoned property, an editorial marker
   (`TODO`/`NOTE:`/`careful`), the generator's own skeleton banner, or any
   mention of the fixing mechanism all fail. **Check it per arm, not once**: a
   hint that lands on two arms and not the third does not merely make the task
   easier, it biases the very cross-arm number the scenario exists to produce.

   Mechanical backstops exist and are deliberately not a substitute for the
   read: `spec_model` tripwires seed comments,
   `generator/tests/test_multistep_emission.py` deny-list-scans a multi-step
   task's `environment/`, and
   `generator/tests/test_workspace_seed.py::TestBrownfieldPromptSurface` scans a
   brownfield task's emitted bytes *and* pins the verbatim `title` string as
   unreachable. They catch the vocabulary someone already thought of. The
   judgement is yours.

3. **State facts in `premise`, never warnings.** "It is already deployed in this
   account" is a fact. "Careful, this group is in use" is a hint — the
   in-use-ness must be discoverable from the configuration, which is what a
   `seed_assert` pins. Do not name the mechanism either
   (`create_before_destroy`, "replacement", "perpetual diff"), which extends
   §2.1's existing `instruction_concision` rule. `premise` is spec-level,
   arm-agnostic, and inserted *before* the per-arm language line, so prompt
   parity holds by construction rather than by review.

4. **Frame the prompt as a change request or an incident symptom.** Never "find
   the bug", "fix the mistake" or "review this config" — those measure code
   review, not day-2 change. An incident prompt states a symptom and a desired
   end state, never a diagnosis. The workspace ownership note changes too: not
   "write your entire solution there" but "holds this project's existing
   configuration — change it as needed". The don't-touch clause for
   `provider.tf`/`bin/app.ts`/`main.ts` is unchanged and still load-bearing.

5. **The do-nothing negative is MANDATORY, and it is generated for you.**
   Brownfield creates exactly one failure mode greenfield cannot have: **a
   change request whose end state the seed already satisfies rewards doing
   nothing**, and every existing gate stays green while it happens —
   `solution/solve.sh` scoring 1.0 proves the oracle *accepts* a correct
   change, never that it *rejects* the absence of one. So every `workspace_seed`
   spec ships `solution/broken/seed-unchanged/solve.sh`, a no-op that submits
   the seed exactly as found, and `gates/oracle_falsifiability.py` requires it
   to score **< 1.0** — a dedicated check whose absence is a hard FAIL, not a
   skip (Amendment 28 §5).

   Three properties of that gate worth understanding before you fight it:
   **`< 1.0` rather than `== 0.0`** deliberately, because the claim being
   falsified is "doing nothing does not earn full marks" and pinning an exact
   value would couple the gate to the reward scale; the gate **additionally
   requires a graded artifact** to exist, because a broken toolchain also
   writes `0.0` and the one check whose purpose is to be un-fakeable must not
   pass vacuously on an infrastructure hiccup; and the fixture is
   **generator-owned and overwritten on every run** — a documented exception to
   the hand-authored-`solution/**` rule, because its content is entirely
   mechanical and the one fixture that must be un-weakenable must not be
   hand-editable into a passing no-op.

   If it scores 1.0, your change request is already satisfied by your own seed.
   Move the change request or the oracle — **never the fixture**.

6. **Decide the tier honestly, and measure it.** A brownfield trap is often
   invisible to the graded artifact. Before writing a static assert for it,
   *check that the artifact actually carries the property* — the pilot's own
   `create_before_destroy` fact does not survive `terraform show -json`, so a
   `not_exists` assert on it would have been a dead path that passes on a
   broken solution and a fixed one alike. If it is invisible, tier the catch
   `"live"` and make its negative fixture **mechanically demonstrate** the
   indistinguishability offline (print `CDKTN_BENCH_LIVE_ONLY_CONFIRMED` only
   after proving it), so a future toolchain release that changes the answer
   turns the gate red instead of letting the claim rot.

7. **Consider `verifier.idempotence`** (`SCHEMA.md` §5.1, Amendment 28 §4) when
   the failure mode is "the change appears to deploy but does not converge": it
   asks whether, after the solution is green, the agent's **own toolchain**
   reports a converged state against what it deployed. Four properties to know
   before opting in:

   - **It is live-only by necessity.** A static tier plans an empty directory,
     and `terraform plan -detailed-exitcode` returns `2` against empty state
     unconditionally, so no meaningful second-plan signal can exist offline.
     `idempotence.enabled` therefore *requires* `live_check.enabled`.
   - **It is gating and fail-closed** — both `pending_changes` and
     `not_verifiable` downgrade the reward to `0.0`, on the same reasoning §3
     gives for `live_check.gating`: for a catch that only this tier can see, a
     non-gating tier can never cost a trial any reward.
   - **The per-arm commands are injected by the generator, not read from a spec
     key.** In particular the awscdk arm diffs against the *deployed stack*
     rather than re-synthesizing: a second synth plus a template self-diff is
     vacuous by construction (CDK synth is deterministic) and would silently
     hand that arm a free pass.
   - **Offline it is skipped with a recorded reason, never fake-passed** — on
     every arm, by two different mechanisms, because the arms keep their
     converged state in different places (a local state file on the TF arms; on
     awscdk there is none to probe, so a completion marker is checked
     post-flight instead). If you add an arm, you owe it one of these.

8. **Never pool brownfield rows with greenfield rows.** Separate metric
   stratum — see §8 below for the full set of no-pooling rules and the one
   place they are *not* yet enforced mechanically.

---

## 7. The holdout-split rule

`specs/split.yaml` (`generator/split.py`) assigns every real scenario to
`train` or `holdout` (prereg §7.1) — a **60/40 split by a deterministic hash
of the scenario id**, not a manual choice per scenario. `generator/
gen.py::enforce_no_holdout_equipping()` hard-fails `make gen` if a holdout
scenario's generated task directory ever contains skill/MCP/plugin
equipping config.

**The rule this split exists to enforce:** any tuned skill/MCP equipping
must be developed ONLY against scenarios currently assigned `train`. A
holdout scenario is used purely to SELECT among equippings already built on
train, never to tune them — using a holdout scenario's own feedback to
improve an equipping and then reporting that scenario's score is exactly
the train/test leakage this split prevents.

**When you add a new scenario**, its split assignment isn't something you
set in the spec — it falls out of the deterministic hash the next time the
split is regenerated:

```bash
uv run python generator/split.py --write
```

This recomputes the assignment from every non-toy `specs/*.yaml` id
currently on disk and overwrites `specs/split.yaml`. Because 60/40 is a
moving cutoff rank over a growing set, adding a scenario can flip an
EXISTING scenario's assignment even though its own score didn't change —
expected, not a bug. If any id flips `train → holdout`, any equipping tuned
against it while it was `train` is now tainted and must be retired/re-tuned
(see `generator/split.py`'s own "Re-split procedure" docstring for the
full before/after diff + `DECISIONS.md` entry this requires). A `holdout →
train` flip has no integrity problem but should still be logged. Never run
`--write` as a side effect of routine `make gen`/`make ci` — it's always a
separate, deliberate, logged action.

---

## 8. Metric strata — which rows may be pooled

Adding a scenario adds rows to a results set, and this repo refuses several
poolings **by pre-registration**, not by later judgement from the data. Know
which stratum your new scenario lands in before you run it.

| Do not pool | Rule |
|---|---|
| N-step vs 1-step tokens-to-green | Amendment 26 §4 — more prompts means more authoring; cross-shape comparisons are *refused, not adjusted* |
| single-step-form vs multi-step-form rows **of the same scenario** | Amendment 27 §2 — the two forms are different scenarios (the prompt *content* changed too) |
| brownfield vs greenfield | Amendment 28 §6 — one is graded on a change to code the agent did not write, the other on authoring from empty |

A multi-step scenario's headline number is
**tokens-to-green-across-steps**: the cumulative sum of per-step agent OUTPUT
tokens (Amendment 23's denominator, unchanged) up to and including the step at
which the final oracle first passes. Per-step tokens are emitted alongside, so
the addends stay visible. Censoring stays **trial-level** — one `MAX_TOKENS`
budget for the whole trial, not N per step, so that decomposing a task does not
silently move its censoring threshold (Amendment 26 §5).

**Partly mechanical, and the gap matters.** A brownfield task's seed hash is
folded into its `equipping_hash`, so brownfield rows are visibly
non-comparable with greenfield ones and the hash moves the moment any arm's
seed changes — which is the result schema's own definition of "not comparable".
But the aggregator's cell key does **not** carry a scenario-form dimension, so
a headline cell computed over a mixed row set would average the forms together
regardless. Until that changes: **do not run `make metrics` over a results
directory containing more than one form — aggregate each stratum separately**
(Amendment 28 §6).

---

## Worked example: `apigw-redeploy`

Every rule above has a real instance in this repo's own history, most
concentrated in one scenario:

- Mutating + gating decision: `specs/apigw-redeploy.yaml`'s
  `verifier.live_check` block, and `DECISIONS.md`'s Slice G amendments
  (12-15) for the iteration that got the gating semantics and cleanup story
  right after getting them wrong twice.
- Role selection: this scenario is why the repo has a mutating-role policy at
  all — and why it now has exactly *two* roles rather than three. It first got
  a bespoke, minimally-scoped `QADeployApplicationRole`, which
  **Amendment 24 retired**: a too-tight deploy role turned harness permission
  gaps into fake agent failures, and it broke arm parity (terraform deployed
  under the scoped role while the CDK arm's default synthesizer routed through
  an `AdministratorAccess` bootstrap role — one arm silently had more
  authority). The scenario now runs as `QALocalInvocationApplicationAdmin` like
  every mutating scenario. Do not reintroduce the middle role; see §2 and §4.
- Reset/cleanup: `apigw-redeploy` originally added its own
  `scenarios/anchor/reset/reset.sh` fixed-name sweep, on the (later
  disproven) assumption that the generic framework sweep had no delete
  handler for `AWS::ApiGateway::*`. Two live teardown experiments
  (`DECISIONS.md` Amendments 17/18) showed the framework's generic reset
  covers it — including CFN-random physical names, the exact case the
  sweep couldn't handle — so the script was removed as dead code
  (Amendment 18, executed 2026-08-13); the scenario now relies solely on
  the framework's generic post-trial reset.
- Multi-step decomposition (§6.4): this scenario is why `steps:` exists
  (`SCHEMA.md` §2.6). Its original single prompt narrated both days *and*
  named its own trap; `DECISIONS.md` Amendment 27 and
  `docs/prompt-decomposition-audit.md` record what was removed (four separate
  foreshadowing leaks plus one outright answer-key leak), why the agent — not
  the harness — still runs both deploys, and why its single-step results must
  never be pooled with multi-step-form ones.
- The `environment/` leak (§1 item 2b, §6.5 rule 2): this scenario is also why
  `workspace_title` exists. Its step-1 *prompt* was clean, and line 1 of the
  very file that prompt said the agent owned still announced the day-2
  iteration — because the generator stamped the scenario `title` into the
  skeleton header, and the arm Dockerfile `COPY`s that file into the image.
  A verifier found it; Amendment 27 §5.1 records the fix at the schema.
- Holdout: `specs/split.yaml` places `apigw-redeploy` in `holdout`. That is
  orthogonal to whether it can be run — it has been run live and green
  (`docs/live-results.md`, Amendment 23, single-step form). The split is about
  equipping-tuning integrity, not about runnability.
- Brownfield contrast: the sibling worked example for §6.5 is
  `specs/named-resource-replacement.yaml`, the brownfield pilot — a different
  form, a different stratum, and the reason the hostile-read rule in §6.5 rule
  2 is scoped to every byte the Dockerfile copies rather than to the seed.
