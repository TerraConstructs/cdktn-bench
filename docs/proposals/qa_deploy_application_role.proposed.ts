// =============================================================================
// PROPOSED, UNDEPLOYED CODE -- DO NOT WIRE THIS INTO scenario/cdk_app/environment.ts
// WITHOUT EXPLICIT OPERATOR SIGN-OFF.
//
// This file deliberately lives OUTSIDE scenarios/anchor/scenario/cdk_app/
// (which IS live, deployed infrastructure code, picked up by that app's own
// tsconfig.json with no `include` allowlist -- ANY .ts file dropped under
// its `stacks/` directory gets compiled and is one `new QADeployApplicationRole(...)`
// call away from being deployed on the next `cdk deploy`). Keeping this
// proposal here means it can never be accidentally picked up, compiled, or
// deployed by that app -- it is inert until a human copies it in, reviews
// it, and explicitly wires it up.
//
// See ../slice-g-iam-proposal.md for the full rationale (which permissions,
// why, and what's still open). Companion to specs/apigw-redeploy.yaml
// (Slice G) -- DECISIONS.md's Slice G amendment records that this role was
// proposed but NOT created/deployed this run; `apigw-redeploy` continues to
// use the existing, already-provisioned QALocalInvocationApplicationAdmin
// (full AdministratorAccess) role, a logged over-grant, until an operator
// approves this narrower role.
//
// To adopt (operator action, not automated by this repo):
//   1. Review every action/resource/condition below against current AWS
//      documentation -- this was authored by reasoning about the
//      scenario's real needs (specs/apigw-redeploy.yaml,
//      docs/apigw-redeploy-mechanics.md), not verified against a live
//      deploy (see the doc's own "Verification status" section).
//   2. Move this file's class body into
//      scenarios/anchor/scenario/cdk_app/stacks/qa_roles_stack.ts, as a
//      fourth role alongside QALocalInvocationApplicationRole/Admin/
//      LLMJudgeFullBedrockAccessRole (same file, same construct-per-role
//      pattern already there).
//   3. Add `new QADeployApplicationRole(...)` wiring inside
//      scenarios/anchor/scenario/cdk_app/environment.ts's
//      `createEnvironment()`, alongside the existing `new QARolesStack(...)`
//      call (or as a new construct inside QARolesStack itself -- either
//      shape works; QARolesStack's own constructor is the natural place
//      since it already owns the other 3 QA roles).
//   4. Set specs/apigw-redeploy.yaml's
//      `verifier.live_check.agent_role_name` from
//      "QALocalInvocationApplicationAdmin" to "QADeployApplicationRole",
//      `make gen SPEC=specs/apigw-redeploy.yaml`, and re-run
//      `aws-bench env setup` against the target account so the role
//      actually exists before any trial tries to assume it.
//   5. Re-run a live proof (both arms, both revisions) under the NEW role
//      to confirm nothing in the real deploy path needs a permission this
//      policy doesn't grant -- do not assume clean until re-proven live.
// =============================================================================

import { AccountPrincipal, Effect, IRole, PolicyDocument, PolicyStatement, Role } from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

/**
 * PROPOSED (not deployed): a minimally-scoped role for `apigw-redeploy`'s
 * agent phase, replacing that spec's current
 * `agent_role_name: "QALocalInvocationApplicationAdmin"` (full
 * AdministratorAccess -- a real, logged over-grant, DECISIONS.md Slice G
 * amendment). Scoped to exactly what this ONE scenario's instruction asks
 * an agent to do: create a REST API + two Lambda functions + their
 * execution role, wire them together, deploy, modify, redeploy. See
 * docs/slice-g-iam-proposal.md for the per-statement rationale and honest
 * caveats on where tight resource-scoping isn't achievable.
 */
