#!/usr/bin/env bash
# Negative fixture for catch "jsonata-expression-correctness" (the anti-L2
# falsifiability catch, Slice D). Same mistake as the awscdk sibling
# fixture: the CheckBudget condition's comparison operator is flipped (`<`
# instead of `>`) -- syntactically valid JSONata, structurally valid ASL,
# correct QueryLanguage, no JSONPath artifacts. `terraform validate`/`plan`
# and the tier-1 policy.rego both PASS this fixture; only Tier 0.5 (run
# separately, host-side, non-gating) catches it. Expected to score
# reward=1.0 through tests/static_tiers.sh -- see
# gates/oracle_falsifiability.py's tier-0.5-aware per-catch handling and
# this scenario's jsonata-expression-correctness catch description for why
# that is the correct, EXPECTED outcome here, not a gate bug.
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
        Type   = "Pass"
        Output = "{% { \"orders\": $states.input.orders.{\"id\": id, \"qty\": qty, \"price\": price, \"total\": qty * price}, \"grandTotal\": $sum($states.input.orders.(qty * price)) } %}"
        Next   = "CheckBudget"
      }
      CheckBudget = {
        Type = "Choice"
        Choices = [
          {
            # BUG: should be "> 1000" -- flipped to "<".
            Condition = "{% $states.input.grandTotal < 1000 %}"
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
