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
3. **`instruction`** — one `shared_body` (identical prose across arms; the
   generator diffs it post-placeholder-substitution and fails the build if
   arms' instructions diverge outside the language line, `SCHEMA.md` §2/
   §8.2 point 2) plus one `per_arm` block per enabled arm (`language_line` +
   `output_contract`). Decide `verifier.live_check` (see §3 below) before
   writing the instruction body — a mutating scenario's instruction needs
   explicit language about whether the agent should clean up after itself
   (see `specs/apigw-redeploy.yaml`'s own instruction for the pattern: "Do
   NOT delete... leave every resource you created running").
4. **`catches`** and **`oracle.structural_asserts`** — the planted-mistake
   taxonomy (prereg §5) and the tiered checks that catch them. Write
   `oracle.intent` (the natural-language ground truth) FIRST, then derive
   the structural asserts from it — not the other way around; see §5 below
   ("oracle-authoring steps") for the full sequence, which is the same
   sequence whether you're adding a whole new scenario or extending an
   existing one's catch list.
5. **`verifier`** — `budget.max_iters` (default 8, don't raise without a
   logged amendment) and `live_check` (§3 below).
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
reading for this decision). Three roles exist today, all defined in
`scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`:

| Role | Grants | Use when |
|---|---|---|
| `QALocalInvocationApplicationRole` | `ReadOnlyAccess` + a handful of read-only managed policies (S3Tables, Redshift, Athena, Bedrock, a custom S3-Vectors-read policy) | The scenario's agent phase never mutates AWS — synth/plan-only, which is every scenario except `apigw-redeploy` as of this writing. This is the **default**: a spec that leaves `verifier.live_check.agent_role_name` unset (`null`) gets this role automatically (`generator/gen.py::build_task_toml`). |
| `QADeployApplicationRole` | Full `apigateway:*`, full `lambda:*`, IAM role-lifecycle actions (`CreateRole`/`GetRole`/`Put`&`GetRolePolicy`/`Attach`&`DetachRolePolicy`/`DeleteRolePolicy`/`DeleteRole`/`TagRole`/`PassRole`) path-scoped to `arn:aws:iam::<account>:role/cdktn-bench-task/*`, plus scoped `logs:*` and `sts:GetCallerIdentity`. | The scenario's agent phase performs real, but narrow, AWS mutations — a day-2 deploy/modify/redeploy loop against a specific, small set of services. This is the **minimally-scoped middle option**, added by explicit operator authorization for `apigw-redeploy` (see `DECISIONS.md` "Adding a QADeployApplicationRole" for the authorization on record and the exact policy). |
| `QALocalInvocationApplicationAdmin` | `AdministratorAccess` + `AmazonBedrockFullAccess` | Last resort only — a scenario whose mutations genuinely span services `QADeployApplicationRole` doesn't cover, AND extending that role (§4 below) isn't done yet or isn't warranted for a one-off. Using this role means the agent trial runs with full account admin — a real, logged over-grant every time it's chosen. |

**The rule: pick the least-privileged role that lets the scenario run.**
Concretely:

1. Does the scenario's agent phase ever call a mutating AWS API? If no,
   leave `agent_role_name` unset (`null`) — you get
   `QALocalInvocationApplicationRole` for free and don't need to read
   further.
2. If yes, does `QADeployApplicationRole`'s current grant (apigateway,
   lambda, path-scoped IAM role CRUD, scoped logs, `sts:GetCallerIdentity`)
   cover every mutating call the scenario's reference solutions actually
   make? If yes, set `agent_role_name: "QADeployApplicationRole"`.
3. If the scenario needs a service or action `QADeployApplicationRole`
   doesn't grant, do **not** fall back to
   `QALocalInvocationApplicationAdmin` by default — go to §4
   ("extending the roles") first. Only use
   `QALocalInvocationApplicationAdmin` if extending is genuinely not
   warranted (e.g. a true one-off exploratory scenario never intended to
   stay in the benchmark long-term) and say so explicitly in the spec's own
   `provenance` notes or a `DECISIONS.md` entry — this is a real,
   deliberate over-grant, not a shortcut to take silently.

---

## 3. Decide read-only vs. mutating

`SCHEMA.md` §5 documents `verifier.live_check` in full; this is the decision
rule.

- **Read-only (`verifier.live_check.enabled: false`, the default)**: the
  scenario is graded entirely from the FINAL delivered file — synth/plan
  output, never a real deploy. This is every scenario except
  `apigw-redeploy`. Leave `verifier.live_check` at its defaults; the
  generator sets `[concurrency] mode = "read-only"` automatically, which
  lets trials of the shared `anchor` scenario co-run without a reset cycle.
