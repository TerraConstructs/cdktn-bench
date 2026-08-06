#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the s3-lambda-invoke-permission-scoped catch: the
# Lambda permission grants principal s3.amazonaws.com with NO SourceArn at
# all (account-wide, not scoped to this scenario's bucket). Tier-0 still
# passes (bucket/function/log-group/notification/principal are all
# correct); reward must be 0.0 from tier-1 (policy.guard) alone.
#
# CDK's own `s3n.LambdaDestination` helper cannot produce this mistake (it
# always sets sourceArn -- see the catch's own description), so this
# fixture deliberately bypasses it with a minimal custom
# IBucketNotificationDestination plus a manually-authored CfnPermission,
# reproducing what an agent using the L1 escape hatch (or simply forgetting
# to scope a hand-rolled permission) would produce.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";

// Minimal notification destination that wires the event WITHOUT ever
// adding a Lambda permission -- the permission below is authored
// separately (and deliberately left unscoped), so exactly one
// AWS::Lambda::Permission resource exists in the synthesized template.
class UnscopedLambdaDestination implements s3.IBucketNotificationDestination {
  constructor(private readonly fn: lambda.IFunction) {}
  bind(_scope: Construct, _bucket: s3.IBucket): s3.BucketNotificationDestinationConfig {
    return {
      type: s3.BucketNotificationDestinationType.LAMBDA,
      arn: this.fn.functionArn,
    };
  }
}

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const bucket = new s3.Bucket(this, "UploadBucket");

    const fn = new lambda.Function(this, "Handler", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline("exports.handler = async () => {};"),
    });

    new logs.LogGroup(this, "HandlerLogGroup", {
      logGroupName: `/aws/lambda/${fn.functionName}`,
      retention: logs.RetentionDays.TWO_WEEKS,
    });

    // Deliberately no SourceArn -- grants ANY s3.amazonaws.com-principal'd
    // caller, not just this scenario's bucket. The catch this fixture
    // exists to violate.
    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
    });

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED_PUT,
      new UnscopedLambdaDestination(fn),
    );
  }
}
TS

bash tests/static_tiers.sh
