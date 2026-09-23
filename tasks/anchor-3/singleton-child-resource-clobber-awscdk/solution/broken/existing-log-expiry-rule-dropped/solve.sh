#!/usr/bin/env bash
# NEGATIVE fixture -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `existing-log-expiry-rule-dropped`
# (specs/singleton-child-resource-clobber.yaml). Must score reward 0.0.
#
# THE MISTAKE, on the arm that is structurally immune to the headline one: the
# rules are a TypeScript array literal, and an array literal is exactly as easy
# to overwrite as an HCL block. Asked for one rule, the agent re-authors the
# array as the one rule it was asked for, and another team's deployed 30-day
# expiry of `logs/` leaves the document with no error anywhere.
#
# This is the catch where the typed arms have NO structural advantage, which is
# why it applies to all three and why it is worth a fixture on each.
set -euo pipefail

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

exec bash tests/static_tiers.sh
