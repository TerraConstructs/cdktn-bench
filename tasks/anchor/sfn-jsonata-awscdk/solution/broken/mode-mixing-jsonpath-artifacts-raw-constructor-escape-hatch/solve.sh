#!/usr/bin/env bash
# EXTRA, non-catch-named negative fixture (gates/oracle_falsifiability.py's
# "extra, non-catch-named negative fixtures" mechanism, same convention
# toy-ssm-parameter's own *-alt-shape fixtures use) -- NOT the primary
# fixture for catch "mode-mixing-jsonpath-artifacts" as of the
# "sfn-jsonata / mode-mixing-jsonpath-artifacts — awscdk tier '1' is
# fixture-selected, not arm-determined" fix (benchmark-integrity review,
# 2026-08-06). Kept to prove the tier-1 cfn-guard rule
# (no_jsonpath_mode_keys) remains reachable via the LESS-idiomatic raw
# State-constructor escape hatch, even though the scenario's own recorded
# `predicted_tier_caught.awscdk` is now "0" (the idiom the reference
# solution itself models -- `Pass.jsonata()`/`Choice.jsonata()`/
# `Fail.jsonata()` -- rejects this mistake at `tsc` time; see the sibling
# `mode-mixing-jsonpath-artifacts/solve.sh` fixture and
# specs/sfn-jsonata.yaml's own catch description for the full evidence
# trail). Deliberately mixes a JSONPath-only ASL field (ResultPath) into an
# otherwise-correct JSONata-mode state machine, via the raw State
# constructor's unified props type (`new sfn.Pass(..., {queryLanguage:
# JSONATA, resultPath: "...", ...})`) -- unlike the narrower
# `Pass.jsonata()` factory's own PassJsonataProps type (which DOES reject
# resultPath at compile time, verified directly), the general PassProps
# type unifies JsonPathStateOptions and JsonataStateOptions and accepts
# both simultaneously with no tsc error. `cdk synth` itself only emits a
# non-blocking CloudFormation-Validate WARNING for this exact mistake
# ("'ResultPath' is not allowed when QueryLanguage is JSONata") -- synth
# still exits 0 and writes the violating template, so this stays invisible
# to tier-0/reward.txt; only the tier-1 cfn-guard policy
# (no_jsonpath_mode_keys) turns it into an actual FAIL. Must score
# reward=0.0.
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

    const computeTotals = new sfn.Pass(this, "ComputeTotals", {
      queryLanguage: sfn.QueryLanguage.JSONATA,
      outputs: computeTotalsExpr,
      resultPath: "$.mistake",
    });

    const overBudget = sfn.Fail.jsonata(this, "OverBudget", {
      error: "GrandTotalExceedsBudget",
      cause: "The computed grand total exceeds the allowed budget.",
    });
    const withinBudget = sfn.Succeed.jsonata(this, "WithinBudget");
    const checkBudget = sfn.Choice.jsonata(this, "CheckBudget")
      .when(sfn.Condition.jsonata(`{% $states.input.grandTotal > 1000 %}`), overBudget)
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
