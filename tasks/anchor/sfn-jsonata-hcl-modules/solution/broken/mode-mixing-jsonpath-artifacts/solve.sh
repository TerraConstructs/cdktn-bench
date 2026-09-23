#!/usr/bin/env bash
# Negative fixture for catch "mode-mixing-jsonpath-artifacts". Deliberately
# mixes a JSONPath-only ASL field (ResultPath) into an otherwise-correct
# JSONata-mode state machine's ASL, and hands that document to the module as
# the `definition` string. The module is not a schema over the ASL -- it
# assigns the variable straight to the resource attribute -- so `terraform
# validate`/`plan` see the same opaque JSON-encoded string the raw arm's
# provider sees, and nothing refuses it until the tier-1 policy.rego walks the
# decoded document. Must score reward=0.0.
set -euo pipefail

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
        Type       = "Pass"
        ResultPath = "$.mistake"
        Output     = "{% { \"orders\": $states.input.orders.{\"id\": id, \"qty\": qty, \"price\": price, \"total\": qty * price}, \"grandTotal\": $sum($states.input.orders.(qty * price)) } %}"
        Next       = "CheckBudget"
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
