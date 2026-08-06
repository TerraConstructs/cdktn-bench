#!/usr/bin/env bash
# Negative fixture for catch "mode-mixing-jsonpath-artifacts" (Slice D;
# REWRITTEN by the "sfn-jsonata / mode-mixing-jsonpath-artifacts — awscdk
# tier '1' is fixture-selected, not arm-determined" fix, benchmark-integrity
# review 2026-08-06). Uses the SAME idiom the scenario's own reference
# solution models (`Pass.jsonata()`/`Choice.jsonata()`/`Fail.jsonata()`
# throughout -- see ../../solve.sh), not the raw `new sfn.Pass(...)`
# constructor the previous version of this fixture used. Verified directly
# against the local aws-cdk clone (packages/aws-cdk-lib/aws-stepfunctions/
# lib/states/pass.ts:96): `PassJsonataProps extends StateBaseProps,
# AssignableStateOptions, JsonataCommonOptions` -- no `PassJsonPathOptions`
# mixed in -- so setting `resultPath` on `Pass.jsonata()` is a genuine `tsc`
# compile error, not a synth-time or policy-time catch. This means an agent
# writing in the idiom the reference solution itself demonstrates hits a
# BUILD FAILURE (tier "0" -- caught by the compiler, before `cdk synth` or
# any Rego/cfn-guard tooling ever runs), not a tier-1 policy rejection.
#
# The previous version of this fixture used the raw `new sfn.Pass(...)`
# constructor specifically to dodge this compile error and reach cfn-guard
# instead -- that idiom-dependent divergence is real (raw-constructor usage
# DOES still only get caught at tier 1: see the sibling fixture
# solution/broken/mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/),
# but recording predicted_tier_caught.awscdk="1" as this catch's PRIMARY,
# spec-verified fixture overstated how weak CDK's catch mechanism is here:
# for the idiom this scenario's own solution teaches, CDK catches the
# mistake EARLIER (tier 0) than the TF-shaped arms do (tier 1), not later.
# specs/sfn-jsonata.yaml now records awscdk="0" for this catch to reflect
# that. Must score reward=0.0 -- via a build failure, same bucket a tier-"0"
# catch's own structural-assert-driven build failure would land in.
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

    // BUG: resultPath is a JSONPath-only field. Pass.jsonata()'s own
    // PassJsonataProps type has no PassJsonPathOptions mixed in, so this
    // line is a genuine `tsc` compile error (not merely a lint warning) --
    // "Object literal may only specify known properties, and 'resultPath'
    // does not exist in type 'PassJsonataProps'."
    const computeTotals = sfn.Pass.jsonata(this, "ComputeTotals", {
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
