#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NEW as of the 2026-08-21 second adversarial-review fix round
# (see specs/lambda-log-group-ownership-and-retention.yaml's own catch
# `retention-left-at-the-construct-default`): this scenario's headline
# value check, `log-group-retention-is-30-days`, previously had no fixture
# that isolated it non-vacuously anywhere -- and this arm specifically had
# ZERO real-mistake coverage for it, despite being the pre-registered
# WINNING arm whose entire reference solution (see
# tasks/anchor/lambda-log-group-ownership-and-retention-terraconstructs/
# solution/solve.sh) is exactly one prop,
# `logRetentionInDays: RetentionDays.ONE_MONTH`, on `compute.LambdaFunction`.
# Omitting that one prop is the ONLY mistake reachable through this L2's
# public surface for this fact at all -- a real, likely catch that
# previously had no fixture proving the oracle actually rejects it.
#
# `compute.LambdaFunction` UNCONDITIONALLY creates its own
# `aws_cloudwatch_log_group`, correctly named
# (`/aws/lambda/${functionName}`) and correctly destroyed with the stack
# (no `skip_destroy`/RETAIN anywhere in that code path -- see this
# scenario's own spec header comment) -- so leaving `logRetentionInDays`
# unset satisfies every OTHER tier-0/tier-1 fact this scenario checks.
# Verified directly, 2026-08-21, against a real `cdktn synth` + offline
# `terraform plan` (terraconstructs 0.2.13, this arm's own pin) before this
# fixture was written: omitting `logRetentionInDays` leaves the
# construct's own default, `RetentionDays.ONE_WEEK`, confirmed to
# synthesize `retention_in_days: 7` in `.planned_values` -- not the 30 this
# ticket asks for. Reward must be 0.0, caught at tier 0 by
# `log-group-retention-is-30-days` (`op: eq`, `expected: 30`,
# `resolved: [7]`).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // No `logRetentionInDays` -- the L2 still creates and correctly owns
    // the log group (right name, deleted with the stack), but retention
    // is left at the construct's own default (RetentionDays.ONE_WEEK = 7)
    // instead of the 30 days this ticket asks for.
    new compute.LambdaFunction(this, "EventProcessor", {
      functionName: "event-processor",
      runtime: compute.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async (event) => ({ statusCode: 200, body: JSON.stringify(event) });",
      ),
    });
  }
}
TS

bash tests/static_tiers.sh
