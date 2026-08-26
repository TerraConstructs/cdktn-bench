#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-removed-instead-of-repointed`, predicted_tier_caught "0" on every arm.
#
# THE MISTAKE: make the symptom go away by removing the thing that has it. The
# environment variable becomes `USD` and both the alias and the version resource
# are deleted, so the new configuration IS reachable -- at the unqualified
# function ARN. It is not the ticket ("every caller reaches this function
# through its alias") and it breaks every one of those callers.
#
# This is the one negative that IS visible to a static tier on this arm, and it
# is what keeps this arm's tier 0 from being pure decoration: with only the
# environment assert, "delete the alias" and "correctly re-point the alias"
# would be indistinguishable at tier 0 here, since the live-tier catch already
# is. `the-alias-still-exists` (op `eq`, count-pinning) is the assert that fails.
#
# Expected verdict: reward 0.0, caught at tier 0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    new lambda.Function(this, "QuoteService", {
      functionName: "cdktn-bench-quote-service",
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        [
          "exports.handler = async () => ({",
          "  statusCode: 200,",
          "  body: JSON.stringify({ currency: process.env.QUOTE_CURRENCY }),",
          "});",
        ].join("\n"),
      ),
      environment: {
        QUOTE_CURRENCY: "USD",
      },
    });
  }
}
TS

exec bash tests/static_tiers.sh
