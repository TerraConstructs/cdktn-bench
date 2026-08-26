#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `s3-acl-vs-object-ownership-log-delivery` (BROWNFIELD, SCHEMA.md §2.7/§2.7.1).
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `lib/scenario-stack.ts` already holds a
# deployed application bucket, a deployed access-logs bucket whose Object
# Ownership is `ObjectWriter` and whose ACL is the canned `log-delivery-write`
# grant, and the logging configuration shipping the first bucket's server
# access logs to the second under `app-data/`. The ticket: turn ACLs off on the
# access-logs bucket, keep the logs flowing.
#
# WHY THIS ARM LOOKS LIKE THIS. terraconstructs 0.2.13's `storage.Bucket` has
# no ownership-controls prop, no ACL prop and no server-access-logs prop
# (enumerated from the pinned package's own `BucketProps` -- see this
# scenario's spec header), so all three live at L1 through
# `@cdktn/provider-aws`. There IS a real L2 for the FIX --
# `IBucket.addToResourcePolicy` / `storage.BucketPolicy` -- and it is equally
# accepted by this scenario's oracle, which asserts nothing about the policy's
# SHAPE on this arm. The L1 `S3BucketPolicy` is used here on purpose, for a
# reason that belongs to the FIXTURES rather than to the solution: the
# `log-delivery-grant-not-migrated` negative fixture has to demonstrate,
# mechanically and offline, that the graded artifact cannot tell a correct
# policy from an incorrect one, and it can only do that honestly if the
# reference and the fixture compose their policy documents the same way.
# `addToResourcePolicy` routes through terraconstructs' `PolicyDocument`, which
# emits a `data "aws_iam_policy_document"` whose statement literals DO survive
# into `.configuration`; a `JSON.stringify` document interpolating the bucket's
# ARN token does not, exactly like the hcl_raw arm's `jsonencode`.
#
# WHAT MAKES THE CORRECT ANSWER CORRECT
# =====================================
# `BucketOwnerEnforced` disables ACLs, and AWS is explicit that once it does,
# the log-delivery group grant "no longer affect[s] permissions" and the bucket
# policy must grant `s3:PutObject` to `logging.s3.amazonaws.com` instead
# (docs.aws.amazon.com/AmazonS3/latest/userguide/enable-server-access-logging.html),
# scoped with the documented `ArnLike aws:SourceArn` confused-deputy condition.
#
# WHY THE LIVE PATH DEPLOYS TWICE. `PutBucketOwnershipControls` refuses
# `BucketOwnerEnforced` while the bucket's ACL still grants anyone but the
# owner (`InvalidBucketAclWithObjectOwnership`), and removing an
# `aws_s3_bucket_acl` from a Terraform configuration is a STATE-ONLY delete
# that leaves the grant in the account (hashicorp/aws issue #26164). Resetting
# the ACL to `private` in its own apply first is AWS's own documented order. It
# is a property of the ROLLOUT, not of the answer: the graded artifact is the
# second synth.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the final file, run the same
# tests/static_tiers.sh a real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally export CDKTN_BENCH_LIVE=1 (which strips the seeded
# app's dummy credentials and mock-STS endpoint) and run the two real
# `cdktn deploy`s. The positional argument is the STACK id -- the spec's
# `workspace_id`, `application-storage` -- not the spec's `id`.
set -euo pipefail

LIVE="${LIVE:-0}"

mkdir -p lib

# ROLLOUT STEP 1 ONLY -- never graded. Ownership stays `ObjectWriter`, so
# `PutBucketAcl` is still legal; this apply clears the log-delivery group grant
# out of the account so step 2's `PutBucketOwnershipControls` is allowed.
write_acl_reset() {
  cat > lib/scenario-stack.ts <<'TS'
import {
  s3BucketAcl,
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

    const accessLogsOwnership =
      new s3BucketOwnershipControls.S3BucketOwnershipControls(
        this,
        "AccessLogsOwnership",
        {
          bucket: accessLogs.bucketName,
          rule: { objectOwnership: "ObjectWriter" },
        },
      );

    new s3BucketAcl.S3BucketAcl(this, "AccessLogsAcl", {
      bucket: accessLogs.bucketName,
      acl: "private",
      dependsOn: [accessLogsOwnership],
    });

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
}

# THE GRADED ANSWER.
write_solution() {
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

    new s3BucketLogging.S3BucketLoggingA(this, "AppDataLogging", {
      bucket: appData.bucketName,
      targetBucket: accessLogs.bucketName,
      targetPrefix: "app-data/",
    });
  }
}
TS
}

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 1/2: reset the destination bucket's ACL while ACLs are still enabled =="
  export CDKTN_BENCH_LIVE=1
  write_acl_reset
  npx tsc -p tsconfig.json
  npx cdktn deploy --auto-approve application-storage
fi

write_solution

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 2/2: disable ACLs and carry the grant on a bucket policy =="
  npx tsc -p tsconfig.json
  npx cdktn deploy --auto-approve application-storage
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
