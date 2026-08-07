# Slice G recon: `apigw-redeploy` live-iteration scenario

Recon only — no implementation. Companion reading: `docs/apigw-redeploy-mechanics.md`
(mechanics), `specs/SCHEMA.md` (spec contract, esp. §5 `verifier.live_check`), the
`apigw-openapi` static sibling (`specs/apigw-openapi.yaml`, `tasks/anchor/apigw-openapi-*`),
`local-registry.md` "Slice F operational notes", `DECISIONS.md`.

---

## 1. Agent-side AWS permissions

**Today, every generated task hardcodes a read-only agent role and read-only
concurrency**, unconditionally — not spec-driven:

- `generator/gen.py:655` — `'agent_role_name = "QALocalInvocationApplicationRole"'`,
  a literal string in `build_task_toml`, not read from the spec.
- `generator/gen.py:662` — `'mode = "read-only"'`, same story, with the comment at
  lines 658-661 explicitly reasoning "no AWS mutation happens ... since
  `verifier.live_check.enabled` is false in v1."
- No `verifier_role_name` line is ever emitted, so `[scenario].verifier_role_name`
  is absent from every generated `task.toml` (confirmed by inspection of
  `tasks/anchor/apigw-openapi-awscdk/task.toml`).

**QA roles available today** (`scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`,
copied verbatim from aws-bench-datasets convention):

| Role | Policy | Line |
|---|---|---|
| `QALocalInvocationApplicationRole` | `ReadOnlyAccess` + a few read-only managed policies (S3Tables, Redshift, Athena, Bedrock, a custom S3-Vectors-read policy) | `qa_roles_stack.ts:52-63` |
| `QALocalInvocationApplicationAdmin` | `AdministratorAccess` + `AmazonBedrockFullAccess` | `qa_roles_stack.ts:66-73` |
| `LLMJudgeFullBedrockAccessRole` | `AmazonBedrockFullAccess` (verifier/judge use) | `qa_roles_stack.ts:76-82` |

**No existing role is minimally-scoped for this scenario.** `QALocalInvocationApplicationRole`
cannot deploy anything (read-only). `QALocalInvocationApplicationAdmin` *would* work
(full admin covers apigateway/lambda/iam) but is a gross over-grant for a scenario that
only needs `apigateway:*`, `lambda:*`, and narrowly-scoped `iam:CreateRole`/`iam:PassRole`
— using it would mean the agent trial runs with full `AdministratorAccess` in the
dedicated account, which is avoidable.

**Recommendation (not yet implemented): add a new role to `QARolesStack`**,
`QADeployApplicationRole`, scoped roughly:

```
- apigateway:*                                  (Resource: "*" -- APIGW has no useful ARN-level scoping for REST API create)
- lambda:*                                       (Resource: "*", or scoped to a function-name prefix if the scenario picks a fixed prefix)
- logs:CreateLogGroup / CreateLogStream / PutLogEvents / DescribeLogGroups  (Resource: "*", Lambda's own execution-role logging)
- iam:CreateRole, iam:PutRolePolicy, iam:AttachRolePolicy, iam:DeleteRole,
  iam:DeleteRolePolicy, iam:DetachRolePolicy, iam:GetRole, iam:PassRole
  (Resource: arn:aws:iam::886312446417:role/cdktn-bench-task/*  -- a path-prefixed
  scope, same pattern the QA roles README already commented on for other tasks;
  requires the task's Lambda execution role(s) be created under that path)
- sts:GetCallerIdentity (Resource: "*")
```

**Open question, not resolved by this recon**: if the `awscdk` arm's own agent
`cdk deploy` targets the account's existing CDKToolkit bootstrap (see §3), CDK v2's
default deploy path needs the deploying identity to `sts:AssumeRole` into the
bootstrap's `cdk-hnb659fds-cfn-exec-role-*`/`cdk-hnb659fds-deploy-role-*` (or have
direct CloudFormation/S3/ECR permissions if deploying without execution-role
indirection). `QADeployApplicationRole` would need `sts:AssumeRole` scoped to those
two bootstrap-role ARNs (fixed, predictable names once bootstrap has run) added
before this is real — flagged, not spec'd here.

**How creds get into the agent container** (`aws-bench` source, not this repo):

