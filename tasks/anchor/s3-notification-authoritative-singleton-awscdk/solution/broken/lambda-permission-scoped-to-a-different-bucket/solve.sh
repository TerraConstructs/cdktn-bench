#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop -- the same mechanism
# `inline-sns-topic-policy-not-scoped-to-bucket` uses on the hcl_raw arm
# to prove an alternate expression of an already-declared mistake is
# caught too, rather than only the one spelling a catch name happens to
# describe.
#
# ROUND-7 ARM-PARITY FIX (2026-08-22). This is the SECOND spelling of the
# lambda-permission-not-scoped-to-bucket catch: not an OMITTED SourceArn
# (that is the sibling fixture next to this one) but a HARDCODED literal
# one naming a different, unrelated bucket. An adversarial verifier proved
# by execution that this exact shape scored reward 1.0 on awscdk while
# scoring 0.0 on hcl_raw, because the awscdk-side rule was a bare
# `Properties.SourceArn EXISTS` presence check. Round 7 replaced that with
# a four-rule cfn-guard graph-edge mirror of the TF-shaped arms'
# `references_bucket`; ROUND 10 (2026-08-23) replaced cfn-guard itself,
# because it could express neither the `Fn::Sub` spelling of this same
# defect nor a per-permission join. The rule now lives in
# oracles/rego-cfn/s3-notification-authoritative-singleton/policy.rego
# (`oracle.awscdk_tier1_engine: rego`; policy.guard is deleted), and this
# fixture is one of the four that falsify it: without them the widened
# rule would be an untested rule.
#
# Everything else is correct (single authoritative notification resource,
# both event types wired, SNS half fully correct including its topic
# policy). Tier-0 still passes (lambda-permission-principal-is-s3 only
# reads the principal, which is right here); reward must be 0.0 from
# tier-1 (lambda-permission-scoped-to-bucket-cfn / the guard rule
# permission_scoped_to_bucket) alone.
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

    // Deliberately a HARDCODED literal ARN naming a bucket this stack
    // does not create -- the grant is not tied to this stack's bucket at
    // all. The catch this fixture exists to violate.
    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: "arn:aws:s3:::some-totally-unrelated-bucket",
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
