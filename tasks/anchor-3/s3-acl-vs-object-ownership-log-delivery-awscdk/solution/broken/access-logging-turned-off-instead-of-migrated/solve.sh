#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `access-logging-turned-off-instead-of-migrated`, predicted_tier_caught "0".
#
# THE MISTAKE: the other way to make the ACL dependency go away -- remove the
# thing that depended on it. ACLs are switched off on the access-logs bucket
# exactly as the ticket's first sentence asks, the correct replacement grant IS
# written, and the application bucket's `loggingConfiguration` is simply
# dropped -- which is what the ticket's second sentence exists to forbid.
#
# Expected verdict: reward 0.0, caught at tier 0 by
# `application-bucket-still-ships-access-logs-under-the-same-prefix` (`eq
# "app-data/"` resolves to zero nodes with no LoggingConfiguration in the
# template, and `eq` requires exactly one) and by
# `access-logs-still-declare-a-destination-bucket`.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as iam from "aws-cdk-lib/aws-iam";
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

    accessLogs.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "S3ServerAccessLogsPolicy",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ServicePrincipal("logging.s3.amazonaws.com")],
        actions: ["s3:PutObject"],
        resources: [accessLogs.arnForObjects("app-data/*")],
        conditions: {
          ArnLike: { "aws:SourceArn": appData.bucketArn },
        },
      }),
    );
  }
}
TS

exec bash tests/static_tiers.sh