- `task.toml [scenario].agent_role_name` is read by `ScenarioRef.role_name(RoleType.AGENT)`
  (`aws_bench/dataset/task_config.py:59-66`).
- `AwsBenchSingleStepTrial._run_agent_phase` (`aws_bench/task/aws_trial.py:323-364`)
  calls `_staged_credentials(RoleType.AGENT)` (line 335), which calls `_assume_all_tags`
  (line 148-164) → `assume_role_for_script` (`aws_bench/task/aws_creds.py:52-71`),
  which does `chain_assume_role(account_id, role_name, ...)` for the named role, or
  falls back to `OrganizationAccountAccessRole` (`ORG_ACCESS_ROLE`,
  `aws_bench/account_management/constants.py:11`) if `role_name` is `None`/falsy
  (`aws_creds.py:61-65`).
- The resulting per-tag STS creds are written as a real `~/.aws/credentials` file
  inside the agent container at `$HOME/.aws/credentials`
  (`aws_trial.py:166-225`, `_staged_credentials`), with the raw
  `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN`/`AWS_DEFAULT_PROFILE`
  env vars blanked (`_RAW_CRED_VARS`, lines 55-60) so nothing host-forwarded can
  outrank the file, and `AWS_PROFILE` set to the account tag. Removed on exit
  (finally block, lines 217-225) — never persists past the phase.
- **The exact same mechanism stages the verifier's creds** — `_verifier_creds`
  (`aws_trial.py:366-384`) calls `_staged_credentials(RoleType.VERIFIER)`. Since no
  generated `task.toml` sets `verifier_role_name`, **the verifier today runs with
  `OrganizationAccountAccessRole`** (full org-access-role permissions in the member
  account) by the same fallback path — i.e., the verifier already has more than
  enough permission to call `apigateway get-deployments`/invoke the execute-api
  endpoint with zero new role work, *if* left unset. Whether that's desired (broad
  org-access creds in a live_check script) or whether `verifier_role_name` should be
  pinned to a narrower read-only role for this scenario is an open design choice.

---

## 2. `live_check` plumbing

> **2026-08-07 update (benchmark-integrity review finding G3):** every gap
> this section originally identified is now closed. `LiveCheck.enabled` is
> `bool` (Slice G), `build_task_toml` writes
> `[verifier] env = { SPEC_LIVE_CHECK_ENABLED = "true" }` for
> `apigw-redeploy`, `build_live_check_py`'s stub is superseded by a real
> hand-authored `tests/live_check.py` for this scenario, and the
> `CDKTN_BENCH_LIVE_CHECK` runner-env second gate this section flagged as
> "not verified further" turned out to be unsatisfiable by construction
> (nothing outside generated copies of `test.sh`/`gen.py`/`SCHEMA.md` ever
> set it) — dropped, per DECISIONS.md's fix-round entry for finding G3.
> `[verifier].env` reaching the verifier's real process environment IS now
> confirmed against real aws-bench/harbor source
> (`harbor/verifier/verifier.py`'s `verify()`), not left as an open
> integration point. The rest of this section is kept as the original
> recon record.

**Today this is fully wired as a dead path** — present, generated, never executed:

- `specs/SCHEMA.md §5` / `generator/spec_model.py:421` — `LiveCheck.enabled:
  Literal[False]` — **the spec model itself statically rejects any spec that sets
  `verifier.live_check.enabled: true`.** This is the first thing that must change
  (`bool`, not `Literal[False]`) for Slice G to exist as a spec field.
- `generator/gen.py:1337-1361` (`build_test_sh`) already generates the gating logic
  correctly: `tests/test.sh` runs `static_tiers.sh` first, then, only if
  `${SPEC_LIVE_CHECK_ENABLED:-false} = true` **and** the runner sets
  `CDKTN_BENCH_LIVE_CHECK=1`, execs `live_check.py > /logs/verifier/live_check-result.json`.
  Confirmed byte-identical in a real generated task: `tasks/anchor/apigw-openapi-awscdk/tests/test.sh`.
- **`SPEC_LIVE_CHECK_ENABLED` is never set anywhere.** It's read with a `false`
  default in the generated `test.sh` but no code path in `gen.py` writes it into
  `task.toml`'s `[verifier]`/`[environment]` section or anywhere else — grepped the
  whole of `generator/gen.py`, zero hits for the string as a write target. This is
  the second gap: something (most likely `build_task_toml`'s `[verifier]` block,
  `gen.py:693-695`) needs to grow an `env = { SPEC_LIVE_CHECK_ENABLED = "true" }`
  line (or equivalent) for a spec with `live_check.enabled: true`, and that env has
  to actually reach the verifier container — `[verifier].env` is exactly the
  channel `_verifier_creds`/`resolve_env_with_creds` already merges creds into
  (`aws_trial.py:376-379`), so this is additive, not a new mechanism.
- `generator/gen.py:1406-1428` (`build_live_check_py`) currently only ever scaffolds
  the inert `{"status": "not_implemented", ...}` stub — real assertions
  (`apigateway get-deployments`, invoke the `execute-api` URL, compare before/after
  behavior) need to be hand-written into this generator function for the new
  scenario, or the scaffolding logic needs a spec-level escape hatch to let Slice D-
  style hand-authoring override the stub (mirroring how `policy.rego`/`policy.guard`
  are hand-authored, never generated, per `SCHEMA.md §8.2` point 7).
- `CDKTN_BENCH_LIVE_CHECK` is a **runner-set env var**, not read from `task.toml`
  anywhere in this repo — confirms it's aws-bench's own knob (outside this repo,
  akin to a CLI/env flag on the trial run itself) that must be set when invoking the
  benchmark for this scenario to actually execute `live_check.py`. Not verified
  further in this recon (would require reading aws-bench's own CLI/trial-config
  source, out of scope for "recon only").
- **Non-gating is structural, not a convention to remember**: `test.sh`'s `exit $rc`
  (line 1359) is `static_tiers.sh`'s own exit code, computed *before* the
  live-check block — `live_check.py`'s own exit status is discarded (`|| true` at
  `gen.py:1356`), so even a fully-implemented live_check literally cannot affect
  `reward.txt`/`rc` under the current wiring. Any Slice G design that wants
  live-deploy failure to gate reward would need a real change here, not just
  flipping `enabled: true`.

