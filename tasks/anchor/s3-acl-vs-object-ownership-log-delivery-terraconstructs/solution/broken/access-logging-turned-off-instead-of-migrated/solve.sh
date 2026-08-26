#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `access-logging-turned-off-instead-of-migrated`, predicted_tier_caught "0".
#
# THE MISTAKE: the other way to make the ACL dependency go away -- remove the
# thing that depended on it. ACLs are switched off on the access-logs bucket
# exactly as the ticket's first sentence asks, the correct replacement grant IS
# written, and the `S3BucketLoggingA` resource is simply dropped -- which is
# what the ticket's second sentence exists to forbid.
#
# Expected verdict: reward 0.0, caught at tier 0 by
# `application-bucket-still-ships-access-logs-under-the-same-prefix` (`eq
# "app-data/"` resolves to zero nodes with no logging resource in the plan, and
# `eq` requires exactly one) and by
# `access-logs-still-target-a-bucket-this-workspace-creates`.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import {
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
        rule: { objectOwnership: "BucketOwnerEnforced" },
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
  }
}
TS

exec bash tests/static_tiers.sh
