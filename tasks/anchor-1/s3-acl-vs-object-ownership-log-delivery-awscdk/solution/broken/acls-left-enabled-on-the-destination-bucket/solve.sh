#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `acls-left-enabled-on-the-destination-bucket`, predicted_tier_caught "0".
#
# THE MISTAKE: the half-measure. Everything else is the reference solution --
# the logging wiring moves onto the L2 prop, so `Bucket.allowLogDelivery()`
# writes the correct `logging.s3.amazonaws.com` bucket-policy grant -- and then
# Object Ownership is left at `BucketOwnerPreferred`, which reads like "the
# bucket owner owns everything written to it" and is not the same claim: it
# only changes ownership of objects uploaded with the
# `bucket-owner-full-control` canned ACL, and ACLs stay ENABLED
# (docs.aws.amazon.com/AmazonS3/latest/userguide/about-object-ownership.html).
# The ticket's actual requirement -- stop relying on access control lists -- is
# not met.
#
# Expected verdict: reward 0.0, caught at tier 0 by
# `destination-bucket-ownership-is-bucket-owner-enforced`
# (`set_eq ["BucketOwnerEnforced"]` against a resolved
# `["BucketOwnerPreferred"]`) and, independently, at tier 1 by
# oracles/cfn-guard/s3-acl-vs-object-ownership-log-delivery/policy.guard.
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
      objectOwnership: s3.ObjectOwnership.BUCKET_OWNER_PREFERRED,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    new s3.Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      serverAccessLogsBucket: accessLogs,
      serverAccessLogsPrefix: "app-data/",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
  }
}
TS

exec bash tests/static_tiers.sh
