#!/usr/bin/env bash
# Broken fixture for catch: stack-ships-a-deployment-time-function
# (anti-L2, applies_to: [awscdk] only). Reproduces exactly ONE mistake
# relative to solution/solve.sh: swaps the hand-wired L1 escape hatch for
# aws-cdk-lib's own IDIOMATIC, RECOMMENDED L2 API --
# `bucket.addEventNotification(EventType.OBJECT_CREATED_PUT, new
# s3n.LambdaDestination(fn))` -- which is exactly what
# s3-lambda-log-retention-awscdk's own reference solution uses (that
# scenario has no platform constraint forbidding it). Nothing about
# calling it looks wrong; it deploys and plans clean. It lazily provisions
# aws-cdk-lib's stack-wide `Custom::S3BucketNotifications` handler
# function plus its execution role -- violating this scenario's own
# platform constraint ("no helpers, no deployment-time functions").
#
# Expected: reward 0.0. Caught DOUBLY, at tier 0 both times:
#   - exactly-one-lambda-function: resolves 2 nodes (Processor AND the
#     BucketNotificationsHandler) -- `eq`'s own ambiguity rule fails any
#     resolution of >1 nodes outright (SCHEMA.md §4.2).
#   - no-deployment-time-custom-resource: the handler's own resource has
#     Type "Custom::S3BucketNotifications", matching the forbidden
#     "^Custom::" prefix.
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

    const bucket = new s3.Bucket(this, "ClaimsBucket");

    const fn = new lambda.Function(this, "Processor", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline("exports.handler = async () => {};"),
    });

    // MISTAKE: the idiomatic L2 notification API. Correct-looking,
    // recommended by aws-cdk-lib's own docs, and forbidden by this
    // scenario's platform constraint -- it lazily provisions a SECOND
    // Lambda function (the BucketNotificationsHandler custom-resource
    // backing function) plus its execution role.
    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED_PUT,
      new s3n.LambdaDestination(fn),
    );
  }
}
TS

bash tests/static_tiers.sh
