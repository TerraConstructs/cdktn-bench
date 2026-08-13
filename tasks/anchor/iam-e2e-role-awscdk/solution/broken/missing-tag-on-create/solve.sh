#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), negative fixture for the missing-tag-on-create catch.
# Identical to solution/solve.sh's own reference lib/scenario-stack.ts
# EXCEPT for the one change described below -- isolates this fixture to
# ONLY this catch. The WORKLOAD role (and its genuinely grantXxx()-
# derived KMS/SSM permissions) is entirely UNCHANGED from the reference
# -- this is a DEPLOYER-side defect, and the deployer role is 100%
# hand-authored on every arm regardless of this rework.
#
# THE MISTAKE: the deployer's InstanceProfileLifecycle statement grants
# iam:CreateInstanceProfile but not iam:TagInstanceProfile -- and
# module/main.tf's own provider default_tags block means the module's
# CreateInstanceProfile call carries tags, which silently ALSO requires
# iam:TagInstanceProfile. This pairing never appears as two separate
# CloudTrail events; it has to be reasoned about, not observed. Every
# static tier PASSES this policy identically to the reference. Confirmed
# via an inline offline IAM evaluator reproducing this exact gap.
set -euo pipefail

cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import * as kms from "aws-cdk-lib/aws-kms";
import * as ssm from "aws-cdk-lib/aws-ssm";
import { Construct } from "constructs";

/**
 * REFERENCE SOLUTION (used by solution/solve.sh) -- IAM E2E role
 * derivation: author deployer + workload permissions against real AWS
 * denials.
 *
 * DEPLOYER role: mirrors ../../iam-e2e-role-hcl-raw/environment/workspace/
 * main.tf's own action/resource-scoping decisions exactly (the
 * account-id-placeholder workaround that arm needs does NOT apply here --
 * CDK resolves `cdk.Aws.ACCOUNT_ID` via a CloudFormation pseudo-parameter,
 * which needs no data source / no real AWS call at synth time, unlike
 * Terraform's `data "aws_caller_identity"`). 100% hand-authored -- no
 * grantXxx() call in either library derives a deployment/provisioning
 * role's permissions (docs/scenario-proposal-iam-e2e-role.md §4.3), so
 * this half of the scenario is deliberately arm-symmetric.
 *
 * WORKLOAD role: the scenario's actual grantXxx()-derivation contrast --
 * see the inline comments at the bottom of this file for exactly which
 * permissions are library-derived vs. hand-authored, and why.
 */
