import { Stack, StackProps } from 'aws-cdk-lib';
import { AccountPrincipal, Effect, IRole, ManagedPolicy, PolicyStatement, Role } from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

/**
 * Generic QA roles stack that creates the three standard roles
 * used by aws-bench environments:
 *
 * - QALocalInvocationApplicationRole  (read-only agent role for introspection tasks)
 * - QADeployApplicationRole           (minimally-scoped agent role for the apigw-redeploy
 *                                      mutation scenario -- apigateway/lambda/logs full,
 *                                      iam role-lifecycle path-scoped to
 *                                      /cdktn-bench-task/. See "Adding roles" below.)
 * - QALocalInvocationApplicationAdmin (admin agent role for mutation tasks)
 *
 * The original aws-bench-datasets convention this file was copied from
 * (docs/aws-bench-datasets-guide.md §6a, "copy verbatim: the 3 QA roles")
 * also included a fourth role, `LLMJudgeFullBedrockAccessRole`, for
 * scenarios graded by a Bedrock-hosted LLM judge. REMOVED here (DECISIONS.md
 * "Adding a QADeployApplicationRole" amendment): this repo grades 100%
 * programmatically (static tiers + tests/live_check.py; no rewardkit/judge
 * anywhere, confirmed by repo-wide grep), no generated task.toml has ever
 * set `[scenario].verifier_role_name` to anything (grepped: zero hits), and
 * `judgeRole` had zero other references in this repo -- the role was a
 * vestige of the upstream convention, never assumed by anything, $0.00
 * Bedrock spend in this account. See "Adding scenarios and tasks" (§ role
 * maintenance) in docs/adding-scenarios.md for the procedure to add a role
 * like this back (or a new one) if a future scenario needs it.
 *
 * Copied (originally verbatim, now amended per the above) from
 * aws-bench-datasets scenarios' stacks/qa_roles_stack.ts per
 * docs/aws-bench-datasets-guide.md §6a. Assumes one environment per
 * account — role names are not env-scoped.
 */
export class QARolesStack extends Stack {
    public readonly readonlyRole: IRole;
    public readonly deployRole: IRole;
    public readonly adminRole: IRole;

