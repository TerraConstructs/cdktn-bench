#!/usr/bin/env bash
# EXTRA, non-catch-named negative fixture (gates/oracle_falsifiability.py's
# "extra, non-catch-named negative fixtures" mechanism, same convention
# mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/ and
# toy-ssm-parameter's own *-alt-shape fixtures use).
#
# Closes the "an asymmetric tier-1 oracle-strictness break passes `make ci`
# completely" blocker (benchmark-integrity review, 2026-08-06 round 2) for
# sfn-jsonata specifically: the ONLY existing fixture that reaches
# oracles/cfn-guard/sfn-jsonata/policy.guard's `no_raw_jsonpath_string_literal`
# rule at all -- mode-mixing-jsonpath-artifacts-raw-constructor-escape-hatch/
# -- sets `resultPath: "$.mistake"`, which trips `no_jsonpath_mode_keys`
# (the banned-key rule) AT THE SAME TIME as `no_raw_jsonpath_string_literal`
# (the raw-"$."-literal rule), because "$.mistake" is simultaneously a
# banned key's VALUE and a raw JSONPath literal. Since a cfn-guard bundle's
# `tier1_status` is a single verdict over ALL rules at once
# (result_schema.json's own `tier_evidence.tier1_status` field
# description), that fixture keeps failing (tier1_status=FAIL) even when
# `no_raw_jsonpath_string_literal` ITSELF is silently gutted (verified by
# hand: replacing its condition with an always-true regex, e.g.
# `!= /ZZZ_NEVER_MATCHES_ZZZ/`, left every existing fixture's PASS/FAIL
# verdict bit-identical -- `no_jsonpath_mode_keys` alone was doing all the
# work). No existing fixture ISOLATES the raw-literal rule, so no existing
# fixture can ever falsify it being gutted.
#
# This fixture closes that gap: it sets NO banned JSONPath-mode key
# anywhere (InputPath/OutputPath/Parameters/ResultPath/ResultSelector/
# ItemsPath are all absent) -- only a raw, un-evaluated "$."-prefixed
# string LITERAL as a Pass state's `Output` value (a field name that is
# itself perfectly legal in JSONata mode; only unwrapped-string VALUES
# starting "$." are the mistake -- see this scenario's own
# no-raw-jsonpath-string-literal structural_assert / the
# mode-mixing-jsonpath-artifacts catch's description in
# specs/sfn-jsonata.yaml for why Step Functions treats an unwrapped string
# as a literal constant, never evaluated as a path). Verified directly
# (hand-run, not just asserted): under a sabotaged
# `no_raw_jsonpath_string_literal` (always-true), this fixture's synthesized
# DefinitionString (`{"...,"ComputeTotals":{"Type":"Pass","Output":"$.orders",...}
# ...}`) passes `cfn-guard validate` cleanly (rc=0, no FAILED rules) --
# proving the isolation is real, not just intended -- while the SAME
# artifact against the genuine (unsabotaged) rule fails with exactly one
# FAILED rule, `no_raw_jsonpath_string_literal`, and no other. Must score
# reward=0.0 under the genuine oracle.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as sfn from "aws-cdk-lib/aws-stepfunctions";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Raw, un-evaluated "$."-prefixed JSONPath string literal used AS A
    // VALUE of `outputs` -- NOT wrapped in `{% ... %}` -- with NO banned
    // JSONPath-mode key anywhere in this state machine. Isolates
    // no_raw_jsonpath_string_literal from no_jsonpath_mode_keys by
    // construction (verified: see this file's own header comment).
    const computeTotals = sfn.Pass.jsonata(this, "ComputeTotals", {
      outputs: "$.orders",
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
