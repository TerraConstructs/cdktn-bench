#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# This is the pre-registered arm prediction made concrete
# (specs/lambda-log-group-ownership-and-retention.yaml's own header
# comment, "ARM PREDICTION" -- reproduced from
# docs/design/batch-a-greenfield-blueprints.md §11(e)): terraconstructs
# 0.2.13's `compute.LambdaFunction` UNCONDITIONALLY creates its own
# `aws_cloudwatch_log_group` named `/aws/lambda/${functionName}` (verified
# directly against the pinned package, see this spec's own header
# comment) -- there is no RETAIN/prevent_destroy/skip_destroy anywhere in
# that code path, and no separate log group resource to hand-author or
# forget. The ENTIRE reference solution is one function construct with one
# extra prop.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, RetentionDays, compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new compute.LambdaFunction(this, "EventProcessor", {
      functionName: "event-processor",
      runtime: compute.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async (event) => ({ statusCode: 200, body: JSON.stringify(event) });",
      ),
      logRetentionInDays: RetentionDays.ONE_MONTH,
    });
  }
}
TS

bash tests/static_tiers.sh
