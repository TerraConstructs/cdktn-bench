#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `retention-left-at-the-construct-default` as
# it appears on this arm: the module creates and names the log group for
# free, so the ownership half of the ticket is satisfied without the
# solution touching CloudWatch at all -- and
# `cloudwatch_logs_retention_in_days` is left at its `null` default
# (variables.tf:455), which the provider resolves to `retention_in_days = 0`,
# never expire.
# Reward must be 0.0 via tier-0's `log-group-retention-is-30-days`,
# non-vacuously: the field resolves to one node whose value is 0.
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

  # Deliberate mistake: retention is never set, so the group never expires
  # -- "we are paying for that today" is exactly what the ticket refuses.
  cloudwatch_logs_skip_destroy = false
}
HCL

bash tests/static_tiers.sh
