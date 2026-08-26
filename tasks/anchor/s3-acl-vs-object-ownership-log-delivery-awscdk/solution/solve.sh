#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `s3-acl-vs-object-ownership-log-delivery` (BROWNFIELD, SCHEMA.md §2.7/§2.7.1).
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `lib/scenario-stack.ts` already holds a
# deployed application bucket, a deployed access-logs bucket carrying
# `accessControl: LOG_DELIVERY_WRITE` (CloudFormation's canned
# `AccessControl: LogDeliveryWrite`, which AWS names as the CFN way to express
# the log-delivery-group ACL grant), and the application bucket's
# `loggingConfiguration` wired at L1. The ticket: turn ACLs off on the
# access-logs bucket, keep the logs flowing.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT, AND WHAT THE L2 DOES FOR YOU HERE
# =======================================================================
# `ObjectOwnership.BUCKET_OWNER_ENFORCED` disables ACLs, at which point the
# log-delivery group grant stops carrying delivery and a bucket policy allowing
# `s3:PutObject` to `logging.s3.amazonaws.com` has to carry it instead. On this
# arm that policy is not hand-written: moving the logging wiring from the L1
# escape hatch onto the L2 prop `serverAccessLogsBucket` makes
# `Bucket.allowLogDelivery()` (aws-cdk-lib/aws-s3/lib/bucket.ts:3277) emit it,
# because this workspace's own cdk.json sets
# `@aws-cdk/aws-s3:serverAccessLogsUseBucketPolicy` to true -- principal,
# `s3:PutObject`, `arnForObjects("app-data/*")` and both the `aws:SourceArn`
# and `aws:SourceAccount` conditions AWS documents.
#
# The same L2 also refuses the half-migration outright rather than deploying
# it: leaving `accessControl` in place while setting
# `BUCKET_OWNER_ENFORCED` throws at synth from `parseOwnershipControls()`
# (bucket.ts:3052) -- "objectOwnership must be set to ObjectWriter when
# accessControl is LogDeliveryWrite". That is the interaction between the two
# properties being MODELLED, which is exactly the difference this scenario
# exists to measure against the arms where it is not.
#
# WHY THE LIVE PATH DEPLOYS TWICE. `PutBucketOwnershipControls` refuses
# `BucketOwnerEnforced` while the bucket's ACL still grants anyone but the
# owner (`InvalidBucketAclWithObjectOwnership`), so the ACL is reset to
# `private` in its own deploy first -- AWS's own "Prerequisites for disabling
# ACLs" order. That is a property of the ROLLOUT, not of the answer: the graded
# artifact is the second synth, and nothing in this scenario's oracle asserts
# on how many deploys it took.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the final file, run the same
# tests/static_tiers.sh a real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally run the two real `cdk deploy`s and assert the live
# oracle. `bin/app.ts` is seeded and non-agent-owned; this script never touches
# it.
set -euo pipefail

LIVE="${LIVE:-0}"

mkdir -p lib

# ROLLOUT STEP 1 ONLY -- never graded. Ownership stays `ObjectWriter` (so
# CloudFormation may still set an ACL) and the canned ACL becomes `Private`,
# which clears the log-delivery group grant out of the account.
write_acl_reset() {
  cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const accessLogs = new s3.Bucket(this, "AccessLogs", {
      bucketName: "cdktn-bench-application-storage-access-logs",
      accessControl: s3.BucketAccessControl.PRIVATE,
      objectOwnership: s3.ObjectOwnership.OBJECT_WRITER,
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
}

# THE GRADED ANSWER.
write_solution() {
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

    new s3.Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      serverAccessLogsBucket: accessLogs,
      serverAccessLogsPrefix: "app-data/",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });
  }
}
TS
}

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 1/2: reset the destination bucket's ACL while ACLs are still enabled =="
  write_acl_reset
  npm run build
  npx cdk deploy --require-approval never ScenarioStack
fi

write_solution

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 2/2: disable ACLs; the L2 moves the grant onto a bucket policy =="
  npm run build
  npx cdk deploy --require-approval never ScenarioStack
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
