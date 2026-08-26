#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-still-serves-the-previous-version`, whose predicted_tier_caught is
# "0" on this arm (it inherits the `hcl` slot -- this arm's graded artifact is
# a Terraform plan, not a CloudFormation template).
#
# THE MISTAKE: the plausible, competent-looking answer. `QUOTE_CURRENCY` becomes
# `USD` and nothing else moves. It synthesizes, it plans, it applies cleanly --
# `publish: true` cuts version 2 -- and `compute.Alias`'s literal `version: "1"`
# goes on naming version 1, whose immutable snapshot still says `EUR`.
#
# This library has no `Version` construct and no `currentVersion` accessor
# (verified against the arm's pinned source, lib/aws/compute/function-alias.d.ts:
# `readonly version: string`), so the alias's target is ALWAYS a string in the
# synthesized cdk.tf.json -- either a literal, as here, or the
# `${aws_lambda_function.….version}` token the reference solution uses. Both
# reach `terraform show -json`'s `.planned_values`, which is why this arm is
# graded at tier 0 exactly like hcl_raw and unlike awscdk.
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
      version: "1",
    });
  }
}
TS

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: this deploy is EXPECTED to succeed and to leave the alias behind =="
  # Same self-proof discipline as the hcl_raw twin: the deploy must SUCCEED
  # before `--expect stale` is allowed to corroborate anything, because the
  # harness-deployed seed already makes `fail_stale` true by construction.
  DEPLOY_LOG=/tmp/lambda-alias-broken-terraconstructs.log
  set +e
  CDKTN_BENCH_LIVE=1 npx cdktn deploy --auto-approve quote-service > "$DEPLOY_LOG" 2>&1
  deploy_rc=$?
  set -e
  cat "$DEPLOY_LOG"
  if [ "$deploy_rc" -ne 0 ]; then
    echo "FIXTURE PROOF FAILED: the deploy exited $deploy_rc." >&2
    echo "This fixture pins a change that DEPLOYS CLEANLY and is still wrong." >&2
    echo "Log: $DEPLOY_LOG" >&2
    exit 1
  fi
  echo "== deploy succeeded, as this fixture requires; now asking the account =="
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
