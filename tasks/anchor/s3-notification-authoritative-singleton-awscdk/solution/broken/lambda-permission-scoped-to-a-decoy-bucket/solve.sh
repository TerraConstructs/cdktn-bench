#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 13 (2026-08-23) -- SAME-TYPE / WRONG-INSTANCE, awscdk twin.
#
# This closure started on the TF-shaped arms (it became possible there once
# `oracle.hcl_traversal` let the policy resolve a `local.` symbol to its
# referent). It is mirrored here because this arm had EXACTLY the same
# hole -- `scoped_to_a_bucket` was a TYPE test, "does SourceArn name AN
# AWS::S3::Bucket in this template" -- and closing it on two arms out of
# three would have converted a closed gap into a NEW one-sided cross-arm
# strictness difference, which DECISIONS.md Amendment 29 §4 forbids and
# which is the exact failure class rounds 7-12 of this scenario kept
# re-opening.
#
# THE DEFECT. Two buckets exist. The notification resource is on
# `MediaBucket`; the Lambda invoke permission's `sourceArn` is
# `decoy.bucketArn`. S3 therefore never invokes the function: the grant
# names a bucket that sends no events, and the bucket that does send them
# has no permission. This is an ordinary one-token slip, not an escape
# hatch -- the L1 `CfnPermission` here exists only so the fixture can own
# the `sourceArn`, exactly as its sibling
# `lambda-permission-scoped-to-a-different-bucket` does.
#
# WHY IT WAS INVISIBLE. `Fn::GetAtt: [DecoyBucket..., Arn]` names an
# AWS::S3::Bucket declared in this template, so every type test passes.
# Note that the sibling fixture does NOT cover this: its `sourceArn` is a
# hardcoded literal string naming no template resource at all, which is a
# different rule's job.
#
# THE FIX. `Custom::S3BucketNotifications`'s own `Properties.BucketName`
# names the wired bucket's logical id; `scoped_to_a_bucket` now requires
# SourceArn to name THAT id. Keyed on logical id -- the CFN analogue of
# the plan address the TF policy joins on -- never on a physical name.
#
# Everything else is correct. Tier-0 still passes; reward must be 0.0 from
# tier-1 (lambda-permission-scoped-to-bucket-cfn) alone.
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

    // A second, real bucket in this same stack. Nothing is wrong with it
    // existing -- what is wrong is the grant below naming it.
    const decoy = new s3.Bucket(this, "DecoyBucket");

    // Deliberately scoped to the DECOY bucket. This resolves cleanly to
    // an AWS::S3::Bucket this stack creates -- it is just the WRONG ONE,
    // which is precisely why every type-only rule accepted it.
    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: decoy.bucketArn,
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