export function buildQaDeployApplicationRole(scope: Construct, accountId: string): IRole {
    return new Role(scope, 'QADeployApplicationRole', {
        roleName: 'QADeployApplicationRole',
        assumedBy: new AccountPrincipal(accountId),
        inlinePolicies: {
            ApiGatewayFull: new PolicyDocument({
                statements: [
                    new PolicyStatement({
                        sid: 'ApiGatewayManage',
                        effect: Effect.ALLOW,
                        // API Gateway's control-plane actions have no useful
                        // resource-level ARN to scope CREATE calls to (the REST
                        // API id doesn't exist until CreateRestApi returns) --
                        // enumerated explicitly (not `apigateway:*`) so this is
                        // at least action-scoped to exactly what the scenario's
                        // instruction (specs/apigw-redeploy.yaml) asks for, not
                        // every apigateway action that exists.
                        actions: [
                            'apigateway:GET',
                            'apigateway:POST',
                            'apigateway:PUT',
                            'apigateway:PATCH',
                            'apigateway:DELETE',
                        ],
                        // apigateway's own IAM action namespace is verb-shaped
                        // (GET/POST/PUT/...), not per-operation -- resource-level
                        // restriction would need the `execute-api`-style ARN
                        // condition keys API Gateway's *control plane* (as
                        // opposed to its data plane / execute-api invoke side)
                        // does not support for these HTTP-verb actions. `*` here
                        // is the same compromise docs/slice-g-recon.md's own §1
                        // draft already reasoned through -- flagged, not hidden.
                        resources: ['*'],
                    }),
                    new PolicyStatement({
                        sid: 'LambdaManageScoped',
                        effect: Effect.ALLOW,
                        actions: [
                            'lambda:CreateFunction',
                            'lambda:GetFunction',
                            'lambda:GetFunctionConfiguration',
                            'lambda:UpdateFunctionCode',
                            'lambda:UpdateFunctionConfiguration',
                            'lambda:DeleteFunction',
                            'lambda:AddPermission',
                            'lambda:RemovePermission',
                            'lambda:GetPolicy',
                            'lambda:TagResource',
                            'lambda:ListVersionsByFunction',
                        ],
                        // Every arm's reference solution and this spec's own
                        // instruction fix the REST API name to
                        // `apigw-redeploy-api`; hcl_raw names its two Lambdas
                        // `apigw-redeploy-hello`/`apigw-redeploy-version`
                        // explicitly, and terraconstructs' L2 default naming is
                        // `${gridUUID}-...` = `apigw-redeploy-...` (confirmed
                        // directly against terraconstructs 0.2.13's
                        // `uniqueResourceNamePrefix`, DECISIONS.md Slice G
                        // amendment finding G5). awscdk's L2 (no explicit
                        // `functionName`) generates a CloudFormation-random
                        // name with NO fixed prefix -- this scoped resource ARN
                        // does not cover that arm's default naming. Either the
                        // awscdk reference solution/instruction should pin an
                        // explicit `functionName: "apigw-redeploy-..."` (not
                        // yet done), or this statement needs a second,
                        // unscoped fallback for that one arm -- flagged as an
                        // open gap in docs/slice-g-iam-proposal.md, not
                        // silently widened here.
                        resources: [`arn:aws:lambda:us-east-1:${accountId}:function:apigw-redeploy-*`],
                    }),
                    new PolicyStatement({
                        sid: 'LogsScoped',
                        effect: Effect.ALLOW,
                        actions: [
                            'logs:CreateLogGroup',
                            'logs:CreateLogStream',
                            'logs:PutLogEvents',
                            'logs:DescribeLogGroups',
                            'logs:DescribeLogStreams',
                            'logs:DeleteLogGroup',
                        ],
                        resources: [
                            `arn:aws:logs:us-east-1:${accountId}:log-group:/aws/lambda/apigw-redeploy-*`,
                            // /aws/apigateway/welcome is a fixed, account-wide
                            // singleton CloudWatch Logs group API Gateway
                            // auto-creates the first time account-level
                            // execution logging is enabled anywhere in the
                            // account -- not scenario-scoped by name, but a
                            // fixed, well-known name, so still tightly scoped
                            // (not a wildcard) rather than left uncovered.
                            `arn:aws:logs:us-east-1:${accountId}:log-group:/aws/apigateway/welcome`,
                        ],
                    }),
                    new PolicyStatement({
                        sid: 'IamRoleLifecycleUnscopedName',
                        effect: Effect.ALLOW,
                        actions: [
                            'iam:CreateRole',
                            'iam:GetRole',
                            'iam:PutRolePolicy',
                            'iam:GetRolePolicy',
                            'iam:AttachRolePolicy',
                            'iam:DetachRolePolicy',
                            'iam:DeleteRolePolicy',
                            'iam:DeleteRole',
                            'iam:TagRole',
                        ],
                        // NOT name-prefix-scoped, unlike Lambda/Logs above --
                        // see docs/slice-g-iam-proposal.md "Why IAM role
                        // actions are Resource: *" for the honest reason (CDK/
                        // terraconstructs L2 default role naming has no fixed,
                        // predictable prefix across all 3 arms; a path-based
                        // scope would need every arm's agent-authored code to
                        // set an explicit `path`, which this scenario's
                        // instruction does not currently ask for). This is the
                        // single widest grant in this policy -- flagged, not
                        // hidden, and bounded to CRUD-on-a-role actions only
                        // (no `iam:*`, no user/group/policy-document escape
                        // hatches beyond what's listed).
                        resources: ['*'],
                    }),
                    new PolicyStatement({
                        sid: 'IamPassRoleToLambdaOnly',
                        effect: Effect.ALLOW,
                        actions: ['iam:PassRole'],
                        resources: ['*'],
                        // The one meaningful guard rail available when the
                        // resource itself can't be scoped by name (see above):
                        // restrict PassRole to roles actually being handed to
                        // the Lambda service, regardless of the role's name --
                        // a standard least-privilege pattern for exactly this
                        // "CDK-generated role name" situation.
                        conditions: {
                            StringEquals: { 'iam:PassedToService': 'lambda.amazonaws.com' },
                        },
                    }),
                    new PolicyStatement({
                        sid: 'CdkToolkitAssumeRoleForAwscdkArm',
                        effect: Effect.ALLOW,
                        actions: ['sts:AssumeRole'],
                        // awscdk's `cdk deploy` needs to assume the CDKToolkit
                        // bootstrap's own execution/deploy roles (already
                        // provisioned in the target account per
                        // docs/slice-g-recon.md §3 -- `deploy.sh` bootstraps
                        // idempotently as part of the anchor scenario's own
                        // env setup, before any task trial runs). These two
                        // role names are fixed, predictable patterns baked in
                        // by `cdk bootstrap` itself
                        // (`cdk-hnb659fds-cfn-exec-role-*`,
                        // `cdk-hnb659fds-deploy-role-*`), so THIS action can
                        // be resource-scoped precisely, unlike the apigateway/
                        // iam-role statements above.
                        resources: [
                            `arn:aws:iam::${accountId}:role/cdk-hnb659fds-cfn-exec-role-*`,
                            `arn:aws:iam::${accountId}:role/cdk-hnb659fds-deploy-role-*`,
                        ],
                    }),
                    new PolicyStatement({
                        sid: 'StsSelfIdentity',
                        effect: Effect.ALLOW,
                        actions: ['sts:GetCallerIdentity'],
                        resources: ['*'],
                    }),
                ],
            }),
        },
    });
}