export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const accountId = cdk.Aws.ACCOUNT_ID;
    const externalId = "iam-e2e-role-trial-2026";
    const rolePath = "/cdktn-bench-task/";
    const instanceProfileArn = `arn:aws:iam::${accountId}:instance-profile/cdktn-bench-iam-e2e-role-workload-profile`;
    const ssmAppParamArnGlob = `arn:aws:ssm:us-east-1:${accountId}:parameter/cdktn-bench-iam-e2e-role/app/*`;
    const ssmAppConfigParamArn = `arn:aws:ssm:us-east-1:${accountId}:parameter/cdktn-bench-iam-e2e-role/app/config`;
    const s3ScratchArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch";
    const s3ScratchObjectsArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch/*";
    const workloadRoleArn = `arn:aws:iam::${accountId}:role${rolePath}iam-e2e-role-workload`;

    // --- DEPLOYER role (hand-authored, unchanged from v1) -----------------
    const deployerRole = new iam.Role(this, "DeployerRole", {
      roleName: "iam-e2e-role-deployer",
      path: rolePath,
      assumedBy: new iam.AccountPrincipal(accountId).withConditions({
        StringEquals: { "sts:ExternalId": externalId },
      }),
    });

    deployerRole.attachInlinePolicy(
      new iam.Policy(this, "DeployerPolicy", {
        statements: [
          new iam.PolicyStatement({
            sid: "ReadOnlyDiscovery",
            actions: [
              "ec2:Describe*",
              "ec2:GetSecurityGroupsForVpc",
              "ec2:DescribeVolumeStatus",
              "ssm:DescribeParameters",
              "sts:GetCallerIdentity",
            ],
            resources: ["*"],
          }),
          new iam.PolicyStatement({
            sid: "SsmRead",
            actions: ["ssm:GetParameter", "ssm:GetParameters"],
            resources: [ssmAppParamArnGlob],
          }),
          new iam.PolicyStatement({
            sid: "InstanceProfileLifecycle",
            actions: [
              "iam:CreateInstanceProfile",
              "iam:DeleteInstanceProfile",
              "iam:GetInstanceProfile",
              "iam:AddRoleToInstanceProfile",
              "iam:RemoveRoleFromInstanceProfile",
              "iam:UntagInstanceProfile",
              "iam:ListInstanceProfilesForRole",
              "iam:GetRole",
              "iam:ListRoleTags",
            ],
            resources: [instanceProfileArn, workloadRoleArn],
          }),
          new iam.PolicyStatement({
            sid: "AssumeWorkloadForTesting",
            actions: ["sts:AssumeRole"],
            resources: [workloadRoleArn],
          }),
          new iam.PolicyStatement({
            sid: "Ec2Write",
            actions: [
              "ec2:CreateSecurityGroup",
              "ec2:DeleteSecurityGroup",
              "ec2:AuthorizeSecurityGroupEgress",
              "ec2:RevokeSecurityGroupEgress",
              "ec2:CreateTags",
              "ec2:DeleteTags",
              "ec2:CreateVolume",
              "ec2:DeleteVolume",
            ],
            resources: ["*"],
          }),
          new iam.PolicyStatement({
            sid: "KmsUseForEbs",
            actions: [
              "kms:DescribeKey",
              "kms:Decrypt",
              "kms:GenerateDataKey",
              "kms:GenerateDataKeyWithoutPlaintext",
              "kms:CreateGrant",
            ],
            resources: ["*"],
            conditions: { StringEquals: { "kms:ViaService": "ec2.us-east-1.amazonaws.com" } },
          }),
          new iam.PolicyStatement({
            sid: "S3Scratch",
            actions: [
              "s3:CreateBucket",
              "s3:DeleteBucket",
              "s3:ListBucket",
              "s3:GetBucket*",
              "s3:PutBucket*",
              "s3:DeleteBucketPolicy",
              "s3:ListTagsForResource",
              "s3:GetAccelerateConfiguration",
              "s3:GetLifecycleConfiguration",
              "s3:GetReplicationConfiguration",
              "s3:GetEncryptionConfiguration",
              "s3:PutEncryptionConfiguration",
            ],
            resources: [s3ScratchArn, s3ScratchObjectsArn],
          }),
        ],
      }),
    );

    // --- WORKLOAD role ------------------------------------------------------
    const workloadRole = new iam.Role(this, "WorkloadRole", {
      roleName: "iam-e2e-role-workload",
      path: rolePath,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("ec2.amazonaws.com"),
        new iam.AccountPrincipal(accountId).withConditions({
          StringEquals: { "sts:ExternalId": externalId },
        }),
      ),
    });

    // --- LIBRARY-DERIVED (the contrast this scenario measures) ------------
    // The pre-provisioned CMK behind alias/cdktn-bench-iam-e2e-role.
    // AWS IAM requires a KEY ARN (never an alias name or alias ARN) to scope
    // kms:Decrypt in an identity policy -- confirmed against the AWS KMS
    // developer guide ("You must use its key ARN to specify a KMS key in an
    // IAM policy statement; you cannot use a key id, alias name, or alias
    // ARN", cmks-in-iam-policies.html). The key's GUID is opaque and NOT
    // derivable offline the way the account id is, so -- exactly like the
    // hcl_raw reference's own `account_id` variable workaround -- this uses
    // a CfnParameter with a syntactically-valid placeholder default,
    // keeping `cdk synth --no-lookups` fully offline. A real deploy passes
    // the true value:
    //   npx cdk deploy --parameters KmsKeyArn=$(aws kms describe-key \
    //     --key-id alias/cdktn-bench-iam-e2e-role \
    //     --query KeyMetadata.Arn --output text)
    // `kms.Key.fromLookup()` (a real AWS context-provider lookup at synth
    // time) was considered and rejected: this arm's own synth_command runs
    // `--no-lookups`, which would make that call fail hard.
    const kmsKeyArnParam = new cdk.CfnParameter(this, "KmsKeyArn", {
      type: "String",
      default: "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000",
      description:
        "Real ARN of the pre-provisioned CMK behind alias/cdktn-bench-iam-e2e-role. Placeholder default is for offline synth only -- pass the real value at deploy time.",
    });
    const cmk = kms.Key.fromKeyArn(this, "CdktnBenchKey", kmsKeyArnParam.valueAsString);

    // The SecureString "db-password" parameter. `grantRead()` derives
    // {ssm:DescribeParameters, ssm:GetParameters, ssm:GetParameter,
    // ssm:GetParameterHistory} scoped to THIS parameter's own ARN, and --
    // because `encryptionKey` is set -- internally calls
    // `cmk.grantDecrypt(workloadRole)` too (ParameterBase.grantRead:
    // "if (this.encryptionKey) { this.encryptionKey.grantDecrypt(grantee) }").
    // This is the scenario's central, evidenced construct-arm advantage:
    // the hcl_raw arm must hand-derive "SecureString implies kms:Decrypt"
    // itself (docs/scenario-proposal-iam-e2e-role.md A8); here the library
    // derives it FOR the agent, resource-scoped to the real CMK's own ARN
    // (stronger than hcl_raw's own Resource:"*" + kms:ViaService condition
    // workaround, which exists there only because hcl_raw has no
    // equivalent of an imported-construct ARN reference).
    const dbPasswordParam = ssm.StringParameter.fromSecureStringParameterAttributes(this, "DbPasswordParam", {
      parameterName: "/cdktn-bench-iam-e2e-role/app/db-password",
      encryptionKey: cmk,
    });
    dbPasswordParam.grantRead(workloadRole);

    // --- HAND-AUTHORED (no grantXxx() call covers these) -------------------
    // 1. The plain "config" parameter is deliberately NOT imported via
    //    StringParameter.fromStringParameterAttributes()/fromStringParameterArn():
    //    verified directly (real `cdk synth`) that doing so creates an
    //    UNUSED "AWS::SSM::Parameter::Value<String>" template Parameter as
    //    an unconditional side effect of that class's `stringValue` field
    //    initializer -- it appears even though nothing here ever reads
    //    `.stringValue`, only `.grantRead()`. CloudFormation resolves that
    //    parameter TYPE using the DEPLOYING PRINCIPAL's own ssm:GetParameters
    //    permission at stack-update time -- a coupling onto whoever calls
    //    `cdk deploy` (this benchmark's QADeployApplicationRole) that this
    //    scenario never authorized and does not need. Scoping "config" by
    //    hand avoids that side effect entirely.
    // 2. ssm:GetParametersByPath -- neither aws-cdk-lib@2.263.0 nor
    //    terraconstructs@0.2.13's grantRead() ever grants this action (both
    //    hard-code the same four single-parameter actions -- verified in
    //    source; TerraConstructs/base#133 is the open upstream tracking
    //    issue, itself filed as aws-cdk parity, not a terraconstructs-only
    //    regression). harness/assertions.py's own check_parameters_by_path()
    //    calls exactly this action, over BOTH parameters at once. THIS is
    //    the scenario's deliberate anti-overclaim catch
    //    (getparametersbypath-not-granted): an agent who trusts a helper
    //    method documented as "grants read access to a parameter" without
    //    independently checking exactly which four actions it covers
    //    reproduces this gap, construct arm or not.
    // 3. ec2:DescribeVolumes/DescribeInstances (self-discovery): no
    //    grantXxx() helper on either library derives this -- it stands in
    //    for a real EC2 instance's own cloud-init discovering its attached
    //    volume by tag (this reduced module boots no instance;
    //    harness/assertions.py's check_volume_self_discovery() makes this
    //    call directly under the workload role's own credentials instead).
    workloadRole.attachInlinePolicy(
      new iam.Policy(this, "WorkloadHandAuthoredPolicy", {
        statements: [
          new iam.PolicyStatement({
            sid: "ReadPlainConfigParameter",
            actions: ["ssm:GetParameter", "ssm:GetParameters", "ssm:DescribeParameters"],
            resources: [ssmAppConfigParamArn],
          }),
          new iam.PolicyStatement({
            sid: "GetParametersByPathGapFiller",
            actions: ["ssm:GetParametersByPath"],
            resources: [ssmAppParamArnGlob],
          }),
          new iam.PolicyStatement({
            sid: "SelfDiscovery",
            actions: ["ec2:DescribeVolumes", "ec2:DescribeInstances"],
            resources: ["*"],
          }),
        ],
      }),
    );

    new cdk.CfnOutput(this, "DeployerRoleArn", { value: deployerRole.roleArn });
    new cdk.CfnOutput(this, "WorkloadRoleArn", { value: workloadRole.roleArn });
    new cdk.CfnOutput(this, "ExternalId", { value: externalId });
  }
}
TS

python3 - <<'PYCHECK'
import fnmatch, json

def as_list(x):
    return x if isinstance(x, list) else [x]

def action_matches(granted, requested):
    return fnmatch.fnmatchcase(requested.lower(), granted.lower())

def resource_matches(granted, requested):
    return granted == "*" or fnmatch.fnmatchcase(requested, granted)

def condition_matches(condition, context):
    if not condition:
        return True
    for op, kv in condition.items():
        for key, expected in kv.items():
            actual = context.get(key)
            expected_list = as_list(expected)
            if op == "StringEquals":
                if actual not in expected_list:
                    return False
            else:
                return False
    return True

def evaluate(statements, action, resource, context=None):
    context = context or {}
    decision = False
    for stmt in statements:
        if not any(action_matches(a, action) for a in as_list(stmt["Action"])):
            continue
        if not any(resource_matches(r, resource) for r in as_list(stmt["Resource"])):
            continue
        if not condition_matches(stmt.get("Condition"), context):
            continue
        if stmt["Effect"] == "Deny":
            return False
        if stmt["Effect"] == "Allow":
            decision = True
    return decision

STATEMENTS = [{'Action': ['iam:AddRoleToInstanceProfile', 'iam:CreateInstanceProfile', 'iam:DeleteInstanceProfile', 'iam:GetInstanceProfile', 'iam:GetRole', 'iam:ListInstanceProfilesForRole', 'iam:ListRoleTags', 'iam:RemoveRoleFromInstanceProfile', 'iam:UntagInstanceProfile'], 'Effect': 'Allow', 'Resource': ['arn:aws:iam::123456789012:instance-profile/cdktn-bench-iam-e2e-role-workload-profile', 'arn:aws:iam::123456789012:role/cdktn-bench-task/iam-e2e-role-workload']}]
CHECKS = [['iam:CreateInstanceProfile', 'arn:aws:iam::123456789012:instance-profile/cdktn-bench-iam-e2e-role-workload-profile', {}, True, 'the create call itself is still granted'], ['iam:TagInstanceProfile', 'arn:aws:iam::123456789012:instance-profile/cdktn-bench-iam-e2e-role-workload-profile', {}, False, 'THE GAP: default_tags makes CreateInstanceProfile ALSO require this, silently']]
all_ok = True
for action, resource, context, expect_allowed, label in CHECKS:
    got = evaluate(STATEMENTS, action, resource, context)
    status = "ALLOW" if got else "DENY"
    print(f"  mini-iam-sim: {action} on {resource} (ctx={context}) -> {status}  [{label}]")
    if got != expect_allowed:
        all_ok = False
        print(f"    UNEXPECTED: wanted {'ALLOW' if expect_allowed else 'DENY'}")

if not all_ok:
    raise SystemExit("mini-iam-sim: the fixture's policy did not reproduce the expected gap -- see output above")
print("CDKTN_BENCH_LIVE_ONLY_CONFIRMED: offline policy-evaluator run above mechanically confirms the exact gap this fixture demonstrates -- every static tier passes this policy identically to the reference, only real IAM evaluation (or this scoped-down offline reimplementation of it, see oracles/lib/mini_iam_sim.py's design) tells them apart.")
PYCHECK

bash tests/static_tiers.sh
