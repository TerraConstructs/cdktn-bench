#!/usr/bin/env bash
# EXTRA, non-catch-named negative fixture -- hcl_raw counterpart of
# ../../../sfn-jsonata-awscdk/solution/broken/raw-jsonpath-literal-value-only/
# (same rationale, same isolation goal; see that file's own header comment
# for the full "an asymmetric tier-1 oracle-strictness break passes `make
# ci` completely" blocker this closes, 2026-08-06 round 2).
#
# The existing mode-mixing-jsonpath-artifacts/ fixture on THIS arm has the
# identical isolation gap as the awscdk escape-hatch fixture: it sets
# `ResultPath = "$.mistake"`, which is simultaneously a banned key
# (`no_jsonpath_mode_keys`-equivalent `banned_keys` deny in
# oracles/rego/sfn-jsonata/policy.rego) AND a raw "$."-prefixed literal
# value (the `deny` rule this fixture targets) -- so it cannot falsify the
# raw-literal deny rule being gutted in isolation, the SAME reason the
# awscdk side needed this fixture. Verified directly: this fixture's plan
# JSON produces exactly one `deny` message under the genuine policy.rego
# ("...contains a raw (un-evaluated) \"$.\"-prefixed JSONPath string
# literal..."), no banned-key deny alongside it -- proving the isolation is
# real. Must score reward=0.0 under the genuine oracle.
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
        Output = "$.orders"
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
