# cdktn-bench hcl-raw arm — offline/live provider bootstrap.
#
# NOT agent-owned. This file is byte-copied unmodified into every generated
# task's workspace (generator/gen.py::write_environment() copytree's the
# whole environment/ tree, then overwrites ONLY main.tf) and is never
# regenerated per scenario — same non-agent-editable-bootstrap role as
# arms/awscdk's bin/app.ts. The task's own instruction.md tells the agent
# not to modify it (generator/gen.py::ownership_note()).
#
# Why this is split out of main.tf (../../../DECISIONS.md-adjacent finding,
# fixed alongside the generator's split): main.tf is this arm's
# output_contract.entry_file — the file a normal agent solution *fully
# rewrites* from scratch (there is no reason for an agent authoring "hand-
# written Terraform HCL" to preserve boilerplate it never wrote and the
# instruction never mentions). When the provider block used to live at the
# top of main.tf, a correct-but-bare agent rewrite silently deleted the
# skip_*/dummy-credential fixture lines below, and `terraform plan` failed
# offline with "No valid credential sources found" — scoring a CORRECT
# solution 0.0. Keeping this block in a separate, non-entry file means a
# full main.tf rewrite can never touch it.
#
# --- OFFLINE vs. LIVE switch (benchmark-integrity review finding 2,
# 2026-08-07) -----------------------------------------------------------
# This file used to hardcode `access_key`/`secret_key` unconditionally,
# which OUTRANKS every ambient credential source (env vars, shared config,
# IMDS role) in the AWS provider's own resolution order — making a REAL
# `terraform apply` against this account impossible for any scenario that
# needs one (apigw-redeploy, verifier.live_check.enabled=true), even
# though the agent is instructed not to touch this file. The
# `var.cdktn_bench_live` switch below (default false — BYTE-IDENTICAL
# offline behavior to before this fix for every scenario that never sets
# it) fixes this without any per-scenario templating:
#   - default (false, i.e. every `terraform` invocation that doesn't
#     explicitly export `TF_VAR_cdktn_bench_live=1`): `access_key`/
#     `secret_key` stay the dummy literals below, the four `skip_*` flags
#     stay on, and `endpoints.sfn` stays pointed at the loopback mock --
#     exactly today's offline-plan fixture, unchanged.
#   - `TF_VAR_cdktn_bench_live=1` (set by whoever is about to run a REAL
#     `terraform apply` against account 886312446417 -- the reference
#     solution's own solve.sh LIVE=1 path does this, and a real agent
#     solving apigw-redeploy needs to do the same, see that scenario's
#     instruction.md): `access_key`/`secret_key` become `null` (omitted,
#     not empty-string -- verified directly against terraform 1.15.8 +
#     hashicorp/aws 6.58.0 that `null` here correctly falls through to the
#     provider's own default credential chain, i.e. real
#     `AWS_ACCESS_KEY_ID`/`AWS_SECRET_ACCESS_KEY`/`AWS_SESSION_TOKEN` env
#     vars staged by the trial -- the same ambient-credential mechanism
#     arms/awscdk's bin/app.ts already relies on), and the `endpoints.sfn`
#     override is dropped (a `dynamic` block, confirmed to work inside a
#     `provider` block against this same terraform/provider pin) so any
#     real `aws_sfn_state_machine` calls go to real AWS, not loopback.
#
#     `skip_requesting_account_id` is LIVE-CONDITIONAL too (fix-round-3,
#     2026-08-07 -- benchmark-integrity review finding B-hcl-1): the header
#     above USED TO claim all four `skip_*` flags were "harmless for a real
#     apply" -- THAT CLAIM WAS FALSE for this one flag and is corrected
#     here. `skip_requesting_account_id = true` stops the provider from
#     ever resolving the caller's real AWS account id, which every
#     account-id-bearing COMPUTED ARN (`aws_api_gateway_rest_api.
#     execution_arn` chief among them) then renders with an EMPTY account
#     segment: `arn:aws:execute-api:us-east-1::<api-id>` instead of
#     `arn:aws:execute-api:us-east-1:886312446417:<api-id>`. Any
#     `aws_lambda_permission.source_arn` built from that broken
#     `execution_arn` never matches the real invocation source ARN API
#     Gateway presents when it calls the Lambda, so every route 500s with
#     "Internal server error" and the Lambda is NEVER INVOKED (a permission
#     denial, not a handler bug) -- reproduced live twice in account
#     886312446417 (docs/apigw-redeploy-mechanics.md's own scenario is the
#     first consumer of a real apply; see DECISIONS.md Slice G amendment
#     for the full live-proof transcript). The other three `skip_*` flags
#     (`skip_credentials_validation`, `skip_region_validation`,
#     `skip_metadata_api_check`) remain unconditionally `true` in BOTH
#     modes -- confirmed directly that leaving those three on is harmless
#     for a real apply as long as credentials are resolved via env
#     vars/shared config (skip_credentials_validation only skips an extra
#     STS sanity call; skip_metadata_api_check only disables the
#     LAST-resort IMDS fallback, never reached once env-var creds resolve
#     first; skip_region_validation only skips a static partition-list
#     lookup, unrelated to account-id resolution).
#
# `terraform plan` needs the four `skip_*` flags + static dummy
# credentials to succeed fully offline for a brand-new resource with no
# prior state and no data sources — see ../../README.md "What `terraform
# plan` needs" for the full breakdown of which flag suppresses which
# network call.
#
# `endpoints.sfn`: a SEPARATE offline-plan gap from the four `skip_*` flags
# above — `aws_sfn_state_machine`'s own `CustomizeDiff` runs a REAL
# `states:ValidateStateMachineDefinition` API call whenever `definition`
# changes (true for any brand-new resource), which none of the `skip_*`
# flags suppress (those only cover the PROVIDER's own bootstrap calls, not
# a resource's own CustomizeDiff-triggered service call) — confirmed
# against the pinned hashicorp/aws 6.58.0
# (internal/service/sfn/state_machine.go::stateMachineDefinitionValidate;
# same unresolved upstream gap as
# github.com/hashicorp/terraform-provider-aws issue #39472). Left
# unhandled, `terraform plan` for ANY scenario using `aws_sfn_state_machine`
# fails with `UnrecognizedClientException: The security token included in
# the request is invalid` against real AWS, offline or not. Pointed at
# mock-sfn.py (byte-copied alongside this file, started/stopped around the
# WHOLE `terraform plan` step by generator/gen.py's build_static_tiers_sh
# hcl_raw tf-plan-mock-sfn wrapper — mirroring
# arms/terraconstructs/environment/app/mock-sts.js's identical role for
# that arm's own offline-plan gap, `data "aws_caller_identity"`). Harmless
# no-op for every hcl_raw scenario that never touches
# `aws_sfn_state_machine` — nothing calls this endpoint unless the
# resource itself is present in the plan.
terraform {
  required_version = ">= 1.15"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.58.0"
    }
  }
}

