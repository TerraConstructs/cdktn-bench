#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-not-migrated`, whose predicted_tier_caught is "0" on THIS
# arm and "live" on the two Terraform arms.
#
# THE MISTAKE, identical in substance to the Terraform arms' fixture: ACLs are
# turned off on the access-logs bucket exactly as the ticket asks, the logging
# configuration is left exactly where it was, and a bucket policy IS written --
# it just carries the wrong grant. `delivery.logs.amazonaws.com` is the
# delivery principal CloudWatch Logs / VPC flow logs / Firehose use; S3 server
# access logging uses `logging.s3.amazonaws.com`.
#
# WHY THIS ARM IS CAUGHT STATICALLY AND THE OTHER TWO ARE NOT -- the asymmetry
# is an artifact-shape fact, not an oracle-strictness choice. A CloudFormation
# bucket policy is literal JSON inside the synthesized template, so the service
# principal is right there for a tier-0 jq path to read
# (`destination-bucket-policy-grants-the-logging-service-principal`). On the
# Terraform arms the same document is a computed interpolation over the
# bucket's ARN, plan-time-unknown and therefore absent from the graded
# artifact -- which those arms' own fixture demonstrates mechanically before it
# is allowed to claim it.
#
# NOTE what this fixture must NOT do: reach for `serverAccessLogsBucket`. That
# L2 prop is exactly what makes this mistake unreachable on this arm --
# `Bucket.allowLogDelivery()` writes the correct statement for you -- so the
# fixture keeps the seed's own L1 `loggingConfiguration` escape hatch and
# hand-writes the policy, which is what an agent who never found the L2 path
# would do.
#
# Expected verdict: reward 0.0, caught at tier 0.
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
        principals: [new iam.ServicePrincipal("delivery.logs.amazonaws.com")],
        actions: ["s3:PutObject"],
        resources: [accessLogs.arnForObjects("app-data/*")],
        conditions: {
          ArnLike: { "aws:SourceArn": appData.bucketArn },
        },
      }),
    );

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
