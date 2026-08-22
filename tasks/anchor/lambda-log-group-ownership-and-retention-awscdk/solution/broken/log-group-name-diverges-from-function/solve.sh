#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). NEW as of the 2026-08-21 verifier-fix round (see this
# scenario's own spec header comment, "VERIFIER-REJECTED FIX" /
# "RESIDUAL, NARROWER TOOL-CAPABILITY GAP") -- catch
# `log-group-name-diverges-from-function` used to be entirely
# unauthorable on awscdk (cfn-guard's own tool-capability gap made the
# EXACT-suffix-match check unimplementable). It is now `applies_to:
# [awscdk, hcl_raw, terraconstructs]`, because closing part of that gap
# (the explicit-wiring disjunct needs no string concatenation at all, only
# a structural EXISTS check) also means the OPPOSITE mistake -- a log
# group with a name that doesn't even match the `/aws/lambda/` PREFIX,
# AND no explicit wiring either -- is now provably catchable here too.
#
# Reproduces catch `log-group-name-diverges-from-function`: the log group
# exists, has 30-day retention, and is not retained on delete -- every
# tier-0 fact this scenario checks passes. But its name is a wholly
# UNRELATED literal (`/platform/event-processor`, not even
# `/aws/lambda/`-prefixed) and the function has no `logGroup` prop / no
# `LoggingConfig.LogGroup` wiring to it at all -- so this log group
# governs NOTHING. Reward must be 0.0, caught ONLY at tier 1
# (log-group-governs-the-function-cfn /
# oracles/cfn-guard/lambda-log-group-ownership-and-retention/policy.guard):
# `log_group_governs_the_function` fails both its OR disjuncts
# (LogGroupName does not match `^/aws/lambda/`, and
# `Properties.LoggingConfig.LogGroup` does not exist on the function).
#
# NOTE on why this fixture's name fails the PREFIX check outright, rather
# than just the SUFFIX (e.g. `/aws/lambda/processor` while the function is
# `event-processor`, the shape hcl_raw/terraconstructs' own broken fixture
# for this same catch uses): cfn-guard 3.2.0 has no string-concatenation
# operator, so its own naming-path disjunct can only check the static
# `^/aws/lambda/` prefix regex, not compute this function's own expected
# suffix. A wrong-suffix-but-right-prefix mistake would still PASS this
# arm's tier-1 rule (a real, accepted, narrower residual gap, documented
# in this scenario's own spec header comment) -- this fixture instead uses
# a name that fails the prefix outright, staying within what this arm's
# own tier-1 rule can actually prove, per the tier1-coverage floor
# (generator/check_tier1_coverage.py) this fixture exists to satisfy.
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

    // Deliberately mismatched AND unwired: an unrelated literal name, no
    // `logGroup` prop passed to the function below -- neither of this
    // scenario's two accepted "the declared group governs this function"
    // mechanisms is satisfied.
    new logs.LogGroup(this, "EventProcessorLogGroup", {
      logGroupName: "/platform/event-processor",
      retention: logs.RetentionDays.ONE_MONTH,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
    });

    new lambda.Function(this, "EventProcessor", {
      functionName,
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      code: lambda.Code.fromInline(
        "exports.handler = async (event) => ({ statusCode: 200, body: JSON.stringify(event) });",
      ),
    });
  }
}
TS

bash tests/static_tiers.sh
