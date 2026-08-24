#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 ARM-PARITY FIX (2026-08-23). This is the THIRD spelling of the
# lambda-permission-not-scoped-to-bucket catch, and the one that survived
# the round-7 fix: not an OMITTED SourceArn (fixture
# lambda-permission-not-scoped-to-bucket) and not a bare literal ARN
# (fixture lambda-permission-scoped-to-a-different-bucket), but the SAME
# unrelated bucket name composed through `cdk.Fn.sub`. cfn-guard 3.2.0
# cannot parse a logical id out of an `Fn::Sub` template string, so the
# round-7 rules could only ask whether SourceArn was an intrinsic rather
# than a literal -- and an `Fn::Sub` IS an intrinsic. Verified by
# execution at round 10 against the retired policy.guard: this exact
# template scored cfn-guard PASS on awscdk while its hcl_raw counterpart
# (`source_arn = "arn:${data.aws_partition.current.partition}:s3:::some-
# totally-unrelated-bucket"`, whose `.references` list holds a data source
# and no aws_s3_bucket) scored 0.0 -- the same arm-parity break round 7
# closed for the other two spellings, still open for this one.
#
# It is closed by the tier-1 engine port (oracles/rego-cfn/s3-notification-
# authoritative-singleton/policy.rego, `sub_tokens`): Rego can read the
# `${...}` tokens, so what an Fn::Sub NAMES is now type-checked exactly
# like a Ref or an Fn::GetAtt. This fixture is what falsifies that clause;
# without it the widened rule would be an untested rule.
#
# Everything else is correct (one authoritative notification resource,
# both event families wired, SNS half fully correct). Tier-0 still passes
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

    // BUG: the ARN is composed with Fn::Sub so it LOOKS parameterised --
    // the partition really is substituted -- but the bucket name is a
    // hardcoded literal naming a bucket this stack does not create. The
    // grant is not tied to this stack's bucket at all. Synthesizes to
    //   SourceArn: {"Fn::Sub": "arn:${AWS::Partition}:s3:::some-totally-unrelated-bucket"}
    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: cdk.Fn.sub("arn:${AWS::Partition}:s3:::some-totally-unrelated-bucket"),
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
