#!/usr/bin/env bash
# NEGATIVE FIXTURE, not a catch -- and the only shape on this arm that reaches
# the tier-1 rule at all, so without it `grading-proof` reports the arm's tier-1
# row as SKIP and nothing proves the log-group-governs-the-function join works
# across a module boundary.
#
# `lambda_at_edge = true` names the created group
# `/aws/lambda/us-east-1.<function-name>` (lambda@8.8.2 main.tf:279) while the
# function's `logging_config.log_group` stays the unset `logging_log_group`
# (main.tf:142), so the group this configuration creates is not the one the
# function writes to. That is the same end state `log-group-name-diverges-from-
# function` traps; it is NOT that catch's fixture because flipping an edge flag
# is not the mistake an author of this ticket makes, and the catch stays
# excluded on this arm for that reason.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
module "event_processor" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "event-processor"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package         = false
  local_existing_package = "function.zip"

  lambda_at_edge = true

  cloudwatch_logs_retention_in_days = 30
  cloudwatch_logs_skip_destroy      = false
}
HCL

bash tests/static_tiers.sh
