# Slice G IAM proposal: `QADeployApplicationRole` (proposed, NOT deployed)

> **[2026-08-20 note]** Doubly historical: the role below was later RETIRED
> entirely by Amendment 24 (admin model), and the terraconstructs resource-name
> prefixes cited in the policy tables (`apigw-redeploy-*` via `gridUUID`) are
> stale since Amendment 28 §10 — `gridUUID` now carries `workspace_id`
> (`hello-version-api-*` for that scenario). Kept as an evolution record only.

> **SUPERSEDED (DECISIONS.md "Adding a QADeployApplicationRole" amendment).**
> The operator explicitly authorized and this repo has since created a REAL
> `QADeployApplicationRole` in
> `scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`, with a
> **simpler** scoping than this document's table below proposed: full
> `apigateway:*`, full `lambda:*` (not the verb-enumerated/name-prefix-scoped
> statements below), IAM role-lifecycle actions path-scoped to
> `/cdktn-bench-task/` (not the unscoped `Resource: *` this document's
> `IamRoleLifecycleUnscopedName` argued for), plus logs permissions. This
> document's per-statement reasoning remains a useful design record (why
> API Gateway can't be resource-scoped pre-creation, the `PassedToService`
> guard idea, the still-OPEN CDKToolkit `sts:AssumeRole` question) and is
> cited from the real implementation's own code comments — kept for that
> reason, not because the proposal below is what got built. See
> `docs/adding-scenarios.md` for the current role-selection/extension
> procedure and `DECISIONS.md` for the authorization on record.

Status: **proposal only, historical**. Not created, not deployed, not wired into
`scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts`. `specs/
apigw-redeploy.yaml` continues to set `verifier.live_check.agent_role_name:
"QALocalInvocationApplicationAdmin"` (full `AdministratorAccess` — a real,
logged over-grant) until an operator reviews this proposal and explicitly
authorizes deploying the narrower role below. This is a repeat of the
previous run's own finding (a prior attempt to add this role directly to
the deployed `QARolesStack` was correctly refused — the user had not
authorized that privilege grant) and this run does not re-attempt it. All
live proofs this run and the next are driven host-side with the operator's
own `OrganizationAccountAccessRole`-derived credentials (see CONTEXT), which
do not need this role at all.

