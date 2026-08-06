#!/usr/bin/env bash
# Negative fixture for catch "jsonata-expression-correctness" (the anti-L2
# falsifiability catch, Slice D). The CheckBudget condition's comparison
# operator is flipped (`<` instead of `>`) -- syntactically valid JSONata,
# structurally valid ASL, correct QueryLanguage, no JSONPath artifacts:
# every tier-0 AND tier-1 check this scenario has PASSES. This is the
# scenario's own defining property (anti-L2, predicted parity): `tsc`/`cdk
# synth`/the tier-1 cfn-guard policy cannot see inside the expression
# string, so this fixture is EXPECTED to score reward=1.0 through
# tests/static_tiers.sh -- the catch is caught ONLY by Tier 0.5
# (oracles.lib.tier05_jsonata, run separately, host-side, non-gating), NOT
# by this script's own reward.txt. See gates/oracle_falsifiability.py's
# tier-0.5-aware per-catch handling: it runs Tier 0.5 against THIS
# fixture's own synthesized artifact and requires it to FAIL, alongside
# (not instead of) requiring reward==1.0 here.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

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

    // BUG: should be "> 1000" -- flipped to "<", a wrong-but-syntactically-
    // valid JSONata expression invisible to every static tier this
    // scenario has except Tier 0.5.
    const checkBudgetCondition = `{% $states.input.grandTotal < 1000 %}`;

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
