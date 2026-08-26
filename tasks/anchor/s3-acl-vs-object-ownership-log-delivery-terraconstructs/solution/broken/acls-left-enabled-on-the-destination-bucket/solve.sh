#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `acls-left-enabled-on-the-destination-bucket`, predicted_tier_caught "0".
#
# THE MISTAKE: the half-measure. This fixture does the HARD part correctly --
# it writes the replacement bucket policy granting `s3:PutObject` to
# `logging.s3.amazonaws.com` on the log prefix -- and then leaves Object
# Ownership at `BucketOwnerPreferred`, which reads like "the bucket owner owns
# everything written to it" and is not the same claim: it only changes
# ownership of objects uploaded with the `bucket-owner-full-control` canned
# ACL, and ACLs stay ENABLED
# (docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html).
# The ticket's actual requirement -- stop relying on access control lists -- is
# not met.
#
# Expected verdict: reward 0.0, caught at tier 0 by
# `destination-bucket-ownership-is-bucket-owner-enforced`
# (`set_eq ["BucketOwnerEnforced"]` against a resolved
# `["BucketOwnerPreferred"]`) and, independently, at tier 1 by
# oracles/rego/s3-acl-vs-object-ownership-log-delivery/policy.rego.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import {
  s3BucketLogging,
  s3BucketOwnershipControls,
  s3BucketPolicy,
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
        rule: { objectOwnership: "BucketOwnerPreferred" },
      },
    );

    const appData = new Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      forceDestroy: true,
    });

    new s3BucketPolicy.S3BucketPolicy(this, "AccessLogsPolicy", {
      bucket: accessLogs.bucketName,
      policy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "S3ServerAccessLogsPolicy",
            Effect: "Allow",
            Principal: { Service: "logging.s3.amazonaws.com" },
            Action: ["s3:PutObject"],
            Resource: `${accessLogs.bucketArn}/app-data/*`,
            Condition: {
              ArnLike: { "aws:SourceArn": appData.bucketArn },
            },
          },
        ],
      }),
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
