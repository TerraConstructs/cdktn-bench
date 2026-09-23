#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces catch `log-group-retained-on-delete`: identical to
# the reference except `cloudwatch_logs_skip_destroy = true`, the module's
# own exposed passthrough to the log group's `skip_destroy`
# (variables.tf:467, main.tf:282). Retention is still 30 days and the group
# is still named after the function; only the teardown half of the ticket
# fails.
# Reward must be 0.0 via tier-0's `log-group-not-retained-on-stack-delete-tf`.
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

  cloudwatch_logs_retention_in_days = 30
  # Deliberate mistake: the log group survives `terraform destroy`.
  cloudwatch_logs_skip_destroy = true
}
HCL

bash tests/static_tiers.sh
