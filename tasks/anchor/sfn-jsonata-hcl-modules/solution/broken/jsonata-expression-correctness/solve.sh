#!/usr/bin/env bash
# Negative fixture for catch "jsonata-expression-correctness" (the anti-L2
# falsifiability catch). Same mistake as the hcl_raw and awscdk sibling
# fixtures: the CheckBudget condition's comparison operator is flipped (`<`
# instead of `>`) -- syntactically valid JSONata, structurally valid ASL,
# correct QueryLanguage, no JSONPath artifacts. The module passes the string
# through untouched, so `terraform validate`/`plan` and the tier-1 policy.rego
# both PASS it and reward stays 1.0; only the LIVE tier (tests/live_check.py,
# `stepfunctions test-state`) sees that CheckBudget routes an over-budget
# total to the Succeed state.
#
# WHAT THIS FIXTURE MUST PROVE, AND HOW
# =====================================
# A "live"-tier catch is only falsified if its offline run MECHANICALLY
# DEMONSTRATES the static-indistinguishability property it claims, rather than
# asserting it in a comment (gates/oracle_falsifiability.py's `live` branch,
# LIVE_ONLY_CONFIRMED_MARKER; SCHEMA.md §3). So, offline, with no account,
# this script:
#
#   1. plans the REFERENCE shape in place and keeps its graded artifact;
#   2. plans THIS shape (the flipped operator) as the graded artifact;
#   3. requires the two to be BYTE-IDENTICAL once every `{% ... %}` expression
#      BODY is elided to a fixed placeholder.
#
# Step 3 is the exact claim: the two solutions differ ONLY inside JSONata
# expression bodies. No tier-0 jq assert and no tier-1 Rego rule in this
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

# $1 -- the CheckBudget comparison operator. The template is a QUOTED heredoc
# so every backslash-escaped quote inside the ASL strings survives verbatim;
# the operator is substituted afterwards.
write_main_tf() {
  cat > main.tf <<'HCL'
module "order_batch" {
  source  = "terraform-aws-modules/step-functions/aws"
  version = "5.1.1"

  name = "sfn-jsonata-order-batch"

  definition = jsonencode({
    QueryLanguage = "JSONata"
    StartAt       = "ComputeTotals"
    States = {
      ComputeTotals = {
        Type   = "Pass"
        Output = "{% { \"orders\": $states.input.orders.{\"id\": id, \"qty\": qty, \"price\": price, \"total\": qty * price}, \"grandTotal\": $sum($states.input.orders.(qty * price)) } %}"
        Next   = "CheckBudget"
      }
      CheckBudget = {
        Type = "Choice"
        Choices = [
          {
            Condition = "{% $states.input.grandTotal __OP__ 1000 %}"
            Next      = "OverBudget"
          }
        ]
        Default = "WithinBudget"
      }
      OverBudget = {
        Type  = "Fail"
        Error = "GrandTotalExceedsBudget"
        Cause = "The computed grand total exceeds the allowed budget."
      }
      WithinBudget = {
        Type = "Succeed"
      }
    }
  })
}
HCL
  tmp="main.tf.op.$$"
  sed "s/__OP__/$1/" main.tf > "$tmp" && mv "$tmp" main.tf
}

# Every `{% ... %}` body replaced by one fixed placeholder, everywhere in the
# document, decoded or not: what survives is precisely what a static tier can
# read. `.timestamp` goes too -- `terraform show -json` stamps WHEN the plan
# ran, which differs between any two plans of the same configuration and which
# no assert in this scenario reads. So does the ORDER of `relevant_attributes`:
# once a module is in the plan Terraform emits that list in map-iteration
# order, so two plans of the same configuration carry the same entries in
# different positions. It is a set, nothing here reads it, and sorting it is
# narrower than sorting every array -- the ASL's own `Choices` list is ordered
# and must keep its order for this comparison to mean anything.
elide_expressions() {
  jq -S 'del(.timestamp)
         | (if has("relevant_attributes") then .relevant_attributes |= sort else . end)
         | walk(if type == "string" then gsub("\\{%.*?%\\}"; "{% ELIDED %}") else . end)' "$1"
}

# --- 1. the REFERENCE shape's graded artifact ------------------------------
# Planned IN PLACE, from the same working directory and the same seeded
# provider.tf the graded plan uses, so the only difference between the two
# artifacts is the one this fixture introduces.
REFERENCE_PLAN="reference-plan.json"
rm -f "$REFERENCE_PLAN"
write_main_tf '>'
terraform init -input=false >/dev/null 2>&1 \
  && terraform plan -input=false -out=reference.tfplan >/dev/null 2>&1 \
  && terraform show -json reference.tfplan > "$REFERENCE_PLAN" 2>/dev/null
probe_rc=$?
rm -f reference.tfplan

# --- 2. THIS shape, left in place for grading -------------------------------
# BUG: the threshold comparison is `<` where the request says "exceeds 1000".
write_main_tf '<'

bash tests/static_tiers.sh
rc=$?

# --- 3. the mechanical static-indistinguishability proof --------------------
echo "== static-indistinguishability probe: graded artifact, JSONata bodies elided =="
if [ "$probe_rc" -ne 0 ] || [ ! -s "$REFERENCE_PLAN" ]; then
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the reference-shape plan did" >&2
  echo "not produce an artifact, so this fixture proved nothing about it." >&2
elif [ ! -s plan.json ]; then
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: this fixture's own plan.json" >&2
  echo "is missing -- static_tiers.sh did not reach the plan step." >&2
elif diff -q <(elide_expressions "$REFERENCE_PLAN") \
              <(elide_expressions plan.json) >/dev/null; then
  echo "$MARKER: the reference solution's plan.json and this fixture's are"
  echo "  IDENTICAL once every {% ... %} body is elided -- the two differ only"
  echo "  INSIDE JSONata expression bodies. No tier-0 jq assert and no tier-1"
  echo "  Rego rule in this scenario evaluates a JSONata body, so nothing"
  echo "  static can distinguish them. The catch is live-only by construction,"
  echo "  not by oracle weakness."
else
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the two plans differ OUTSIDE" >&2
  echo "the JSONata expression bodies, so a static assert could tell them" >&2
  echo "apart. Re-tier this catch and add a real static assert. Diff:" >&2
  diff <(elide_expressions "$REFERENCE_PLAN") \
       <(elide_expressions plan.json) >&2 || true
fi
rm -f "$REFERENCE_PLAN"

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: Step Functions must route an over-budget total to Succeed =="
  python3 tests/live_check.py --expect stale
fi

exit $rc
