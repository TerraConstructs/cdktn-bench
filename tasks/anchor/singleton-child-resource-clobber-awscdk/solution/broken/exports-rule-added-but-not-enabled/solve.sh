#!/usr/bin/env bash
# NEGATIVE fixture -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `exports-rule-added-but-not-enabled`
# (specs/singleton-child-resource-clobber.yaml). Must score reward 0.0.
#
# THE MISTAKE. The new rule is authored correctly in every value -- right
# prefix, right storage class, right day count -- and left switched off
# (`enabled: false`, which CDK renders as `"Status": "Disabled"`). Nothing ever
# moves to Glacier and nothing errors.
#
# THIS IS THE FIXTURE THAT FALSIFIES THIS ARM'S TIER-1 POLICY
# (oracles/cfn-guard/singleton-child-resource-clobber/policy.guard), so it must
# fail there and NOWHERE else: every tier-0 assert reads a VALUE, and every
# value here is correct. Checked mechanically below -- a 0.0 earned at tier 0
# would leave the cfn-guard rule unexercised the moment it was written, which
# is exactly the gap generator/check_tier1_coverage.py exists to close. If the
# check does not hold, this fixture DELETES /logs/verifier/reward.txt so the
# falsifiability gate goes loud instead of banking an accidental 0.0.
set -uo pipefail

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
          enabled: false,
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

LOG=/tmp/singleton-child-resource-clobber-tier1.log
bash tests/static_tiers.sh 2>&1 | tee "$LOG"

proof_failed() {
  echo "FIXTURE SELF-PROOF FAILED: $1" >&2
  rm -f /logs/verifier/reward.txt
  exit 1
}

grep -q '== summary: tier0_pass=' "$LOG" \
  || proof_failed "static_tiers.sh never reached its summary line -- the build or the synth is broken, so nothing here is evidence about this artifact"

grep -q '== summary: tier0_pass=1 ' "$LOG" \
  || proof_failed "tier 0 did not pass -- every value in this artifact is correct, so a tier-0 failure means this fixture is scoring 0.0 for some other reason and leaves the tier-1 policy unexercised"

grep -q 'tier1_status=FAIL' "$LOG" \
  || proof_failed "tier 1 did not FAIL -- the un-enabled-rule policy is what this fixture exists to falsify (a SKIPPED_STUB/TOOL_MISSING status is a run-invalidating condition, not proof)"

echo "FIXTURE SELF-PROOF OK: tier 0 passes on this artifact and only the tier-1 policy denies it"
exit 0
