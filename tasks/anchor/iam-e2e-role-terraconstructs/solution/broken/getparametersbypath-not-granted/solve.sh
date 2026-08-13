#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), negative fixture for the getparametersbypath-not-granted
# catch. Identical to solution/solve.sh's own reference
# lib/scenario-stack.ts EXCEPT for the one change described below --
# isolates this fixture to ONLY this catch.
#
# THE MISTAKE (the scenario's anti-overclaim catch): drops
# ssm:GetParametersByPath from the hand-authored ReadAppParameters
# statement, leaving the workload role with single-parameter reads only
# (ssm:GetParameter/ssm:GetParameters) and no hierarchical path-based
# read anywhere -- even though the library-derived kms:Decrypt grant
# above is completely correct and unaffected. This is the same class of
# mistake as the awscdk arm's own fixture for this catch, reached by a
# different mechanism here (a hand-authored statement losing one action,
# rather than a hand-authored statement being dropped entirely) since
# this arm never routes the SSM read actions through grantRead() at all
# (see this scenario's own solve.sh header for why). Every static tier
# PASSES identically to the reference. Confirmed via an inline offline
# IAM evaluator reproducing this exact gap.
set -euo pipefail

cat > lib/scenario-stack.ts <<'TS'
// REFERENCE SOLUTION (used by solution/solve.sh) -- IAM E2E role
// derivation: author deployer + workload permissions against real AWS
// denials.
//
// DEPLOYER role: mirrors ../../iam-e2e-role-hcl-raw/environment/workspace/
// main.tf's own action/resource-scoping decisions exactly. Like the awscdk
// reference (not the hcl_raw one), this arm's account id (`this.account`,
// an AwsStack property backed by a `data "aws_caller_identity"` Terraform
// data source under the hood) resolves fine offline because this arm's own
// tests/static_tiers.sh already starts mock-sts.js around the whole
// `terraform plan` step -- so, unlike hcl_raw's own reference (which has
// no such mock available and must avoid `data "aws_caller_identity"`
// entirely), this file uses `this.account` directly. 100% hand-authored --
// no grantXxx() call in either library derives a deployment role's
// permissions, so this half of the scenario is deliberately arm-symmetric.
//
// WORKLOAD role: the scenario's actual grantXxx()-derivation contrast --
// see the inline comments below for exactly which permissions are
// library-derived vs. hand-authored on THIS arm, and why it differs from
// the awscdk arm's own split (a real, evidenced per-arm coverage limit,
// not an oversight -- see this file's solve.sh header for the full
// verification record).
import { Construct } from "constructs";
import { TerraformVariable } from "cdktn";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import * as iam from "terraconstructs/lib/aws/iam";
import * as encryption from "terraconstructs/lib/aws/encryption";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const accountId = this.account;
    const externalId = "iam-e2e-role-trial-2026";
    const rolePath = "/cdktn-bench-task/";
    const instanceProfileArn = `arn:aws:iam::${accountId}:instance-profile/cdktn-bench-iam-e2e-role-workload-profile`;
    const ssmAppParamArnGlob = `arn:aws:ssm:us-east-1:${accountId}:parameter/cdktn-bench-iam-e2e-role/app/*`;
    const s3ScratchArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch";
    const s3ScratchObjectsArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*-scratch/*";
    const workloadRoleArn = `arn:aws:iam::${accountId}:role${rolePath}iam-e2e-role-workload`;

    // --- DEPLOYER role (hand-authored, unchanged from v1) -----------------
    const deployerRole = new iam.Role(this, "DeployerRole", {
      roleName: "iam-e2e-role-deployer",
      path: rolePath,
      assumedBy: new iam.AccountPrincipal(accountId).withConditions({
        test: "StringEquals",
        variable: "sts:ExternalId",
        values: [externalId],
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
              "iam:TagInstanceProfile",
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
            condition: [{ test: "StringEquals", variable: "kms:ViaService", values: ["ec2.us-east-1.amazonaws.com"] }],
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

    // --- WORKLOAD role -------------------------------------------------------
    const workloadRole = new iam.Role(this, "WorkloadRole", {
      roleName: "iam-e2e-role-workload",
      path: rolePath,
      assumedBy: new iam.CompositePrincipal(
        new iam.ServicePrincipal("ec2.amazonaws.com"),
        new iam.AccountPrincipal(accountId).withConditions({
          test: "StringEquals",
          variable: "sts:ExternalId",
          values: [externalId],
        }),
      ),
    });

    // --- LIBRARY-DERIVED (the contrast this scenario measures) --------------
    // The pre-provisioned CMK behind alias/cdktn-bench-iam-e2e-role. AWS IAM
    // requires a KEY ARN (never an alias name or alias ARN) to scope
    // kms:Decrypt in an identity policy. The key's GUID is opaque and not
    // derivable offline the way the account id is -- exactly like the
    // hcl_raw reference's own `account_id` variable workaround, this uses a
    // TerraformVariable with a syntactically-valid placeholder default,
    // keeping `terraform plan` fully offline. A real deploy passes the true
    // value via `-var`, resolved the same way hcl_raw's own README documents
    // for account_id: `aws kms describe-key --key-id
    // alias/cdktn-bench-iam-e2e-role --query KeyMetadata.Arn --output text`.
    // `encryption.Key.fromLookup()` (a real Terraform CLI-time AWS lookup)
    // was considered and rejected for the same reason hcl_raw avoids
    // `data "aws_caller_identity"`: it is not offline-plan-safe.
    const kmsKeyArnVar = new TerraformVariable(this, "kms_key_arn", {
      type: "string",
      default: "arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000",
      description:
        "Real ARN of the pre-provisioned CMK behind alias/cdktn-bench-iam-e2e-role. Placeholder default is for offline plan only -- pass the real value at deploy time.",
    });
    const cmk = encryption.Key.fromKeyArn(this, "CdktnBenchKey", kmsKeyArnVar.stringValue);
    // Verified offline-plan-safe directly: importing a Key by ARN touches no
    // Terraform resource or data source at all (pure client-side ARN-string
    // handling), unlike importing a StringParameter (see below).
    cmk.grantDecrypt(workloadRole);

    // --- HAND-AUTHORED (no offline-plan-safe grantXxx() call covers these
    // on THIS arm -- see this file's solve.sh header for the full,
    // verified reason `storage.StringParameter.from*().grantRead()` is not
    // used here even though it exists and would derive these same actions)
    // -----------------------------------------------------------------------
    // Covers BOTH parameters under the fixed fixture path:
    //   - single-parameter reads (GetParameter/GetParameters/
    //     DescribeParameters) for "config" AND "db-password" alike (the
    //     KMS decrypt half of "db-password" access is library-derived
    //     above; its SSM read half is hand-authored here, for the reason
    //     given in this file's solve.sh header).
    //   - ssm:GetParametersByPath -- neither aws-cdk-lib@2.263.0 nor
    //     terraconstructs@0.2.13's grantRead() ever grants this action
    //     (both hard-code the same four single-parameter actions --
    //     TerraConstructs/base#133 is the open upstream tracking issue).
    //     harness/assertions.py's own check_parameters_by_path() calls
    //     exactly this action, over BOTH parameters at once. THIS is the
    //     scenario's deliberate anti-overclaim catch
    //     (getparametersbypath-not-granted), reachable identically on
    //     every arm.
    // ec2:DescribeVolumes/DescribeInstances (self-discovery): no grantXxx()
    // helper on either library derives this -- it stands in for a real EC2
    // instance's own cloud-init discovering its attached volume by tag
    // (this reduced module boots no instance; harness/assertions.py's
    // check_volume_self_discovery() makes this call directly under the
    // workload role's own credentials instead).
    workloadRole.attachInlinePolicy(
      new iam.Policy(this, "WorkloadHandAuthoredPolicy", {
        statements: [
          new iam.PolicyStatement({
            sid: "ReadAppParameters",
            actions: ["ssm:GetParameter", "ssm:GetParameters", "ssm:DescribeParameters"],
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

STATEMENTS = [{'Action': ['ssm:GetParameter', 'ssm:GetParameters', 'ssm:DescribeParameters'], 'Effect': 'Allow', 'Resource': 'arn:aws:ssm:us-east-1:123456789012:parameter/cdktn-bench-iam-e2e-role/app/*'}, {'Action': ['ec2:DescribeInstances', 'ec2:DescribeVolumes'], 'Effect': 'Allow', 'Resource': '*'}, {'Action': 'kms:Decrypt', 'Effect': 'Allow', 'Resource': 'arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000'}]
CHECKS = [['ssm:GetParameter', 'arn:aws:ssm:us-east-1:123456789012:parameter/cdktn-bench-iam-e2e-role/app/config', {}, True, 'single-parameter reads are still granted (hand-authored, unaffected by this fixture)'], ['kms:Decrypt', 'arn:aws:kms:us-east-1:123456789012:key/00000000-0000-0000-0000-000000000000', {}, True, 'the library-derived KMS decrypt is still granted (unaffected by this fixture)'], ['ssm:GetParametersByPath', 'arn:aws:ssm:us-east-1:123456789012:parameter/cdktn-bench-iam-e2e-role/app/config', {}, False, 'THE GAP: the hierarchical path read the harness actually uses is denied -- the hand-written ReadAppParameters statement no longer includes it']]
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
