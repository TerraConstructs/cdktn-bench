#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8), negative fixture for the wildcard-matches-protected-bucket
# catch. Identical to solution/solve.sh's own reference
# lib/scenario-stack.ts EXCEPT for the one change described below --
# isolates this fixture to ONLY this catch.
#
# THE MISTAKE: the S3 resource scope drops the "-scratch" suffix the
# module's own bucket naming convention has -- "arn:aws:s3:::cdktn-
# bench-iam-e2e-*" is derived correctly from the module's prefix but
# ALSO matches the pre-provisioned decoy bucket
# (cdktn-bench-iam-e2e-tfstate-<account>-us-east-1), a real bucket this
# task's own module never creates or references. Every static tier-0
# check still PASSES (no admin wildcard, no invalid action, valid
# trust) -- only the tier-1 Rego glob-match check catches this, exactly
# like the real episode's own A11 defect: no failing run would ever
# surface it on its own. Verified directly: `opa eval` against this
# exact plan reports a non-empty `deny` set for
# data.cdktn_bench.iam_e2e_role.deny.
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
    const s3ScratchArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*";
    const s3ScratchObjectsArn = "arn:aws:s3:::cdktn-bench-iam-e2e-*/*";
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
            actions: ["ssm:GetParameter", "ssm:GetParameters", "ssm:GetParametersByPath", "ssm:DescribeParameters"],
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

bash tests/static_tiers.sh
