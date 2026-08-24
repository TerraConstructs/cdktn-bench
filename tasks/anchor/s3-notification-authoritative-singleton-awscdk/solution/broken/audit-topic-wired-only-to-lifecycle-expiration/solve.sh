#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the NEW (round 6) audit-topic-events-cover-a-real-
# delete tier-1 rule: identical to the reference solution except ONE
# argument -- `s3.EventType.LIFECYCLE_EXPIRATION` in place of
# `s3.EventType.OBJECT_REMOVED`. `s3n.SnsDestination` still authors a
# correctly-scoped topic-publish statement (this mistake is about WHICH
# event family is wired, not about scoping), so this fixture passes every
# tier-0 assert and the lambda-permission tier-1 rule -- it fails
# audit_topic_covers_a_real_delete alone: `EventType.LIFECYCLE_EXPIRATION`
# is a first-class aws-cdk-lib enum member (aws-s3/lib/bucket.d.ts,
# pinned 2.263.0), so this is reachable through the SAME idiomatic call
# site the reference solution itself uses, not a fabricated escape hatch.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

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

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(fn),
    );

    // BUG: LIFECYCLE_EXPIRATION, not OBJECT_REMOVED -- passes the tier-0
    // whitelist (a member of the six-literal set) but never fires for an
    // ordinary user-initiated delete. The catch this fixture exists to
    // violate.
    bucket.addEventNotification(
      s3.EventType.LIFECYCLE_EXPIRATION,
      new s3n.SnsDestination(auditTopic),
    );
  }
}
TS

bash tests/static_tiers.sh