- **Mutating (`verifier.live_check.enabled: true`)**: the scenario's whole
  point is a runtime fact a static artifact cannot express — e.g.
  `apigw-redeploy`'s "did the SECOND deploy actually take effect, or does
  the stage keep serving stale content." Setting this `true` requires:
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
  - An explicit cleanup story: give the scenario its own
    `scenarios/anchor/reset/reset.sh` that sweeps the scenario's own
    fixed, well-known resource names (see that file for the pattern
    `apigw-redeploy` uses) — do not rely solely on the framework's generic
    post-trial sweep, which has no delete handler for every resource type
    (confirmed by grep against `aws_bench/resource_management/cleanup/
    handlers/` for `apigw-redeploy`'s own resource types — check the
    equivalent for whatever services your scenario touches before assuming
    coverage).
  - The matching agent role from §2 above, and, if it needs to be a new or
    extended role, the procedure in §4.

---

## 4. When and how to extend the roles

A new scenario sometimes needs a service or action none of the three
existing roles grant (`QALocalInvocationApplicationRole` is read-only by
design and shouldn't grow mutating actions; extending it defeats its
purpose). When that happens, extend `QADeployApplicationRole` — do not
create a fourth ad hoc role and do not silently fall back to
`QALocalInvocationApplicationAdmin`. Procedure:

1. **Propose the diff.** Write out exactly which new actions/resources the
   scenario needs and why, scoped as tightly as the service allows (prefer
   a resource-ARN or path-prefix scope over `Resource: "*"`; if the service
   genuinely has no resource-level ARN for the action in question — API
   Gateway's own control-plane actions are the precedent, see
   `qa_roles_stack.ts`'s `ApiGatewayFull` statement comment — say so
   explicitly rather than silently widening). A short markdown doc under
   `docs/` (the pattern `docs/slice-g-iam-proposal.md` set, now superseded
   but readable for the shape) or just a clear paragraph in the scenario's
   own spec-authoring PR/commit message is enough — the point is a reviewable,
   written diff, not a specific file format.
2. **Get operator authorization, explicitly, in writing.** This repo does
   not add or widen IAM grants in the deployed `QARolesStack` without it —
   see `DECISIONS.md`'s own "Adding a QADeployApplicationRole" amendment
   for what that authorization looked like in practice (the operator's
   exact quote is recorded there). A proposal with no sign-off stays a
   proposal (see the superseded `docs/proposals/
   qa_deploy_application_role.proposed.ts` for what an authorized-but-not-
   yet-approved proposal looks like while it waits — kept deliberately
   OUTSIDE `scenarios/anchor/scenario/cdk_app/`, which has no `tsconfig.json`
   `include` allowlist and will compile/deploy anything dropped under its
   `stacks/` directory).
3. **Extend `QARolesStack`.** Once authorized, edit
   `scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts` directly —
   either widen `QADeployApplicationRole`'s existing `ManagedPolicy`
   statements or add a new statement to it, following the file's existing
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

1. **`tasks/<scenario-id>-<arm>/solution/solve.sh`** — a real, hand-authored
   reference solution. Must score reward `1.0` end-to-end (the actual
   generated `tests/static_tiers.sh`, not a shortcut).
2. **`tasks/<scenario-id>-<arm>/solution/broken/<catch-name>/solve.sh`** —
   one per `catches[].name` your spec declares, each reproducing exactly
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

## Worked example: `apigw-redeploy`

Every rule above has a real instance in this repo's own history, most
concentrated in one scenario:

- Mutating + gating decision: `specs/apigw-redeploy.yaml`'s
  `verifier.live_check` block, and `DECISIONS.md`'s Slice G amendments
  (12-15) for the iteration that got the gating semantics and cleanup story
  right after getting them wrong twice.
- Role selection + the extend-the-roles procedure: this exact scenario is
  why `QADeployApplicationRole` (§4 above) exists at all —
  `QALocalInvocationApplicationRole` couldn't run it,
  `QALocalInvocationApplicationAdmin` was a real logged over-grant, and the
  operator-authorized middle role closes that gap. See `DECISIONS.md`
  "Adding a QADeployApplicationRole" for the authorization on record.
- Reset/cleanup: `scenarios/anchor/reset/reset.sh`, added specifically
  because the generic framework sweep had no delete handler for
  `AWS::ApiGateway::*`.
- Holdout: `specs/split.yaml` places `apigw-redeploy` in `holdout` — an
  orthogonal fact from its current NOT-YET-trial-runnable status (§4's IAM
  path-prefix gap, `specs/apigw-redeploy.yaml`'s own `gating` comment) —
  the split is about equipping-tuning integrity, not about whether a
  scenario can currently be run at all.
