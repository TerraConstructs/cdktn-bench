#!/usr/bin/env bash
# EXTRA, non-catch-named negative fixture -- hcl_modules counterpart of
# ../../../sfn-jsonata-hcl-raw/solution/broken/raw-jsonpath-literal-value-only/
# (same rationale; see that file's header for the isolation gap it closes).
#
# This arm's mode-mixing-jsonpath-artifacts/ fixture has the identical gap as
# the other two arms': `ResultPath = "$.mistake"` is simultaneously a banned
# key AND a raw "$."-prefixed literal value, so it cannot falsify the
# raw-literal deny rule in oracles/rego/sfn-jsonata/policy.rego being gutted on
# its own. Here the ASL carries no banned key at all: ComputeTotals' `Output`
# is a bare JSONPath string where a `{% ... %}` JSONata expression belongs --
# valid JSON, valid ASL, and a never-evaluated constant at runtime. Must score
# reward=0.0 under the genuine oracle, on the raw-literal deny alone.
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
HCL

bash tests/static_tiers.sh
