#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the only-one-of-the-two-events-wired catch: wires the
# Product half only (upload -> transcode, correctly scoped via
# s3n.LambdaDestination) and never creates the SNS topic or any
# ObjectRemoved wiring at all -- the Compliance half of the ticket is
# dropped entirely. Reward must be 0.0 from tier-0 alone (sns-topic-exists
# and object-removed-notification-targets-a-topic both resolve 0 nodes).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
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

    // BUG: no SNS topic, no ObjectRemoved wiring -- the Compliance ask
    // was never attempted.
    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(fn),
    );
  }
}
TS

bash tests/static_tiers.sh