---

## 3. Toolchain deltas per arm for LIVE deploys

**awscdk — CDKToolkit bootstrap.** Confirmed: `scenarios/anchor/deploy/deploy.sh`
(the anchor scenario's own env-setup hook, run once per `aws-bench env setup`, not
per trial) already runs:

```sh
npx cdk bootstrap --profile PRIMARY "aws://${PRIMARY}/us-east-1"
```

(`deploy.sh` lines ~14-16, "Bootstrapping is idempotent.") This means **CDKToolkit
will already be present in account 886312446417 / us-east-1** by the time any
Slice G trial runs, as a side effect of the anchor scenario's own setup — no new
bootstrap step is needed in the task/agent/solve.sh layer. The open risk flagged in
§1 (whether `QADeployApplicationRole` needs `sts:AssumeRole` on the bootstrap's
CFN-exec/deploy roles) still applies — bootstrap *existing* doesn't by itself mean
an arbitrary IAM principal can use it without being granted that assume-role.

**hcl-raw / terraconstructs — state backend.** `arms/hcl-raw/environment/workspace/provider.tf`
has no `backend` block (grepped; only comments about `skip_*` offline-plan flags and
the `endpoints.sfn` STS-mock workaround). No S3/DynamoDB backend is configured
anywhere in either TF-shaped arm's bootstrap file. Terraform defaults to local
`terraform.tfstate` in the working directory when no backend is declared — **this is
fine for a single-trial `apply`** (the container is ephemeral and the whole
apply→modify→re-apply loop happens inside one trial's one container, so local state
persisting across the two `terraform apply` invocations within the same trial is
exactly the semantics needed; no cross-trial state sharing is implied or required).
Confirmed no S3 backend is needed for v1's one-trial-one-container shape.

