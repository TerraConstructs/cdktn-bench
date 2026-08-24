#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the lambda-permission-not-scoped-to-bucket catch
# (s3-lambda-log-retention's own scoping catch, reused verbatim): the SNS
# half is fully correct (s3n.SnsDestination, which always scopes itself),
# but the Lambda half bypasses `s3n.LambdaDestination` (which always sets
# SourceArn -- see this scenario's own spec.yaml catch description) with a
# minimal custom `IBucketNotificationDestination` that wires the event
# WITHOUT ever calling `fn.addPermission()`, then separately (and
# deliberately) authors an unscoped `lambda.CfnPermission` -- reproducing
# what an agent hand-rolling the permission (or reaching for the L1
# escape hatch) would produce. Tier-0 still passes
# (lambda-permission-principal-is-s3 only checks the principal); reward
# must be 0.0 from tier-1 (lambda-permission-scoped-to-bucket-cfn) alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

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

    const bucket = new s3.Bucket(this, "MediaBucket");

    const fn = new lambda.Function(this, "IngestHandler", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline("exports.handler = async () => {};"),
    });

    const auditTopic = new sns.Topic(this, "AuditTopic");

    // Deliberately no SourceArn -- grants ANY s3.amazonaws.com-principal'd
    // caller, not just this scenario's bucket. The catch this fixture
    // exists to violate.
    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
    });

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new UnscopedLambdaDestination(fn),
    );

    bucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED,
      new s3n.SnsDestination(auditTopic),
    );
  }
}
TS

bash tests/static_tiers.sh
