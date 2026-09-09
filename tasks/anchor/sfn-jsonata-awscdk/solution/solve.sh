#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8; Slice D).
# Writes an oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";

/**
 * sfn-jsonata reference solution: a JSONata-query-language state machine
 * that computes per-order + grand totals for a batch of orders, then
 * branches on the grand total against a budget cap.
 */
export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // ONE embedded {% ... %} expression evaluating to the WHOLE Output
    // object, not an object literal with a {% %} per field. The graded fact
    // is the VALUE this state computes: tests/live_check.py submits this
    // state to TestState and compares what Step Functions returns, so the
    // reference states the computation as the single expression the service
    // evaluates in one go.
    const computeTotalsExpr = `{% {
      "orders": $states.input.orders.{"id": id, "qty": qty, "price": price, "total": qty * price},
      "grandTotal": $sum($states.input.orders.(qty * price))
    } %}`;

    const computeTotals = sfn.Pass.jsonata(this, "ComputeTotals", {
      outputs: computeTotalsExpr,
    });

    const overBudget = sfn.Fail.jsonata(this, "OverBudget", {
      error: "GrandTotalExceedsBudget",
      cause: "The computed grand total exceeds the allowed budget.",
    });

    const withinBudget = sfn.Succeed.jsonata(this, "WithinBudget");

    const checkBudgetCondition = `{% $states.input.grandTotal > 1000 %}`;

    const checkBudget = sfn.Choice.jsonata(this, "CheckBudget")
      .when(sfn.Condition.jsonata(checkBudgetCondition), overBudget)
      .otherwise(withinBudget);

    const definition = computeTotals.next(checkBudget);

    new sfn.StateMachine(this, "OrderBatchStateMachine", {
      definitionBody: sfn.DefinitionBody.fromChainable(definition),
      queryLanguage: sfn.QueryLanguage.JSONATA,
    });
  }
}
TS

bash tests/static_tiers.sh

# LIVE=1 (a real account): the same gating live oracle the verifier runs, in
# its fixture-invoked shape. The reference solution's JSONata must be what
# Step Functions actually computes, not merely what the static tiers accept.
if [ "${LIVE:-0}" = "1" ]; then
  python3 tests/live_check.py --expect ok
fi
