# cdktn-bench hcl-raw arm — offline provider bootstrap.
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
# `terraform plan` needs these four `skip_*` flags + static dummy
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

provider "aws" {
  region = "us-east-1"

  # Dummy, non-functional credentials — never used to sign a real API call;
  # plan only works because of the skip_* flags below.
  access_key = "AKIAIOSFODNN7EXAMPLE"
  secret_key = "dummy-secret-key-not-real"

  skip_credentials_validation = true # don't call STS GetCallerIdentity to check creds are real
  skip_requesting_account_id  = true # don't call STS to resolve the account id for ARNs
  skip_region_validation      = true # don't validate region name against a partition list
  skip_metadata_api_check     = true # don't probe the EC2 instance-metadata service

  # See this file's own header comment ("endpoints.sfn") for why this
  # exists. Verified: `sfn` (not `states`/`stepfunctions`) is the correct
  # endpoints{} block key for this provider version — confirmed empirically
  # (a real `terraform plan` against a hand-built aws_sfn_state_machine
  # config, pointed at a real mock-sfn.py responder on this port, produced
  # "Plan: 2 to add, 0 to change, 0 to destroy" with zero network
  # reachability beyond loopback), matching names/data/names_data.hcl's own
  # `service "sfn" { ... provider_package_correct = "sfn" }` entry in the
  # hashicorp/terraform-provider-aws source.
  endpoints {
    sfn = "http://127.0.0.1:17772"
  }

  default_tags {
    tags = {
      project = "cdktn-bench"
      arm     = "hcl-raw"
    }
  }
}