**terraconstructs synth→apply**: same story — `arms/terraconstructs/environment`'s
bootstrap (`main.ts`) wires `cdktn synth`; the actual `terraform apply` step for a
live deploy would run in the synthesized stack's own output directory
(`cdktf.out/stacks/<id>/`, per `SCHEMA.md` §2.4's table), same local-state
reasoning as hcl-raw applies once synthesized.

---

## 4. Task shape: mutating mode + reset consequences

**`[concurrency] mode` must become `"mutating"`** for this scenario (not the
generator's current hardcoded `"read-only"`, §1) — that's what actually triggers
the framework reset:

- `AwsBenchSingleStepTrial.run` (`aws_trial.py:103-116`): `if
  self.config.concurrency_mode is ConcurrencyMode.MUTATING:
  await self._reset_scenario_account()` — reset only fires for mutating trials. A
  live-deploy scenario left at `"read-only"` (today's hardcoded default) would
  **never** trigger a reset, silently leaving the deployed API/Lambda/IAM resources
  in the account after every trial — a real risk if this generator default isn't
  also changed for this spec.
- `_reset_scenario_account` (`aws_trial.py:118-146`) constructs a fresh
  `ScenarioTrial` and runs `ScenarioPhase.RESET` (`aws_bench/scenario/trial.py`,
  `_run_reset` around line 828). **`scenarios/anchor/` has no `reset/` directory**
  (confirmed: only `deploy/` and `cleanup/` exist under `scenarios/anchor/`,
  `find` output). Per `ScenarioTrial`'s own docstrings
  (`trial.py:337-342`, "a reset with no `reset.sh`"), a scenario-authored
  `reset.sh` is optional — the RESET phase's real work is
  `ResourceManager.reset_scenarios` (`aws_bench/resource_management/manager.py:302`,
  invoked at `trial.py:835-843`), a **framework-level generic residual-resource
  diff/revert** against a snapshot taken at scenario setup, run regardless of
  whether `reset.sh` exists.
- **Not verified in this recon**: whether `ResourceManager`'s generic sweep actually
  covers/reverts `apigateway`/`lambda`/`iam` resource types (its resource-type
  coverage list lives in `aws_bench/resource_management/manager.py` and wasn't
  read in depth here — flagged as a follow-up before relying on it as the *sole*
  cleanup mechanism for this scenario's live resources).
- **Practical consequence for now**: given the CONTEXT's own explicit instruction
  ("ALWAYS delete live resources you create... leave the account as you found it"),
  the safe design is to **not** depend solely on the framework's generic reset for
  this scenario's resource cleanup — either give the scenario its own
  `scenarios/anchor/reset/reset.sh` (or equivalent explicit cleanup script) that
  `delete-rest-api`/`delete-function`/`delete-role`s anything tagged/named per this
  task's convention, or have the task's own `post_invoke`/`cleanup` phase (task-level,
  not scenario-level — `ScriptType.POST_INVOKE`) do it, and treat the framework
  generic sweep as defense-in-depth, not the primary mechanism. This is a design
  decision for implementation, not resolved by this recon.
- A failed reset **flags the account contaminated**
  (`trial.py`, `_flag_contamination`-style logic around lines 888-923;
  `aws_trial.py:136-142` logs "the account is flagged contaminated and later trials
  will be refused... `aws-bench env cleanup` to clean it and clear the flag") — a
  real operational risk for a scenario whose whole point is a live mutating loop:
  a mid-run failure (e.g. agent leaves a dangling deployment) could brick the
  shared anchor account for every subsequent trial (including unrelated static
  scenarios) until manually cleared. Worth explicit design attention before this
  scenario ships.

---

## Summary of concrete gaps to close before implementation

1. `generator/spec_model.py:421` — `LiveCheck.enabled` needs to allow `True`.
2. `generator/gen.py:655,662` — `agent_role_name`/`[concurrency] mode` need to
   become spec-driven (or at minimum, a special-cased override), not hardcoded.
3. New `QADeployApplicationRole` in `qa_roles_stack.ts` (spec above, §1) — scoped
   apigateway/lambda/iam(path-prefixed)/logs; open question on CDKToolkit
   assume-role grants for the awscdk arm.
4. `SPEC_LIVE_CHECK_ENABLED` needs an actual write path into generated
   `task.toml`/`[verifier].env` (§2) — currently read but never written anywhere.
5. `generator/gen.py::build_live_check_py` needs either real generation logic or a
   hand-authored-override escape hatch for this scenario's actual live assertions.
6. `[concurrency] mode = "mutating"` for this scenario + an explicit cleanup path
   (scenario `reset/reset.sh` and/or task `post_invoke`) — do not rely solely on
   the unverified framework generic sweep (§4).
7. Consider pinning `verifier_role_name` to something narrower than the
   `OrganizationAccountAccessRole` fallback the verifier gets today by omission (§1).

None of the above is implemented by this recon.
