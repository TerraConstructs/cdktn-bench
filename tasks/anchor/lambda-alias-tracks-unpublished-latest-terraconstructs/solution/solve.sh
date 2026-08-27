#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same tests/static_tiers.sh
# a real trial's verifier runs. Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# BROWNFIELD: this is the SEED with exactly two changes.
#   1. QUOTE_CURRENCY  "EUR" -> "USD"   -- the ticket.
#   2. the alias's target: the literal `version: "1"` becomes
#      `version: quoteService.version`.
#
# `LambdaFunction.version` is this library's accessor for the underlying
# `aws_lambda_function.version` attribute ("Latest published version of your
# Lambda Function"), so with the `publish: true` the seed already carries, the
# alias now names the version this apply cuts instead of the one that was
# current when someone typed "1". Verified against the arm's pinned
# terraconstructs source: `AliasProps.version` is a plain `readonly version:
# string` (lib/aws/compute/function-alias.d.ts) -- this library has no `Version`
# construct and no `currentVersion` accessor, so the attribute token IS the
# idiomatic fix here, and it is a different shape from awscdk's.
#
# `aliasName` stays `"live"` and is NOT renamed to match the other two arms'
# literal: `compute.Alias` composes the deployed name itself as
# `${gridUUID}-${aliasName}` (lib/aws/compute/function-alias.js), so `"live"`
# here IS `quote-service-live` in the account and in the plan JSON -- which is
# what makes the arm-agnostic live oracle and the shared tier-0 name assert
# possible. Changing it would silently break both.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const quoteService = new compute.LambdaFunction(this, "QuoteService", {
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

    new compute.Alias(this, "LiveAlias", {
      aliasName: "live",
      function: quoteService,
      version: quoteService.version,
    });
  }
}
TS

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: real cdktn deploy against this account =="
  npx cdktn deploy --auto-approve quote-service
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
