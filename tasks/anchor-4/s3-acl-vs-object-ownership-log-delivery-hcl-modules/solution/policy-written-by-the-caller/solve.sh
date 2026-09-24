#!/usr/bin/env bash
# SECOND REFERENCE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). A CORRECT
# solution in the other accepted shape, required to score reward 1.0 by
# gates/oracle_falsifiability.py exactly like solution/solve.sh.
#
# WHY IT EXISTS. solution/solve.sh reaches the grant through
# `attach_access_log_delivery_policy`, the module input that writes it for you.
# An agent who does not find that input writes the grant itself, and on this arm
# the only way to write it is a root-level `aws_s3_bucket_policy` interpolating
# `module.access_logs.s3_bucket_arn`: the module's own `policy` argument is read
# BY the call, so a document derived from that call's output is a cycle. One raw
# resource beside the module calls is composition, not a bypass -- the same
# judgement acm's hosted zone gets.
# It is also what makes solution/broken/log-delivery-grant-not-migrated/'s
# static-indistinguishability proof a claim about two real solutions: that
# fixture is this file with one word changed.
set -euo pipefail

LIVE="${LIVE:-0}"
APP_DATA='
module "app_data" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  depends_on = [module.access_logs]

  bucket        = "cdktn-bench-application-storage-app-data"
  force_destroy = true

  attach_public_policy = false

  logging = {
    target_bucket = module.access_logs.s3_bucket_id
    target_prefix = "app-data/"
  }

  tags = {
    Name = "application-storage-app-data"
  }
}
'

# The destination-bucket call, with `object_ownership` and any extra module
# inputs supplied by the caller. $1 -- the ownership setting; $2 -- extra
# arguments, already indented.
access_logs_call() {
  cat <<TF
module "access_logs" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket        = "cdktn-bench-application-storage-access-logs"
  force_destroy = true

  attach_public_policy = false

  control_object_ownership = true
  object_ownership         = "${1}"
${2}
  tags = {
    Name = "application-storage-access-logs"
  }
}
TF
}

# ROLLOUT STEP 1 ONLY -- never graded. Ownership is still `ObjectWriter`, so
# `PutBucketAcl` is still legal here; this is the call that clears the
# log-delivery group grant out of the account so the next apply's
# `PutBucketOwnershipControls` is allowed to succeed.
write_acl_reset() {
  {
    access_logs_call "ObjectWriter" ""
    cat <<'TF'

resource "aws_s3_bucket_acl" "access_logs" {
  depends_on = [module.access_logs]

  bucket = module.access_logs.s3_bucket_id
  acl    = "private"
}
TF
    printf '%s\n' "$APP_DATA"
  } > main.tf
}

# ACLs disabled, and the grant written out by the caller as a root-level
# `aws_s3_bucket_policy`. $1 -- the service principal it grants to. The document
# interpolates `module.access_logs.s3_bucket_arn`, so it is plan-time-unknown
# and never reaches the graded artifact -- which is also why handing the same
# document to the module's own `policy` input is not an option: that argument is
# read BY the call, and a value derived from the call's own output is a cycle.
write_caller_policy_shape() {
  {
    access_logs_call "BucketOwnerEnforced" ""
    cat <<TF

resource "aws_s3_bucket_policy" "access_logs" {
  bucket = module.access_logs.s3_bucket_id

  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [
      {
        Sid       = "S3ServerAccessLogsPolicy"
        Effect    = "Allow"
        Principal = { Service = "${1}" }
        Action    = ["s3:PutObject"]
        Resource  = "\${module.access_logs.s3_bucket_arn}/app-data/*"
        Condition = {
          ArnLike = { "aws:SourceArn" = module.app_data.s3_bucket_arn }
        }
      },
    ]
  })
}
TF
    printf '%s\n' "$APP_DATA"
  } > main.tf
}

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 1/2: reset the destination bucket's ACL while ACLs are still enabled =="
  write_acl_reset
  terraform init -input=false
  terraform apply -input=false -auto-approve
fi

write_caller_policy_shape "logging.s3.amazonaws.com"

if [ "$LIVE" = "1" ]; then
  echo "== LIVE step 2/2: disable ACLs and carry the grant on a hand-written bucket policy =="
  terraform init -input=false
  terraform apply -input=false -auto-approve
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
