#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 CROSS-ARM CONTROL (2026-08-23). The awscdk twin of the hcl_raw
# fixture of the same name: the invoke permission is scoped to the AUDIT
# TOPIC's ARN, reached through the same DRY const-hoist an author would
# naturally write on this arm. It is the arm this pair compares AGAINST --
# it scored 0.0 here all along, while its hcl_raw twin scored 1.0 until
# round 10 narrowed that arm's `local.`/`var.` tolerance by provenance.
# Shipping both keeps the agreement falsified by `make falsifiability` on
# every run instead of asserted once in a header.
#
# On this arm the const disappears at synth time and the template still
# carries `SourceArn: {"Ref": <AuditTopic logical id>}`, so
# oracles/rego-cfn/s3-notification-authoritative-singleton/policy.rego
# resolves it to an AWS::SNS::Topic and denies -- quoting that logical id
# and its Type rather than asserting a diagnosis (Amendment 29 §6 RULING
# 3).
#
# Everything else is correct. Tier-0 still passes
# (lambda-permission-principal-is-s3 reads only the principal, which is
# right here); reward must be 0.0 from tier-1
# (lambda-permission-scoped-to-bucket-cfn) alone.
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
// separately (and deliberately mis-scoped), so exactly one
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

    // Both ARNs hoisted, exactly as an author writing DRY code would.
    const mediaBucketArn = bucket.bucketArn;
    const auditTopicArn = auditTopic.topicArn;

    // BUG: `auditTopicArn`, one token off the correct `mediaBucketArn` --
    // the grant is scoped to the audit topic's ARN, which no S3
    // invocation ever matches.
    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: auditTopicArn,
    });

    // `mediaBucketArn` is referenced so the hoist is real code, not an
    // unused binding the compiler would flag.
    new cdk.CfnOutput(this, "MediaBucketArn", { value: mediaBucketArn });

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
