#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE: `terraform-aws-modules/step-functions/aws` 5.1.1 authors the
# state machine, its execution role and the role's trust policy from one call
# -- `create_role` defaults true, so `role_arn` is wired inside the module and
# the caller states no IAM at all. No raw resource is left: this scenario's
# two services are exactly the pair this module composes.
#
# The ASL reaches the resource untouched. `definition` is a string variable
# assigned straight to `aws_sfn_state_machine.definition`, with no jsonencode
# or templatefile wrapper and nothing the module computes interpolated into
# it, so the document stays plan-time-known and `values.definition` resolves
# in full for the tier-0 `|fromjson` asserts and the Rego bundle alike.
set -euo pipefail

cat > main.tf <<'HCL'
module "order_batch" {
  source  = "terraform-aws-modules/step-functions/aws"
  version = "5.1.1"

  name = "sfn-jsonata-order-batch"

  # ONE embedded {% ... %} expression evaluating to the WHOLE Output object,
  # not an object literal with a {% %} per field. The graded fact is the VALUE
  # this state computes: tests/live_check.py submits it to TestState and
  # compares what Step Functions returns.
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
            Condition = "{% $states.input.grandTotal > 1000 %}"
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

bash tests/static_tiers.sh

# LIVE=1 (a real account): the same gating live oracle the verifier runs, in
# its fixture-invoked shape. The reference solution's JSONata must be what
# Step Functions actually computes, not merely what the static tiers accept.
if [ "${LIVE:-0}" = "1" ]; then
  python3 tests/live_check.py --expect ok
fi
