#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# ONE authoritative `aws_s3_bucket_notification` resource wires BOTH
# requirements (Product: upload -> lambda; Compliance: delete -> sns).
#
# ROUND-7 CORRECTION (2026-08-22). This header used to call that "the only
# correct TF shape, per this scenario's own spec.yaml header comment". Both
# halves of that sentence were false and it is superseded here, not
# preserved: the spec says no such thing (its "oracle must tolerate/defend"
# point 2 says the opposite), and EventBridge fan-out
# (`aws_s3_bucket_notification { eventbridge = true }` +
# `aws_cloudwatch_event_rule`/`_target` per consumer) is a real,
# provider-documented, provider-RECOMMENDED TF shape for exactly this
# two-independent-teams framing. One authoritative
# `aws_s3_bucket_notification` is the shape THIS ticket asks for, not the
# only correct one in general: the ticket's own sentence ("Both signals
# need to come straight from the bucket itself, not through any shared
# notification or messaging layer other teams might also be plugged into")
# is what excludes the EventBridge shared-bus indirection, and equally the
# S3 -> SNS -> Lambda relay shape. Within the direct-wiring family the
# ticket does ask for, ONE notification resource per bucket is forced by
# the API rather than chosen: S3's PutBucketNotificationConfiguration is
# one document per bucket with no create/update distinction, so two
# `aws_s3_bucket_notification` resources overwrite each other -- that is
# the headline catch, and it is not an alternative shape.
# See specs/s3-notification-authoritative-singleton.yaml "oracle must
# tolerate/defend" point 2 for the full statement this header now matches.
#
# ROUND-8 NOTE (2026-08-23), EXTENDED AT ROUND 9, RE-AUTHORED AT ROUND 12
# -- why both ARNs are hoisted into a `locals` block below, and why they
# are hoisted as ONE MAP. The bucket ARN is referenced twice (the invoke
# permission's `source_arn` and the topic policy's `aws:SourceArn`
# condition) and the topic ARN three times (the topic policy's `arn`, that
# policy's own `Resource`, and the notification's `topic_arn`), so hoisting
# both is the ordinary DRY move; they are written that way here on purpose,
# as the STANDING CONTROL for the arm-parity fixes of rounds 8, 9 and 12.
# An adversarial verifier PROVED by execution, three times, that these
# exact hoists used to score reward 0.0 on hcl_raw while the byte-for-byte
# equivalent decision on awscdk (a plain `const mediaBucketArn =
# bucket.bucketArn`, or `const arns = { mediaBucket: bucket.bucketArn, ... }`)
# scored 1.0 -- because `terraform show -json` does not emit locals and the
# graph-edge rules could not follow the hop.
#
# ROUND 12 (2026-08-23) is why the two flat locals became one map. The
# round-11 policy matched reference strings BY PREFIX, and terraform emits
# the container of a traversal alongside the traversal itself
# (`source_arn = local.arns.media_bucket` reads as
# `["local.arns.media_bucket", "local.arns"]`), so the shared `local.arns`
# made the bucket slot and the topic slots collide: this file, in exactly
# the shape below, scored 0.0 on hcl_raw against 1.0 for its awscdk twin,
# with a deny message that was factually FALSE about it (RULING 3). The
# single-map spelling is therefore the checked-in reference shape now, so
# that `make falsifiability` proves it accepted on EVERY run instead of
# leaving the correction assumed. The flat `local.x` spelling stays
# exercised, both as an ACCEPTED spelling (every broken/ fixture below that
# hoists -- e.g. `lambda-permission-scoped-to-a-laundered-literal`, whose
# topic policy `arn = local.audit_topic_arn` must pass the attachment rule
# so the fixture fails at its own defect and nowhere else) and as a
# REJECTED one where it denotes the wrong thing
# (`lambda-permission-scoped-to-the-topic-arn-behind-a-local`,
# `lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-local`,
# `sns-topic-policy-attached-to-a-lambda-arn-behind-a-local`).
#
# `policy.rego` accepts the hop in every DEDICATED SINGLE-ARN ARGUMENT SLOT
# -- `source_arn` and the topic policy's `arn` alike -- but only on
# POSITIVE evidence the artifact really carries (round 12): the plan must
# not resolve the slot to a constant, the plan's own `relevant_attributes`
# must show this configuration depending on an `arn` of the required
# resource type, and the attachment slot's symbol must also appear in a
# slot that WIRES the topic. See that file's ROUND-12 block for the two
# executed proofs and for the one residual it deliberately does not claim
# to have closed. The DIRECT `aws_s3_bucket.<name>.arn` /
# `aws_sns_topic.<name>.arn` spellings stay exercised too: most broken/
# fixtures write them (they must pass these rules and fail only their own),
# and the terraconstructs arm's reference solution -- graded by this same
# policy.rego -- synthesizes them, since cdktn never emits locals.
#
# function.zip is a placeholder --
# this scenario's oracle is plan-only (never apply), so its actual byte
# content is never graded, same convention as s3-lambda-log-retention's
# own reference solution.
#
# ROUND-13 CORRECTION (2026-08-23). The header above describes the ROUND-12
# mechanism, and that mechanism no longer exists. `config_reaches_arn_of`,
# `relevant_attributes`-based positive evidence, `slot_is_plan_time_unknown`,
# `bucket_denoting_indirections`, `topic_target_indirections` and
# `deepest_refs` were all DELETED from
# oracles/rego/s3-notification-authoritative-singleton/policy.rego. The
# hcl_raw arm now parses the agent's own `.tf` with `hcl2json` and merges it
# into the oracle input (`oracle.hcl_traversal`, specs/SCHEMA.md sect 4.6),
# so a `local.` symbol is RESOLVED to the resource attribute it names rather
# than reasoned about circumstantially.
#
# THIS FILE IS UNCHANGED and still scores 1.0 -- which is the point of it.
# It is the STANDING CONTROL for the arm-parity fixes of rounds 8, 9, 12 and
# now 13: the one-map DRY hoist it is authored in must be accepted on every
# arm, and `make falsifiability` re-proves that on every run rather than
# leaving it assumed. Under round 13 both of its hoisted symbols resolve --
# `local.arns.media_bucket` -> `aws_s3_bucket.media.arn`,
# `local.arns.audit_topic` -> `aws_sns_topic.audit.arn` -- and both name the
# same resource INSTANCES this file's own `aws_s3_bucket_notification`
# wires, so the acceptance is now positive evidence about the artifact
# rather than tolerated unresolvability.
#
# One thing this file no longer has to be careful about: round 12 DENIED a
# correct solution that hoisted the topic ARN for `aws_sns_topic_policy.arn`
# and spelled the notification's `topic_arn` DIRECTLY, because its
# corroboration clause required the SAME SYMBOL in both slots. Round 13
# compares REFERENTS, so that mixed spelling is accepted too. Read
# policy.rego's ROUND 13 block for what replaced the machinery this header
# names.
set -euo pipefail

