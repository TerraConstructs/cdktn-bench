#!/usr/bin/env bash
# Negative fixture for catch "mode-mixing-jsonpath-artifacts" (Slice D).
# Deliberately mixes a JSONPath-only ASL field (ResultPath) into an
# otherwise-correct JSONata-mode state machine's raw ASL JSON --
# `terraform validate`/`plan` never parse ASL semantics (the whole
# `definition` attribute is an opaque JSON-encoded string to the provider),
# so this is entirely undetected until the tier-1 policy.rego
# (no_jsonpath_mode_keys) inspects it. Must score reward=0.0.
set -euo pipefail

cat > main.tf <<'TF'
resource "aws_iam_role" "sfn_exec" {
  name = "sfn-jsonata-order-batch-exec"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "states.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_sfn_state_machine" "order_batch" {
  name     = "sfn-jsonata-order-batch"
  role_arn = aws_iam_role.sfn_exec.arn

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
TF

bash tests/static_tiers.sh
