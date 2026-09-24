#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `alias-still-serves-the-previous-version`, whose predicted_tier_caught is
# "0" on this arm.
#
# THE MISTAKE: the plausible, competent-looking answer. It makes exactly the
# change the ticket asks for -- `QUOTE_CURRENCY` becomes `USD` -- and touches
# nothing else. It validates, it plans, and it applies CLEANLY: `publish = true`
# cuts version 2 with the new configuration. The alias call, still carrying the
# literal `function_version = "1"`, goes on naming version 1, whose immutable
# snapshot still says `EUR`.
#
# WHY IT IS STILL A TIER-0 FIXTURE ONCE THE ALIAS IS MODULE-AUTHORED:
# `lambda//modules/alias` 8.8.2 passes `function_version` straight through to
# `aws_lambda_alias.with_refresh`, and the plan normaliser hoists that resource
# out of the module body into `root_module.resources`, so
# `.planned_values...aws_lambda_alias.values.function_version` reads `"1"` here
# and is ABSENT for the reference (known-after-apply, because the value now
# comes from the function module's own output). The tier-0 assert
# `alias-is-no-longer-pinned-to-the-seeds-version` refuses the SEED's value
# rather than demanding a shape, so it fails here and passes for both accepted
# answers.
#
# Expected verdict: reward 0.0, caught at tier 0.
set -euo pipefail

cat > main.tf <<'HCL'
module "quote_service_packages" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket_prefix = "cdktn-bench-quote-service-"
  force_destroy = true
}

module "quote_service_package" {
  source  = "terraform-aws-modules/s3-bucket/aws//modules/object"
  version = "5.16.1"

  bucket         = module.quote_service_packages.s3_bucket_id
  key            = "quote-service.zip"
  content_base64 = "UEsDBBQAAAAIAAAAIVwSlli1eAAAAHoAAAAIAAAAaW5kZXguanMNybEKgzAQANA9X3FjAhKko8UuwaWDUluHTiVNrlUoidzF0iD+e13fw98cKbEebfAfJKjBcg4OpIL6BHIVAJxsWthEjxUcyrLY6Rl9ruB87VrNiabwnl5ZruAWIgxur5miQ2aN4asvQ3drHmbo+6Y1d9hUITZ1FH9QSwECFAMUAAAACAAAACFcEpZYtXgAAAB6AAAACAAAAAAAAAAAAAAApAEAAAAAaW5kZXguanNQSwUGAAAAAAEAAQA2AAAAngAAAAAA"
}

module "quote_service" {
  source  = "terraform-aws-modules/lambda/aws"
  version = "8.8.2"

  function_name = "cdktn-bench-quote-service"
  handler       = "index.handler"
  runtime       = "nodejs22.x"

  create_package = false

  s3_existing_package = {
    bucket = module.quote_service_packages.s3_bucket_id
    key    = module.quote_service_package.s3_object_id
  }

  publish = true

  environment_variables = {
    QUOTE_CURRENCY = "USD"
  }
}

module "quote_service_live" {
  source  = "terraform-aws-modules/lambda/aws//modules/alias"
  version = "8.8.2"

  name             = "quote-service-live"
  function_name    = module.quote_service.lambda_function_name
  function_version = "1"
}
HCL

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: this apply is EXPECTED to succeed and to leave the alias behind =="
  terraform init -input=false
  # FIXTURE SELF-PROOF: `--expect stale` alone cannot tell this catch from a
  # no-op, because workspace_seed.deploy has the harness put the euro-serving
  # alias in the account BEFORE this script starts -- `fail_stale` is true by
  # construction until something changes it. The discriminating fact is that
  # the apply must SUCCEED and the alias must still be stale afterwards.
  DEPLOY_LOG=/tmp/lambda-alias-broken-hcl-modules.log
  set +e
  terraform apply -input=false -auto-approve > "$DEPLOY_LOG" 2>&1
  deploy_rc=$?
  set -e
  cat "$DEPLOY_LOG"
  if [ "$deploy_rc" -ne 0 ]; then
    echo "FIXTURE PROOF FAILED: the apply exited $deploy_rc." >&2
    echo "This fixture exists to pin a change that APPLIES CLEANLY and is still" >&2
    echo "wrong. A failed apply also reaches live_check's 'fail_stale', so" >&2
    echo "accepting it would let a broken toolchain wear this catch's costume." >&2
    echo "Log: $DEPLOY_LOG" >&2
    exit 1
  fi
  echo "== apply succeeded, as this fixture requires; now asking the account =="
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
