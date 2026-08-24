#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 (2026-08-23). Falsifies the tier-1 FAIL-CLOSED companion rule
# ("an AWS::S3::Bucket exists, but no AWS::Lambda::Permission with
# Principal s3.amazonaws.com exists anywhere in this template") in
# oracles/rego-cfn/s3-notification-authoritative-singleton/policy.rego,
# which no fixture exercised before -- an unfalsified rule is an untested
# rule. The bucket's ObjectCreated event is wired straight at the function
# ARN through a hand-rolled destination that never calls
# `fn.addPermission()`, so S3 is authorised to invoke nothing at all and
# the notification silently never fires in production.
#
# HONEST NOTE ON TIER ATTRIBUTION, because this fixture cannot isolate its
# rule and saying otherwise would be false: with zero permissions in the
# template, tier-0's `lambda-permission-principal-is-s3` (op `eq`, which
# requires EXACTLY ONE resolved node) also fails, so both tiers reject
# this artifact. That is a property of the scenario, not a gap: every
# artifact that can trigger the fail-closed rule necessarily resolves that
# tier-0 path to zero nodes. The rule is still genuinely exercised -- the
# tier-1 deny set is non-empty and carries exactly this message, proven by
# direct `opa eval` and recorded in policy.rego's own ROUND-10
# verification list. It is an extra fixture precisely so that
# gates/oracle_falsifiability.py checks reward only (0.0), with no
# predicted_tier_caught claim attached to it.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

// Wires the event at the function ARN and NEVER adds a Lambda permission.
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

    // BUG: no lambda.CfnPermission, and no s3n.LambdaDestination either --
    // nothing in this template lets S3 invoke the function.
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
