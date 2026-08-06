#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the s3-lambda-invoke-permission-scoped catch: the
# `lambdaPermission.LambdaPermission` L1 resource grants principal
# s3.amazonaws.com with NO sourceArn at all (account-wide, not scoped to
# this scenario's bucket). Tier-0 still passes (bucket/function/log-group/
# notification/principal are all correct); reward must be 0.0 from tier-1
# (policy.rego) alone.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, RetentionDays, cloudwatch } from "terraconstructs/lib/aws";
import {
  s3Bucket,
  iamRole,
  lambdaFunction,
  lambdaPermission,
  s3BucketNotification,
} from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new s3Bucket.S3Bucket(this, "UploadBucket", {
      provider: this.provider,
      bucket: "cdktn-bench-s3-lambda-log-retention-upload",
    });

    const role = new iamRole.IamRole(this, "HandlerRole", {
      provider: this.provider,
      name: "cdktn-bench-s3-lambda-log-retention-handler-role",
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "lambda.amazonaws.com" },
            Action: "sts:AssumeRole",
          },
        ],
      }),
    });

    const fn = new lambdaFunction.LambdaFunction(this, "Handler", {
      provider: this.provider,
      functionName: "cdktn-bench-s3-lambda-log-retention-handler",
      role: role.arn,
      handler: "index.handler",
      runtime: "nodejs22.x",
      filename: "function.zip",
    });

    new cloudwatch.LogGroup(this, "HandlerLogGroup", {
      logGroupName: `/aws/lambda/${fn.functionName}`,
      retention: RetentionDays.TWO_WEEKS,
    });

    // Deliberately no sourceArn -- grants ANY s3.amazonaws.com-principal'd
    // caller, not just this scenario's bucket. The catch this fixture
    // exists to violate.
    new lambdaPermission.LambdaPermission(this, "AllowS3Invoke", {
      provider: this.provider,
      statementId: "AllowS3Invoke",
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
    });

    new s3BucketNotification.S3BucketNotification(this, "UploadNotification", {
      provider: this.provider,
      bucket: bucket.id,
      lambdaFunction: [
        {
          lambdaFunctionArn: fn.arn,
          events: ["s3:ObjectCreated:Put"],
        },
      ],
    });
  }
}
TS

bash tests/static_tiers.sh
