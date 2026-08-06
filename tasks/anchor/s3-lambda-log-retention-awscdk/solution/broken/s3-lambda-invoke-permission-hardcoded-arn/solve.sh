#!/usr/bin/env bash
# EXTRA, non-catch-named negative fixture (gates/oracle_falsifiability.py's
# "extra, non-catch-named negative fixtures" mechanism) -- added by the
# "s3-lambda-log-retention / oracle-equivalence (tier-1 SourceArn scoping)"
# fix (benchmark-integrity review, 2026-08-06). The PREVIOUS
# oracles/cfn-guard/s3-lambda-log-retention/policy.guard only checked
# `Properties.SourceArn EXISTS` -- present-with-ANY-value -- which this
# fixture (a hardcoded, unrelated bucket's literal ARN, present but never
# referencing the bucket this scenario actually creates) demonstrated
# passes that rule (rc=0, reward 1.0) even though it is the exact
# "wrong/hardcoded resource" violation oracle.intent's own words rule out
# ("scoped to this specific bucket ... no unrelated/hardcoded ARN"). The
# fixed rule (permission_source_arn_resolves_via_getatt, requiring
# `Properties.SourceArn.'Fn::GetAtt' EXISTS`) correctly rejects this
# fixture, since a hardcoded string literal is never an `Fn::GetAtt`
# intrinsic. Must score reward=0.0.
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
// separately, with a hardcoded SourceArn naming a completely unrelated
// bucket (present, but not scoped to the bucket this scenario creates).
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

    // BUG: SourceArn is present (so the OLD "EXISTS" rule passed this),
    // but it's a hardcoded literal ARN for a totally unrelated bucket --
    // never a reference to `bucket` at all.
    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: "arn:aws:s3:::some-totally-unrelated-bucket",
    });

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED_PUT,
      new UnscopedLambdaDestination(fn),
    );
  }
}
TS

bash tests/static_tiers.sh
