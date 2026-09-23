#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-removed-instead-of-repointed`, predicted_tier_caught "0" on every arm.
#
# THE MISTAKE: make the symptom go away by removing the thing that has it. The
# environment variable becomes `USD` and the alias construct is deleted, so the
# new configuration IS reachable -- at the unqualified function ARN. It is not
# the ticket ("every caller reaches this function through its alias") and it
# breaks every one of those callers.
#
# Kept as its own fixture for the reason spelled out in the hcl_raw twin:
# deleting the alias also makes `alias-is-no-longer-pinned-to-the-seeds-version`
# pass, because `not_regex` is true over zero resolved nodes. Only
# `the-alias-still-exists` (op `eq`, count-pinning) refuses this.
#
# Expected verdict: reward 0.0, caught at tier 0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new compute.LambdaFunction(this, "QuoteService", {
      functionName: "cdktn-bench-quote-service",
      runtime: compute.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
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
      publish: true,
    });
  }
}
TS

exec bash tests/static_tiers.sh
