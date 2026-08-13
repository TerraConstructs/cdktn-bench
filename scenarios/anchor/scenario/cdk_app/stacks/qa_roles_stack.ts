import { Stack, StackProps } from 'aws-cdk-lib';
import { AccountPrincipal, Effect, IRole, ManagedPolicy, PolicyStatement, Role } from 'aws-cdk-lib/aws-iam';
import { Construct } from 'constructs';

/**
 * Generic QA roles stack, copied from the aws-bench-datasets convention
 * (docs/aws-bench-datasets-guide.md §6a, "copy verbatim: the QA roles").
 * Creates the two standard agent roles aws-bench itself uses:
 *
 * - QALocalInvocationApplicationRole  (read-only agent role for introspection tasks)
 * - QALocalInvocationApplicationAdmin (AdministratorAccess agent role for mutation tasks)
 *
 * DEPLOY IDENTITY MODEL (DECISIONS.md Amendment 24, 2026-08-13). Mutation
 * scenarios (a live apply/modify/re-apply loop) run the agent as
 * `QALocalInvocationApplicationAdmin` -- exactly what aws-bench does for its
 * own 35 mutation tasks. This is deliberately BROAD power in a DISPOSABLE,
 * guarded account, not per-scenario least-privilege. The safety model is the
 * platform's (confirmed by reading aws-bench):
 *   - a dedicated, reset-to-baseline account (886312446417), nothing valuable,
 *     no path to prod (sibling accounts' OrganizationAccountAccessRole trusts
 *     the management account, not this member);
 *   - a region-restriction SCP (`awsbench-region-restrict-anchor`) on the
 *     account, and a role-protection SCP (`awsbench-protect-org-access-role`)
 *     on the OU that DENIES the admin agent from tampering with
 *     OrganizationAccountAccessRole / cfn-service-execution (so the reset path
 *     is always intact) -- both verified present 2026-08-13 before adopting
 *     this model;
 *   - token + turn censoring bounding each trial;
 *   - framework reset + contamination gating after every mutating trial.
 * Why broad, not scoped: a too-tight deploy role turns HARNESS permission gaps
 * into fake AGENT failures (invalid-infra masquerading as the agent), and both
 * arms MUST carry identical deploy authority or the abstraction comparison is
 * contaminated. Admin gives both -- Terraform (direct API calls) and CDK (via
 * CloudFormation, standard bootstrap synthesizer) deploy with equal authority.
 *
 * RETIRED (Amendment 24): the bespoke, minimally-scoped `QADeployApplicationRole`
 * (apigateway/lambda/path-scoped-iam/logs, + Amendment 19's scoped
 * `sts:AssumeRole`) is removed -- it was a deviation from the platform that
 * created exactly the false-failure and arm-parity hazards above, and every
 * grant it carried is subsumed by AdministratorAccess. See DECISIONS.md
 * Amendment 24 for the aws-bench IAM-story evidence and the SCP verification.
 *
 * The upstream convention also included a `LLMJudgeFullBedrockAccessRole` for
 * Bedrock-LLM-judged scenarios. REMOVED earlier (see DECISIONS.md): this repo
 * grades 100% programmatically (static tiers + tests/live_check.py), no
 * generated task.toml sets `verifier_role_name`, and the role was never
 * assumed by anything. See docs/adding-scenarios.md (§ role maintenance) to
 * add a role back if a future scenario needs one.
 *
 * Assumes one environment per account -- role names are not env-scoped.
 */
export class QARolesStack extends Stack {
    public readonly readonlyRole: IRole;
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

        // ── QALocalInvocationApplicationAdmin (admin for mutation tasks) ──
        // The deploy identity for all mutating scenarios (see stack docstring
        // + DECISIONS.md Amendment 24). Broad by design; made safe by the
        // disposable account + region/role-protection SCPs + reset, not by
        // narrow IAM. Matches aws-bench's own mutation-task role verbatim.
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
