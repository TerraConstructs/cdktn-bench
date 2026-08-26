#!/usr/bin/env bash
# NEGATIVE fixture -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `existing-log-expiry-rule-dropped`
# (specs/singleton-child-resource-clobber.yaml). Must score reward 0.0.
#
# THE MISTAKE, on the arm that is structurally immune to the headline one: the
# rules are a TypeScript array literal passed to `storage.Bucket`'s constructor,
# and an array literal is exactly as easy to overwrite as an HCL block. Asked
# for one rule, the agent re-authors the array as the one rule it was asked
# for, and another team's deployed 30-day expiry of `logs/` leaves the document
# with no error anywhere.
set -euo pipefail

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

exec bash tests/static_tiers.sh
