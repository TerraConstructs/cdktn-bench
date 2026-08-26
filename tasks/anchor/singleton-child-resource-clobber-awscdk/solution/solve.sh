#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `singleton-child-resource-clobber` (BROWNFIELD, SCHEMA.md §2.7 / §2.7.1,
# DECISIONS.md Amendments 28 and 31). Regenerating this scenario will NOT
# overwrite this file (destructive-safe rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `lib/scenario-stack.ts` already holds the
# deployed storage configuration for one archive bucket, including another
# team's rule deleting `logs/` objects after 30 days. The task is ONE change:
# also move `exports/` objects to Glacier Instant Retrieval after 90 days, and
# roll it out.
#
# THIS ARM CANNOT REACH THE HEADLINE MISTAKE, AND THAT IS THE MEASUREMENT.
# =======================================================================
# On CloudFormation a bucket's storage rules are the `LifecycleConfiguration`
# PROPERTY of the one `AWS::S3::Bucket` resource -- there is no child resource
# to declare twice, and `s3.Bucket`'s `lifecycleRules` / `addLifecycleRule`
# both append to one array on one construct. So the only edit available on this
# arm is the correct one: append a rule to the existing list. Read the hcl_raw
# reference solution next to this one, and its
# `solution/broken/exports-rule-added-as-a-second-child-resource/` fixture, for
# the shape this arm is structurally immune to -- two
# `aws_s3_bucket_lifecycle_configuration` resources plan green, apply green,
# and silently leave only one of the two requirements in effect.
#
# What this arm is NOT immune to, and what its own two broken fixtures cover:
# dropping the other team's rule while re-authoring the array
# (`existing-log-expiry-rule-dropped`), and adding the new rule with
# `enabled: false` (`exports-rule-added-but-not-enabled`). A TypeScript array
# literal is exactly as easy to overwrite as an HCL block.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally run a real `cdk deploy` and assert the live oracle. This
# arm's bin/app.ts always uses ambient credentials, so there is no offline/live
# switch to export (unlike the TF-shaped arms' provider bootstrap).
set -euo pipefail

LIVE="${LIVE:-0}"

cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as s3 from "aws-cdk-lib/aws-s3";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    new s3.Bucket(this, "Reports", {
      bucketName: "cdktn-bench-reports-archive",
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      lifecycleRules: [
        {
          id: "expire-raw-logs",
          enabled: true,
          prefix: "logs/",
          expiration: cdk.Duration.days(30),
        },
        {
          id: "archive-exports",
          enabled: true,
          prefix: "exports/",
          transitions: [
            {
              storageClass: s3.StorageClass.GLACIER_INSTANT_RETRIEVAL,
              transitionAfter: cdk.Duration.days(90),
            },
          ],
        },
      ],
    });
  }
}
TS

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real cdk deploy against this account =="
  npm run build
  npx cdk deploy --require-approval never ScenarioStack
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
