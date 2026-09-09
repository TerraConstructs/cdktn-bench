#!/usr/bin/env bash
# Negative fixture for catch "jsonata-expression-correctness" (the anti-L2
# falsifiability catch). The CheckBudget condition's comparison operator is
# flipped (`<` instead of `>`) -- syntactically valid JSONata, structurally
# valid ASL, correct QueryLanguage, no JSONPath artifacts: every tier-0 AND
# tier-1 check this scenario has PASSES, so reward stays 1.0. Only the LIVE
# tier (tests/live_check.py, `stepfunctions test-state`) sees that CheckBudget
# routes an over-budget total to the Succeed state.
#
# WHAT THIS FIXTURE MUST PROVE, AND HOW
# =====================================
# A "live"-tier catch is only falsified if its offline run MECHANICALLY
# DEMONSTRATES the static-indistinguishability property it claims, rather than
# asserting it in a comment (gates/oracle_falsifiability.py's `live` branch,
# LIVE_ONLY_CONFIRMED_MARKER; SCHEMA.md §3). So, offline, with no account,
# this script:
#
#   1. synthesizes the REFERENCE shape into a scratch output directory;
#   2. synthesizes THIS shape (the flipped operator) as the graded artifact;
#   3. requires the two templates to be BYTE-IDENTICAL once every `{% ... %}`
#      expression BODY is elided to a fixed placeholder.
#
# Step 3 is the exact claim: the two solutions differ ONLY inside JSONata
# expression bodies. No tier-0 jq assert and no tier-1 cfn-guard rule in this
# scenario evaluates a JSONata body -- they test which keys and which
# substrings are present -- so nothing static can tell the two apart. If a
# future oracle change starts reading inside those bodies, or the two shapes
# start differing somewhere else, step 3 fails, the marker is not printed,
# `make falsifiability` turns red, and this catch gets re-tiered instead of
# silently continuing to claim invisibility it no longer has.
#
# Expected verdict: reward 1.0 (the static tiers genuinely cannot see this) AND
# the marker on stdout. Both are required; either alone is not falsification.
set -uo pipefail

MARKER="CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
REFERENCE_OUT="cdk.out.reference"

# $1 -- the CheckBudget comparison operator. The template is a QUOTED heredoc
# so the TypeScript template literals survive verbatim; the operator is
# substituted afterwards.
write_stack_ts() {
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

    const checkBudgetCondition = `{% $states.input.grandTotal __OP__ 1000 %}`;

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
  tmp="lib/scenario-stack.ts.op.$$"
  sed "s/__OP__/$1/" lib/scenario-stack.ts > "$tmp" && mv "$tmp" lib/scenario-stack.ts
}

# Every `{% ... %}` body replaced by one fixed placeholder, everywhere in the
# document: what survives is precisely what a static tier can read.
elide_expressions() {
  jq -S 'walk(if type == "string" then gsub("\\{%.*?%\\}"; "{% ELIDED %}") else . end)' "$1"
}

# --- 1. the REFERENCE shape's graded artifact, into a scratch out dir -------
rm -rf "$REFERENCE_OUT"
write_stack_ts '>'
npm run build >/dev/null 2>&1 \
  && npx cdk synth --no-lookups --quiet -o "$REFERENCE_OUT" >/dev/null 2>&1
probe_rc=$?

# --- 2. THIS shape, left in place for grading -------------------------------
# BUG: the threshold comparison is `<` where the request says "exceeds 1000".
write_stack_ts '<'

bash tests/static_tiers.sh
rc=$?

# --- 3. the mechanical static-indistinguishability proof --------------------
REFERENCE_TEMPLATE="$REFERENCE_OUT/ScenarioStack.template.json"
GRADED_TEMPLATE="cdk.out/ScenarioStack.template.json"
echo "== static-indistinguishability probe: graded artifact, JSONata bodies elided =="
if [ "$probe_rc" -ne 0 ] || [ ! -s "$REFERENCE_TEMPLATE" ]; then
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the reference-shape synth did" >&2
  echo "not produce a template, so this fixture proved nothing about it." >&2
elif [ ! -s "$GRADED_TEMPLATE" ]; then
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: this fixture's own template is" >&2
  echo "missing -- static_tiers.sh did not reach the synth step." >&2
elif diff -q <(elide_expressions "$REFERENCE_TEMPLATE") \
              <(elide_expressions "$GRADED_TEMPLATE") >/dev/null; then
  echo "$MARKER: the reference solution's synthesized template and this"
  echo "  fixture's are IDENTICAL once every {% ... %} body is elided -- the two"
  echo "  differ only INSIDE JSONata expression bodies. No tier-0 jq assert and"
  echo "  no tier-1 cfn-guard rule in this scenario evaluates a JSONata body, so"
  echo "  nothing static can distinguish them. The catch is live-only by"
  echo "  construction, not by oracle weakness."
else
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the two templates differ" >&2
  echo "OUTSIDE the JSONata expression bodies, so a static assert could tell" >&2
  echo "them apart. Re-tier this catch and add a real static assert. Diff:" >&2
  diff <(elide_expressions "$REFERENCE_TEMPLATE") \
       <(elide_expressions "$GRADED_TEMPLATE") >&2 || true
fi
rm -rf "$REFERENCE_OUT"

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: Step Functions must route an over-budget total to Succeed =="
  python3 tests/live_check.py --expect stale
fi

exit $rc