printf 'placeholder-lambda-package-not-a-real-zip-plan-only-oracle-never-reads-it' > function.zip

cat > main.tf <<'HCL'
locals {
  # media_bucket is referenced twice below (the invoke permission and the
  # topic policy's condition); audit_topic three times (the topic policy's
  # own `arn`, that policy's `Resource`, and the notification's
  # `topic_arn`). One map, the ordinary DRY spelling.
  arns = {
    media_bucket = aws_s3_bucket.media.arn
    audit_topic  = aws_sns_topic.audit.arn
  }
}

resource "aws_s3_bucket" "media" {
  bucket = "cdktn-bench-media-ingest-media"
}

resource "aws_iam_role" "ingest" {
  name = "cdktn-bench-media-ingest-handler-role"
  assume_role_policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Effect    = "Allow"
      Principal = { Service = "lambda.amazonaws.com" }
      Action    = "sts:AssumeRole"
    }]
  })
}

resource "aws_lambda_function" "ingest" {
  function_name = "cdktn-bench-media-ingest-transcode"
  role          = aws_iam_role.ingest.arn
  handler       = "index.handler"
  runtime       = "nodejs22.x"
  filename      = "function.zip"
}

resource "aws_lambda_permission" "allow_s3_invoke" {
  statement_id  = "AllowS3Invoke"
  action        = "lambda:InvokeFunction"
  function_name = aws_lambda_function.ingest.function_name
  principal     = "s3.amazonaws.com"
  source_arn    = local.arns.media_bucket
}

resource "aws_sns_topic" "audit" {
  name = "cdktn-bench-media-ingest-audit"
}

# S3 cannot publish to a topic with no resource policy granting it
# sns:Publish -- part of "the topic must receive a notification"
# (this scenario's own oracle.intent), not an add-on. Scoped via
# aws:SourceArn to this specific bucket -- the sns-topic-policy-not-
# scoped-to-bucket catch's own target.
resource "aws_sns_topic_policy" "audit" {
  arn = local.arns.audit_topic
  policy = jsonencode({
    Version = "2012-10-17"
    Statement = [{
      Sid       = "AllowS3Publish"
      Effect    = "Allow"
      Principal = { Service = "s3.amazonaws.com" }
      Action    = "SNS:Publish"
      Resource  = local.arns.audit_topic
      Condition = {
        ArnLike = { "aws:SourceArn" = local.arns.media_bucket }
      }
    }]
  })
}

# ONE authoritative notification resource -- the headline catch of this
# scenario is declaring TWO of these (one per stakeholder ask) instead.
resource "aws_s3_bucket_notification" "media" {
  bucket = aws_s3_bucket.media.id

  lambda_function {
    lambda_function_arn = aws_lambda_function.ingest.arn
    events              = ["s3:ObjectCreated:Put"]
  }

  topic {
    topic_arn = local.arns.audit_topic
    events    = ["s3:ObjectRemoved:*"]
  }

  depends_on = [aws_lambda_permission.allow_s3_invoke, aws_sns_topic_policy.audit]
}
HCL

bash tests/static_tiers.sh
