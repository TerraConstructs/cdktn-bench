#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-missing-entirely`, predicted_tier_caught "1" on this arm.
#
# THE MISTAKE, and the likeliest one an agent actually makes: do exactly what
# the ticket says and nothing else. Object Ownership on the access-logs bucket
# becomes the bucket-owner-enforced setting, the now-inert `S3BucketAcl` is
# deleted, the logging configuration is left untouched, and NO bucket policy
# replaces the grant that was just switched off. terraconstructs 0.2.13's
# `storage.Bucket` models neither ownership controls nor server access logging,
# so nothing in this arm's L2 surface even hints that the two are connected.
# Nothing complains: `PutBucketLogging` is never re-issued because the logging
# configuration did not change, the plan is green, the deploy is green, and the
# log objects stop arriving hours later.
#
# Expected verdict: reward 0.0, caught at TIER 1 by
# oracles/rego/s3-acl-vs-object-ownership-log-delivery/policy.rego's "declares
# no aws_s3_bucket_policy" rule. NOT caught at tier 0, on purpose: every tier-0
# assert this arm declares (the log prefix literal, and the logging resource's
# `target_bucket` reference) is still satisfied by this file.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import {
  s3BucketLogging,
  s3BucketOwnershipControls,
} from "@cdktn/provider-aws";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { Bucket } from "terraconstructs/lib/aws/storage";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const accessLogs = new Bucket(this, "AccessLogs", {
      bucketName: "cdktn-bench-application-storage-access-logs",
      forceDestroy: true,
    });

    new s3BucketOwnershipControls.S3BucketOwnershipControls(
      this,
      "AccessLogsOwnership",
      {
        bucket: accessLogs.bucketName,
        rule: { objectOwnership: "BucketOwnerEnforced" },
      },
    );

    const appData = new Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      forceDestroy: true,
    });

    new s3BucketLogging.S3BucketLoggingA(this, "AppDataLogging", {
      bucket: appData.bucketName,
      targetBucket: accessLogs.bucketName,
      targetPrefix: "app-data/",
    });
  }
}
TS

exec bash tests/static_tiers.sh