The actual proposed code lives at
[`docs/proposals/qa_deploy_application_role.proposed.ts`](proposals/qa_deploy_application_role.proposed.ts)
— a real, syntactically valid CDK construct, deliberately kept **outside**
`scenarios/anchor/scenario/cdk_app/` (which is live, deployed infrastructure
code with no `tsconfig.json` `include` allowlist — any `.ts` file dropped
under its `stacks/` directory gets compiled by that app's own build). Kept
here instead so it is reviewable but structurally inert: nothing in this
repo's build/deploy path ever touches `docs/`.

## Why this scenario needs a role at all

`apigw-redeploy` (`specs/apigw-redeploy.yaml`) is the first scenario in this
benchmark whose agent phase performs REAL AWS mutations
(`verifier.live_check.enabled: true`, `concurrency_mode: "mutating"`) — see
`docs/apigw-redeploy-mechanics.md` and the scenario's own `oracle.intent`.
The agent needs to actually create an API Gateway REST API, two Lambda
functions, their shared execution role, and (day 2) a MOCK-integration
route, then redeploy. `QALocalInvocationApplicationRole` (read-only) cannot
do any of this. `QALocalInvocationApplicationAdmin`
(`AdministratorAccess`) can, but grants the agent phase every permission in
the account for a task that needs exactly four services' worth of narrow
CRUD.

## Exactly which permissions, and why

One inline policy, six statements (see the `.proposed.ts` file for the
literal CDK):

| Statement | Actions | Resource scope | Why |
|---|---|---|---|
| `ApiGatewayManage` | `apigateway:{GET,POST,PUT,PATCH,DELETE}` | `*` | API Gateway's IAM action namespace is verb-shaped (`GET`/`POST`/...), not per-operation, and its control-plane actions (as opposed to the `execute-api` data-plane invoke side) don't expose a resource-level ARN condition a `CreateRestApi` call could be scoped against before the API exists. Docs/slice-g-recon.md §1's own draft reached the same conclusion. Action-scoped (only the 5 HTTP verbs a REST/HTTP client uses) rather than `apigateway:*`, which is the tightest available bound. |
| `LambdaManageScoped` | `CreateFunction`, `GetFunction(Configuration)`, `UpdateFunctionCode`, `UpdateFunctionConfiguration`, `DeleteFunction`, `Add/RemovePermission`, `GetPolicy`, `TagResource`, `ListVersionsByFunction` | `arn:aws:lambda:us-east-1:<account>:function:apigw-redeploy-*` | The scenario's own fixed naming convention. hcl_raw's reference solution names its functions `apigw-redeploy-hello`/`apigw-redeploy-version` explicitly; terraconstructs' `compute.LambdaFunction` L2 defaults to `${gridUUID}-...` = `apigw-redeploy-...` (confirmed directly against terraconstructs 0.2.13's `uniqueResourceNamePrefix`, the same fact DECISIONS.md's Slice G amendment finding G5 already relied on for the log-group sweep prefix). **Gap**: awscdk's L2 (no explicit `functionName` in the reference solution) gets a CloudFormation-random name with no fixed prefix — this scoped ARN does not cover it. See "Open gaps" below. |
| `LogsScoped` | `Create/DescribeLogGroup(s)`, `CreateLogStream`, `PutLogEvents`, `DescribeLogStreams`, `DeleteLogGroup` | `/aws/lambda/apigw-redeploy-*` + the fixed, account-wide `/aws/apigateway/welcome` singleton | Covers exactly the log groups Lambda/API Gateway auto-create for this scenario (the same two prefixes DECISIONS.md Slice G amendment's finding 7/G5 already identified as needing cleanup). |
| `IamRoleLifecycleUnscopedName` | `Create/Get/DeleteRole`, `Put/Get/DeleteRolePolicy`, `Attach/DetachRolePolicy`, `TagRole` | `*` | See "Why IAM role actions are `Resource: *`" below — the one deliberately wide grant in this policy. |
| `IamPassRoleToLambdaOnly` | `iam:PassRole` | `*`, guarded by `Condition: StringEquals iam:PassedToService = lambda.amazonaws.com` | The standard least-privilege mitigation for an unscoped-by-name `PassRole` grant: whatever role name gets created, it can only ever be handed to the Lambda service, never to anything else. |
| `CdkToolkitAssumeRoleForAwscdkArm` | `sts:AssumeRole` | `arn:...role/cdk-hnb659fds-{cfn-exec,deploy}-role-*` | awscdk's `cdk deploy` needs to assume the CDKToolkit bootstrap's own roles. These have a fixed, predictable name pattern (`cdk bootstrap`'s own naming), already provisioned in the target account as a side effect of the anchor scenario's own env setup (`docs/slice-g-recon.md` §3 — bootstrap already ran, idempotent). Resolves the recon's own open question from that section. |
| `StsSelfIdentity` | `sts:GetCallerIdentity` | `*` | Needed by every arm's own credential-sanity/account-guard checks (the reference solutions' own "Account/region guardrail" echo lines). |

## Why IAM role actions are `Resource: *`

Every other statement above is scoped by a real, predictable name prefix.
IAM role creation is the one exception: CDK's `Role` L2 construct (used by
both the awscdk arm directly and, transitively, by terraconstructs'
`compute.LambdaFunction`'s own default execution role) does not set a fixed
name prefix by default — its auto-generated names are
`<stack-logical-id-derived-hash>`-shaped, with no common prefix across all
three arms the way Lambda function names happen to have. A path-based scope
(`arn:...role/cdktn-bench-task/*`, `docs/slice-g-recon.md`'s own original
draft) would require every arm's agent-authored code to explicitly set
`path: "/cdktn-bench-task/"` on the role it creates — this scenario's
instruction does not currently ask for that, and adding it would be a
second, separate spec change with its own review burden. Rather than either
(a) silently widening every OTHER statement to match, or (b) quietly
picking a fragile name-prefix guess likely to break on one arm, this is
logged as the single genuinely-wide grant in the policy, bounded to
role-CRUD actions only (no `iam:*`, no user/group/managed-policy-document
actions beyond what's listed), with `PassRole` separately guarded by the
`iam:PassedToService` condition above.

## Open gaps (honest, not resolved by this proposal)

1. **awscdk Lambda naming**: `LambdaManageScoped`'s
   `function:apigw-redeploy-*` resource scope does not cover awscdk's
   default (unprefixed) function names. Either the awscdk reference
   solution/instruction should pin an explicit
   `functionName: "apigw-redeploy-hello"` / `"apigw-redeploy-version"` (not
   yet done, would need its own spec/generator change and re-proof), or
   this statement needs a second, unscoped `lambda:*`-on-`*` fallback
   specifically for that arm — neither is done here; adopting this role
   as-is would need that gap closed and re-verified first, or the awscdk
   arm's live proof would fail with an `AccessDenied` this proposal did not
   anticipate.
2. **Not verified against a real deploy.** This policy was authored by
   reasoning about the scenario's documented needs
   (`specs/apigw-redeploy.yaml`, `docs/apigw-redeploy-mechanics.md`), not by
   running a live trial under it and observing zero `AccessDenied` errors.
   Per the adoption steps in the `.proposed.ts` file's own header, a real
   live proof under the new role (both arms, both revisions) is required
   before treating this as production-ready, not merely syntax-checked.
3. **Terraform/terraconstructs provider IAM calls**: the `hashicorp/aws`
   provider itself may issue a small number of read-only IAM calls
   (`iam:GetRole`, `iam:ListRolePolicies`, etc.) beyond the explicit
   resource CRUD listed above, depending on provider version and exact
   resource graph — `IamRoleLifecycleUnscopedName`'s action list was sized
   to the specific calls this scenario's own reference solutions make
   (`aws_iam_role`, `aws_iam_role_policy_attachment`), not audited against
   the full `hashicorp/aws` 6.x provider's read surface for these resource
   types.

## Verification status

- `docs/proposals/qa_deploy_application_role.proposed.ts` is syntactically
  valid TypeScript (matches the existing `qa_roles_stack.ts`'s own
  `aws-cdk-lib`/`constructs` import shape and `Role`/`PolicyStatement`
  usage patterns) — not run through this repo's own `tsc`/`cdk synth`
  since it is deliberately outside the `cdk_app` tree those commands ever
  touch (see the file's own header for why).
- Not created, not deployed, not assumed by anything in this run.