variable "cdktn_bench_live" {
  description = "false (default): offline dummy-credential/mock-endpoint fixture, used by tests/static_tiers.sh's `terraform plan` and any other offline invocation. true (set via TF_VAR_cdktn_bench_live=1): real ambient AWS credentials, no mock endpoints -- for a genuine `terraform apply` against account 886312446417."
  type        = bool
  default     = false
}

provider "aws" {
  region = "us-east-1"

  # Dummy, non-functional credentials when offline — never used to sign a
  # real API call; plan only works because of the skip_* flags below. When
  # `cdktn_bench_live` is true, `null` here means "no explicit override" --
  # the provider falls through to its normal ambient credential chain (see
  # this file's own header comment above).
  access_key = var.cdktn_bench_live ? null : "AKIAIOSFODNN7EXAMPLE"
  secret_key = var.cdktn_bench_live ? null : "dummy-secret-key-not-real"

  skip_credentials_validation = true # don't call STS GetCallerIdentity to check creds are real
  # LIVE-CONDITIONAL (see this file's own header comment, "the four skip_*
  # flags" -- fix-round-3): leaving this `true` unconditionally corrupts
  # every account-id-bearing computed ARN (aws_api_gateway_rest_api.
  # execution_arn) on a real apply, breaking Lambda permission matching.
  # false when cdktn_bench_live -- the provider resolves the real account
  # id via STS (skip_credentials_validation above does NOT skip this; it's
  # a separate call) exactly like a real, non-benchmark `terraform apply`
  # would.
  skip_requesting_account_id = var.cdktn_bench_live ? false : true
  skip_region_validation     = true # don't validate region name against a partition list
  skip_metadata_api_check    = true # don't probe the EC2 instance-metadata service

  # See this file's own header comment ("endpoints.sfn") for why this
  # exists, and the OFFLINE vs. LIVE switch comment above for why it's
  # `dynamic` -- a real `terraform apply` (`cdktn_bench_live = true`) must
  # never be pointed at this loopback-only mock responder.
  dynamic "endpoints" {
    for_each = var.cdktn_bench_live ? [] : [1]
    content {
      sfn = "http://127.0.0.1:17772"
    }
  }

  default_tags {
    tags = {
      project = "cdktn-bench"
      arm     = "hcl-raw"
    }
  }
}
