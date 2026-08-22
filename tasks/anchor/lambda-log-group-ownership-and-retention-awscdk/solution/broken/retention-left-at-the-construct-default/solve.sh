#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NEW as of the 2026-08-21 second adversarial-review fix round
# (see specs/lambda-log-group-ownership-and-retention.yaml's own catch
# `retention-left-at-the-construct-default`): this scenario's headline
# value check, `log-group-retention-is-30-days`, previously had no fixture
# that isolated it non-vacuously -- every existing broken fixture that
# failed it did so only because it declared no log group at all (0
# resolved nodes), never because a real, present retention value was
# simply wrong.
#
# Reproduces that catch: the log group is correctly named
# (`/aws/lambda/event-processor`), correctly wired (passed as the
# function's own `logGroup` prop), and correctly deleted with the stack
# (`removalPolicy: DESTROY`) -- every OTHER tier-0/tier-1 fact this
# scenario checks passes. The only thing missing is the `retention` prop
# itself. Verified directly, 2026-08-21, against a real `cdk synth`
# (aws-cdk-lib 2.263.0, this arm's own pin) before this fixture was
# written: an explicit `logs.LogGroup` with no `retention` prop synthesizes
# `RetentionInDays: 731` in the template (not absent -- a present, wrong
# value; `aws-logs/lib/log-group.d.ts`'s own `@default RetentionDays.
# TWO_YEARS` resolves to the enum member's real numeric value, 731 --
# either way, not the 30 this ticket asks for). Reward must be
# 0.0, caught at tier 0 by `log-group-retention-is-30-days`
# (`op: eq`, `expected: 30`, `resolved: [731]`).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const functionName = "event-processor";

    // Correctly named, correctly wired, correctly deleted with the stack
    // -- but no `retention` prop, so it is left at the construct's own
    // default (RetentionDays.TWO_YEARS, synthesized as 731) rather than
    // the 30 days this ticket asks for.
    const logGroup = new logs.LogGroup(this, "EventProcessorLogGroup", {
      logGroupName: `/aws/lambda/${functionName}`,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    new lambda.Function(this, "EventProcessor", {
      functionName,
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async (event) => ({ statusCode: 200, body: JSON.stringify(event) });",
      ),
      logGroup,
    });
  }
}
TS

bash tests/static_tiers.sh
