#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-missing-entirely`, predicted_tier_caught "0" on THIS arm
# and "1" on both Terraform arms.
#
# THE MISTAKE, and the likeliest one an agent actually makes: do exactly what
# the ticket says and nothing else. `objectOwnership` becomes
# `BUCKET_OWNER_ENFORCED`, the now-illegal `accessControl` prop is removed
# (aws-cdk-lib throws at synth if it is left -- `parseOwnershipControls()`,
# bucket.ts:3052 -- so the agent cannot avoid noticing THAT much), the seed's
# L1 `loggingConfiguration` escape hatch is left exactly where it was, and no
# bucket policy replaces the grant that was just switched off. The plan is
# green, the deploy is green, and the log objects stop arriving.
#
# WHAT THIS FIXTURE MUST NOT DO, and the reason is this arm's whole
# contribution to the measurement: reach for `serverAccessLogsBucket`. That L2
# prop makes this mistake UNREACHABLE here --
# `Bucket.allowLogDelivery()` (bucket.ts:3277) writes the replacement
# bucket-policy statement for you the moment you use it, because this
# workspace's cdk.json enables
# `@aws-cdk/aws-s3:serverAccessLogsUseBucketPolicy`. Keeping the seed's escape
# hatch is what an agent who never found that path would do, and it is the only
# way to reproduce the mistake on this arm at all.
#
# Expected verdict: reward 0.0, caught at TIER 0: with no
# `AWS::S3::BucketPolicy` in the template, both
# `destination-bucket-policy-grants-the-logging-service-principal` and
# `destination-bucket-policy-allows-putobject` resolve to ZERO nodes, and
# `contains` requires at least one resolved value.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const accessLogs = new s3.Bucket(this, "AccessLogs", {
      bucketName: "cdktn-bench-application-storage-access-logs",
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_ENFORCED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const appData = new s3.Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    const accessLogsBucket = accessLogs.node.defaultChild as s3.CfnBucket;
    const appDataBucket = appData.node.defaultChild as s3.CfnBucket;

    appDataBucket.loggingConfiguration = {
      destinationBucketName: accessLogsBucket.ref,
      logFilePrefix: "app-data/",
    };
  }
}
TS

exec bash tests/static_tiers.sh
