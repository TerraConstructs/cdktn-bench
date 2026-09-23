#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf plus a placeholder Lambda deployment package, then
# runs the same tests/static_tiers.sh a real trial's verifier runs.
# Regenerating this scenario will NOT overwrite this file (destructive-safe
# rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): one call to
# `terraform-aws-modules/lambda/aws` 8.8.2 authors all three resources the
# hcl_raw reference hand-wires -- the function, its execution role
# (`create_role`, on by default) and the log group
# (`aws_cloudwatch_log_group.lambda`, main.tf:274, named
# `/aws/lambda/${var.function_name}`). Nothing is written raw.
#
# `create_package = false` + `local_existing_package`: the module's own
# packaging path shells out to package.py through a `data "external"`, and
# this oracle is plan-only, so the placeholder file the hcl_raw reference
# already uses is handed to the module instead (that reference's header
# comment records why a placeholder is enough and why `hashicorp/archive` is
# not on this arm's path).
#
# Retention and teardown are the two inputs this scenario grades, and both
# are stated rather than left to a default: `cloudwatch_logs_retention_in_days`
# defaults to `null` (never expire) and `cloudwatch_logs_skip_destroy`
# defaults to `false`. The false one is restated because it is the ticket's
# "nothing of it may be left behind" and a solution that says so does not
# change meaning if a future module version changes its default.
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

  # The module derives the group's name from `function_name`, so the group it
  # creates is exactly the `/aws/lambda/<function-name>` destination Lambda
  # falls back to -- the ownership half of the ticket.
  cloudwatch_logs_retention_in_days = 30
  cloudwatch_logs_skip_destroy      = false
}
HCL

bash tests/static_tiers.sh
