#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same tests/static_tiers.sh
# a real trial's verifier runs. Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# BROWNFIELD: this is the SEED with exactly two changes.
#   1. QUOTE_CURRENCY  "EUR" -> "USD"   -- the ticket.
#   2. the alias's version target: the seed's stand-alone
#      `new lambda.Version(this, "ReleasedVersion", { lambda: quoteService })`
#      is replaced by `quoteService.currentVersion`.
#
# WHY (2) IS THE FIX, precisely. `AWS::Lambda::Version` publishes a version when
# CloudFormation CREATES it, and its only property is `FunctionName`. A stand-
# alone `lambda.Version` construct has a logical id derived from its construct
# path alone, so changing the function leaves that resource's id AND properties
# untouched, CFN issues no update for it, no new version is published, and the
# alias keeps naming version 1 -- whose immutable snapshot still says EUR.
# `Function.currentVersion` exists exactly to remove that: aws-cdk-lib stamps a
# hash of the function's own configuration into the Version resource's LOGICAL
# ID, so a changed function yields a different logical id, a NEW
# `AWS::Lambda::Version`, and an alias update in the same changeset.
#
# NOTE FOR THE READER OF THE STATIC TIERS: this arm's tier 0 CANNOT tell this
# file from solution/broken/alias-still-serves-the-previous-version/solve.sh,
# and that is by construction rather than by oracle weakness -- that fixture
# proves it mechanically, offline, on every `make falsifiability` run. This
# arm's catch is graded live.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as lambda from "aws-cdk-lib/aws-lambda";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const quoteService = new lambda.Function(this, "QuoteService", {
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

    new lambda.Alias(this, "LiveAlias", {
      aliasName: "quote-service-live",
      version: quoteService.currentVersion,
    });
  }
}
TS

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: real cdk deploy against this account =="
  npx cdk deploy --require-approval never ScenarioStack
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
