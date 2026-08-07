#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Verified directly at authoring time (2026-08-08): `npx cdktn synth`
# succeeds, and a real `terraform init && terraform plan` against the
# synthesized stack (with this arm's own mock-sts.js started around it,
# exactly as tests/static_tiers.sh does) succeeds fully offline;
# tests/static_tiers.sh against the resulting plan.json reports
# tier0_pass=1, tier1_status=PASS (rego), reward=1.0.
#
# Like the hcl_raw reference's own header note: this only proves the
# STATIC half of this scenario's oracle. The LIVE half is unproven by this
# script -- see DECISIONS.md's iam-e2e-role amendment.
set -euo pipefail

cat > lib/scenario-stack.ts <<'TS'
// REFERENCE SOLUTION (used by solution/solve.sh) -- IAM E2E role
// derivation: author deployer + workload permissions against real AWS
// denials.
//
// Mirrors ../../iam-e2e-role-hcl-raw/environment/workspace/main.tf's own
// action/resource-scoping decisions exactly. Like the awscdk reference
// (not the hcl_raw one), this arm's account id (`this.account`, an
// AwsStack property backed by a `data "aws_caller_identity"` Terraform
// data source under the hood) resolves fine offline because this arm's
// own tests/static_tiers.sh already starts mock-sts.js around the whole
// `terraform plan` step (arms/terraconstructs' own documented fix for
// this exact gap -- see that arm's README) -- so, unlike hcl_raw's own
// reference (which has no such mock available and must avoid
// `data "aws_caller_identity"` entirely), this file uses `this.account`
// directly.
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import * as iam from "terraconstructs/lib/aws/iam";

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

    // --- DEPLOYER role ---------------------------------------------------
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

    // --- WORKLOAD role -----------------------------------------------------
    // Never given any permission by module/ itself -- every grant below is
    // authored here, by hand, exactly like on hcl_raw/awscdk (not via a
    // grantXxx() call on an imported construct -- see this scenario's own
    // provenance notes for why the v1 reference solution is symmetric
    // across arms rather than exercising the grantXxx-derivation contrast
    // directly here).
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

    workloadRole.attachInlinePolicy(
      new iam.Policy(this, "WorkloadPolicy", {
        statements: [
          new iam.PolicyStatement({
            sid: "ReadAppParameters",
            actions: [
              "ssm:GetParameter",
              "ssm:GetParameters",
              "ssm:GetParametersByPath",
              "ssm:DescribeParameters",
            ],
            resources: [ssmAppParamArnGlob],
          }),
          new iam.PolicyStatement({
            sid: "DecryptSecureStringViaSsm",
            actions: ["kms:Decrypt", "kms:DescribeKey"],
            resources: ["*"],
            condition: [{ test: "StringEquals", variable: "kms:ViaService", values: ["ssm.us-east-1.amazonaws.com"] }],
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
