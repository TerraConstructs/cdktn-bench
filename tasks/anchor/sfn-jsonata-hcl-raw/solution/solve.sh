#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8; Slice D).
# Writes an oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh
# a real trial's verifier runs. Regenerating this scenario will NOT
# overwrite this file (destructive-safe rule).
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

# Plan-time-knownness (specs/SCHEMA.md §4.2.1): every value inside this
# definition is a literal -- no reference to any other resource's
# provider-computed output -- so `definition` stays fully plan-time-known
# in `terraform show -json` output (role_arn below is a SEPARATE
# attribute; its own plan-time-unknown ARN never enters `definition`).
resource "aws_sfn_state_machine" "order_batch" {
  name     = "sfn-jsonata-order-batch"
  role_arn = aws_iam_role.sfn_exec.arn

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
TF

bash tests/static_tiers.sh
