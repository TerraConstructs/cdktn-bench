#!/usr/bin/env bash
# SECOND REFERENCE -- HAND-AUTHORED, required by gates/oracle_falsifiability.py
# to score 1.0. It is here because it is the shape that would otherwise have
# been `log-group-name-diverges-from-function`'s fixture on this arm, and
# measuring it is what established that the module removes that catch:
# `logging_log_group` (variables.tf:849) feeds BOTH the created group's
# `name` (main.tf:279) and the function's `logging_config.log_group`
# (main.tf:142), so a name that is not `/aws/lambda/<function-name>` arrives
# WIRED, which is the second mechanism this scenario's oracle accepts
# (oracle.intent: "OR the function being EXPLICITLY WIRED to it"). The
# divergence the catch traps -- a group the function does not write to --
# has no module input that produces it.
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

  # A group whose name follows no convention at all, and the function wired
  # to it from the same value.
  logging_log_group                 = "/platform/event-processor-logs"
  cloudwatch_logs_retention_in_days = 30
  cloudwatch_logs_skip_destroy      = false
}
HCL

bash tests/static_tiers.sh