    constructor(scope: Construct, id: string, props?: StackProps) {
        super(scope, id, props);

        const accountId = this.account;

        // ── Custom policy: S3 Vectors read-only access ──
        const s3VectorsReadOnlyPolicy = new ManagedPolicy(this, 'S3VectorsReadOnlyAccess', {
            managedPolicyName: `S3VectorsReadOnlyAccess-${accountId}-${this.region}`,
            description: 'Read-only access to S3 Vectors operations',
            statements: [
                new PolicyStatement({
                    sid: 'AllowS3VectorsReadOnlyAccess',
                    effect: Effect.ALLOW,
                    actions: [
                        's3vectors:ListVectors',
                        's3vectors:GetVectors',
                        's3vectors:GetIndex',
                        's3vectors:GetVectorBucket',
                        's3vectors:GetVectorBucketPolicy',
                        's3vectors:ListIndexes',
                        's3vectors:ListTagsForResource',
                        's3vectors:ListVectorBuckets',
                        's3vectors:QueryVectors',
                    ],
                    resources: ['*'],
                }),
            ],
        });

        // ── QALocalInvocationApplicationRole (read-only for introspection) ──
        this.readonlyRole = new Role(this, 'QALocalInvocationApplicationRole', {
            roleName: 'QALocalInvocationApplicationRole',
            assumedBy: new AccountPrincipal(accountId),
            managedPolicies: [
                ManagedPolicy.fromAwsManagedPolicyName('ReadOnlyAccess'),
                ManagedPolicy.fromAwsManagedPolicyName('AmazonS3TablesReadOnlyAccess'),
                ManagedPolicy.fromAwsManagedPolicyName('AmazonRedshiftFullAccess'),
                ManagedPolicy.fromAwsManagedPolicyName('AmazonAthenaFullAccess'),
                ManagedPolicy.fromAwsManagedPolicyName('AmazonBedrockFullAccess'),
                s3VectorsReadOnlyPolicy,
            ],
        });

        // ── QADeployApplicationRole (minimally-scoped middle option, added by
        //    OPERATOR-AUTHORIZED request for the apigw-redeploy mutation
        //    scenario -- see DECISIONS.md "Adding a QADeployApplicationRole"
        //    for the authorization on record and this policy's own
        //    rationale. Promoted from docs/proposals/
        //    qa_deploy_application_role.proposed.ts (now marked superseded),
        //    re-derived from docs/slice-g-recon.md §1's own scoping draft
        //    per this stack's simpler existing convention (a custom
        //    ManagedPolicy attached via `managedPolicies`, matching
        //    s3VectorsReadOnlyPolicy above, rather than the proposal's
        //    inlinePolicies shape). ──
        const qaDeployApplicationPolicy = new ManagedPolicy(this, 'QADeployApplicationPolicy', {
            managedPolicyName: `QADeployApplicationPolicy-${accountId}-${this.region}`,
            description:
                'Minimally-scoped deploy permissions for the apigw-redeploy scenario: ' +
                'full apigateway/lambda, path-scoped IAM role lifecycle, scoped logs.',
            statements: [
                new PolicyStatement({
                    sid: 'ApiGatewayFull',
                    effect: Effect.ALLOW,
                    // API Gateway's control-plane actions have no useful
                    // resource-level ARN to scope CREATE calls to (the REST
                    // API id doesn't exist until CreateRestApi returns) --
                    // docs/slice-g-recon.md §1's own conclusion. Full
                    // `apigateway:*` (not just the CRUD verbs the scenario's
                    // reference solutions currently use) per the operator's
                    // explicit authorization -- see DECISIONS.md.
                    actions: ['apigateway:*'],
                    resources: ['*'],
                }),
                new PolicyStatement({
                    sid: 'LambdaFull',
                    effect: Effect.ALLOW,
                    // Full `lambda:*` per the operator's explicit
                    // authorization (DECISIONS.md), not scoped to a
                    // function-name prefix -- unlike the superseded
                    // proposal's `LambdaManageScoped` statement, this
                    // doesn't need per-arm naming-convention gymnastics
                    // (the proposal's own "Open gaps" #1, awscdk's
                    // unprefixed default Lambda names not matching a
                    // name-scoped ARN, is moot under this grant).
                    actions: ['lambda:*'],
                    resources: ['*'],
                }),
                new PolicyStatement({
                    sid: 'LogsScoped',
                    effect: Effect.ALLOW,
                    // docs/slice-g-recon.md §1's log-permission list, for
                    // the deploying identity's own logging needs (the
                    // Lambda functions' own execution role -- a SEPARATE
                    // role this policy's IamRoleLifecycleScoped statement
                    // below lets the agent create -- carries its own
                    // logs:* grant via AWSLambdaBasicExecutionRole or
                    // equivalent, at runtime; this statement is for the
                    // deploying identity's own toolchain, e.g. an explicit
                    // LogGroup resource in the IaC).
                    actions: [
                        'logs:CreateLogGroup',
                        'logs:CreateLogStream',
                        'logs:PutLogEvents',
                        'logs:DescribeLogGroups',
                        'logs:DescribeLogStreams',
                    ],
                    resources: ['*'],
                }),
                new PolicyStatement({
                    sid: 'IamRoleLifecycleScoped',
                    effect: Effect.ALLOW,
                    // The operator's authorization names `iam:CreateRole`/
                    // `iam:PassRole` as the headline scoped actions; per
                    // task instruction ("follow the permission scoping in
                    // docs/slice-g-recon.md -- it spec'd this role"),
                    // implemented as that section's full path-scoped
                    // role-lifecycle action list (Create/PassRole are the
                    // two most consequential of the set, the ones worth
                    // naming explicitly in a summary -- the rest is
                    // ordinary supporting CRUD a real `cdk deploy`/
                    // `terraform apply` needs to attach permissions to a
                    // role it just created and clean it up on a
                    // destroy/redeploy).
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
                    // Path-prefix scope, per the operator's explicit
                    // authorization ("path-prefixed to /cdktn-bench-task/")
                    // -- an IAM role's ARN embeds its `path`
                    // (arn:aws:iam::<account>:role/<path>/<name>), so a
                    // role created with `path: "/cdktn-bench-task/"` is the
                    // only shape this Resource pattern matches.
                    //
                    // GAP CLOSED (2026-08-13, see DECISIONS.md): the
                    // apigw-redeploy reference solutions used to create
                    // their Lambda execution role named
                    // `apigw-redeploy-lambda-exec` at the DEFAULT path
                    // (`/`), not under `/cdktn-bench-task/`, so this scoped
                    // grant would not have let those reference solutions
                    // actually deploy under this role. All three arms'
                    // solution/solve.sh (and hcl_raw's two LIVE-capable
                    // negative fixtures) now pin an explicit
                    // `path: "/cdktn-bench-task/"` on the role construct,
                    // and specs/apigw-redeploy.yaml's shared instruction
                    // body now tells the agent about this path constraint
                    // too. Still open: `aws-bench env setup` must be
                    // re-run against the target account so this role
                    // actually exists live before a real trial can assume
                    // it -- see docs/adding-scenarios.md's role-extension
                    // procedure and DECISIONS.md.
                    resources: [`arn:aws:iam::${accountId}:role/cdktn-bench-task/*`],
                }),
                new PolicyStatement({
                    sid: 'IamPassRoleScoped',
                    effect: Effect.ALLOW,
                    actions: ['iam:PassRole'],
                    resources: [`arn:aws:iam::${accountId}:role/cdktn-bench-task/*`],
                    // Belt-and-suspenders on top of the path-prefix Resource
                    // scope above (same defense-in-depth idea the
                    // superseded proposal used): even a path-scoped
                    // PassRole can only ever be handed to the Lambda
                    // service.
                    conditions: {
                        StringEquals: { 'iam:PassedToService': 'lambda.amazonaws.com' },
                    },
                }),
                new PolicyStatement({
                    sid: 'StsSelfIdentity',
                    effect: Effect.ALLOW,
                    actions: ['sts:GetCallerIdentity'],
                    resources: ['*'],
                }),
            ],
        });

        // NOT GRANTED, deliberately: `sts:AssumeRole` on the CDKToolkit
        // bootstrap's `cdk-hnb659fds-{cfn-exec,deploy}-role-*` (needed for
        // the awscdk arm's `cdk deploy` to actually execute against the
        // bootstrapped account -- docs/slice-g-recon.md §1's open question,
        // repeated by the superseded proposal's own table). The operator's
        // authorization on record (DECISIONS.md) does not name this action;
        // adding it needs its own explicit sign-off, same as this role
        // itself did -- follow docs/adding-scenarios.md's role-extension
        // procedure rather than silently widening this policy.
        this.deployRole = new Role(this, 'QADeployApplicationRole', {
            roleName: 'QADeployApplicationRole',
            assumedBy: new AccountPrincipal(accountId),
            managedPolicies: [qaDeployApplicationPolicy],
        });

        // ── QALocalInvocationApplicationAdmin (admin for mutation) ──
        this.adminRole = new Role(this, 'QALocalInvocationApplicationAdmin', {
            roleName: 'QALocalInvocationApplicationAdmin',
            assumedBy: new AccountPrincipal(accountId),
            managedPolicies: [
                ManagedPolicy.fromAwsManagedPolicyName('AdministratorAccess'),
                ManagedPolicy.fromAwsManagedPolicyName('AmazonBedrockFullAccess'),
            ],
        });
    }
}
