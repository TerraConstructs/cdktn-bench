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
# THIS ARM CANNOT REACH THE HEADLINE MISTAKE THROUGH ITS OWN L2, AND THAT IS
# THE MEASUREMENT.
# =========================================================================
# `storage.Bucket` creates its `S3BucketLifecycleConfiguration` child exactly
# once, inside a single `if (props.lifecycleRules)` guard, from a CONSTRUCTOR
# prop -- there is no `addLifecycleRule()` method on this arm at all. So the
# only idiomatic edit is to extend the array that is already there. Read the
# hcl_raw reference solution next to this one, and its
# `solution/broken/exports-rule-added-as-a-second-child-resource/` fixture, for
# the shape this arm would have to abandon its own L2 to express.
#
# ARM-SHAPE NOTE (verified against the pinned package, not assumed): this arm's
# `LifecycleConfigurationRule` is generated from the L1 schema, so `filter`,
# `expiration` and `transition` are ARRAYS of L1 structs and `enabled` is a
# boolean that the construct maps to the L1's `status` string. Its `id` is
# REQUIRED, unlike aws-cdk-lib's, which is why every rule on every arm of this
# scenario carries an explicit id.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally export CDKTN_BENCH_LIVE=1 so the generator-owned
# app/main.ts drops its dummy credentials and mock-STS endpoint, run a real
# `cdktn deploy`, and assert the live oracle.
set -euo pipefail

LIVE="${LIVE:-0}"

cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { Bucket } from "terraconstructs/lib/aws/storage";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new Bucket(this, "Reports", {
      bucketName: "cdktn-bench-reports-archive",
      forceDestroy: true,
      lifecycleRules: [
        {
          id: "expire-raw-logs",
          enabled: true,
          filter: [{ prefix: "logs/" }],
          expiration: [{ days: 30 }],
        },
        {
          id: "archive-exports",
          enabled: true,
          filter: [{ prefix: "exports/" }],
          transition: [{ days: 90, storageClass: "GLACIER_IR" }],
        },
      ],
    });
  }
}
TS

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real cdktn deploy against this account =="
  export CDKTN_BENCH_LIVE=1
  npx tsc -p tsconfig.json
  # The positional argument is the STACK id -- app/main.ts constructs
  # `new ScenarioStack(app, "reports-archive", ...)`, i.e. the spec's
  # `workspace_id`, NOT its `id`. Naming the spec id here names a stack that
  # does not exist; that was a real shipped bug on the template scenario.
  npx cdktn deploy --auto-approve reports-archive
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
