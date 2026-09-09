#!/usr/bin/env bash
# NEGATIVE fixture -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `exports-rule-added-but-not-enabled`
# (specs/singleton-child-resource-clobber.yaml). Must score reward 0.0.
#
# THE MISTAKE. The new rule is authored correctly in every value -- right
# prefix, right storage class, right day count -- and left switched off
# (`enabled: false`, which this arm's `storage.Bucket` maps to the L1's
# `status = "Disabled"`). Nothing ever moves to Glacier and nothing errors.
#
# THIS IS THE FIXTURE THAT FALSIFIES THE TIER-1 POLICY on this arm
# (oracles/rego/singleton-child-resource-clobber/policy.rego, the same bundle
# hcl_raw is graded by), so it must fail there and NOWHERE else: every tier-0
# assert reads a VALUE, and every value here is correct. It also independently
# exercises the `enabled` -> `status` mapping this arm's construct performs --
# if that mapping ever changed, this fixture would stop failing at tier 1 and
# say so loudly rather than quietly grading a different fact. Checked
# mechanically below; if the check does not hold, this fixture DELETES
# /logs/verifier/reward.txt so the falsifiability gate goes loud instead of
# banking an accidental 0.0.
set -uo pipefail

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
          enabled: false,
          filter: [{ prefix: "exports/" }],
          transition: [{ days: 90, storageClass: "GLACIER_IR" }],
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
  || proof_failed "static_tiers.sh never reached its summary line -- the synth or the plan is broken (an aws-unavailable preflight bail-out looks like this), so nothing here is evidence about this artifact"

grep -q '== summary: tier0_pass=1 ' "$LOG" \
  || proof_failed "tier 0 did not pass -- every value in this artifact is correct, so a tier-0 failure means this fixture is scoring 0.0 for some other reason and leaves the tier-1 policy unexercised"

grep -q 'tier1_status=FAIL' "$LOG" \
  || proof_failed "tier 1 did not FAIL -- the un-enabled-rule policy is what this fixture exists to falsify (a SKIPPED_STUB/TOOL_MISSING status is a run-invalidating condition, not proof)"

echo "FIXTURE SELF-PROOF OK: tier 0 passes on this artifact and only the tier-1 policy denies it"
exit 0
