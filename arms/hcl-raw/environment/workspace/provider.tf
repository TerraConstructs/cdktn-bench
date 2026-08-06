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

  default_tags {
    tags = {
      project = "cdktn-bench"
      arm     = "hcl-raw"
    }
  }
}
