import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
import { Construct } from "constructs";

/**
 * REFERENCE SOLUTION (used by solution/solve.sh) -- IAM E2E role
 * derivation: author deployer + workload permissions against real AWS
 * denials.
 *
 * Mirrors ../../iam-e2e-role-hcl-raw/environment/workspace/main.tf's own
 * action/resource-scoping decisions exactly (the account-id-placeholder
 * workaround that arm needs does NOT apply here -- CDK resolves
 * `cdk.Aws.ACCOUNT_ID` via a CloudFormation pseudo-parameter, which needs
 * no data source / no real AWS call at synth time, unlike Terraform's
 * `data "aws_caller_identity"`; see the hcl_raw reference's own comment
 * for that arm-specific gap).
 */
export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const accountId = cdk.Aws.ACCOUNT_ID;
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

    // --- WORKLOAD role -----------------------------------------------------
    // Never given any permission by module/ itself -- every grant below is
    // authored here, by hand, on THIS arm just like on hcl_raw (not via a
    // grantXxx() call on an imported construct -- see this scenario's own
    // provenance notes on why the v1 reference solution is symmetric across
    // arms rather than exercising the grantXxx-derivation contrast directly
    // in this reference; a future revision could redo this half with
    // StringParameter.fromSecureStringParameterAttributes(...).grantRead()
    // + Key.fromKeyArn(...).grantDecrypt() to demonstrate the construct-arm
    // win on THIS specific role for real).
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
            conditions: { StringEquals: { "kms:ViaService": "ssm.us-east-1.amazonaws.com" } },
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
