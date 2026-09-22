# Preflight fixture 1 of 3: a module the workspace names directly.
#
# What it proves: the tf-registry sidecar answers `versions` and `download`,
# the tarball it serves unpacks into `.terraform/modules`, and the module then
# `validate`s against the provider schema out of the filesystem mirror — all
# with no route to anything but loopback (`docker run --network none`).
terraform {
  required_version = ">= 1.15"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.66.0"
    }
  }
}

# Dummy, non-functional credentials plus the four skip_* flags arms/hcl-raw's
# preflight fixture uses — never used to sign a real API call. `validate` needs
# none of this; it is here so the fixture is the shape a task workspace has, and
# so a future plan attempt has one less thing to change. See
# ../../../../hcl-raw/README.md "What `terraform plan` needs".
provider "aws" {
  region = "us-east-1"

  access_key = "AKIAIOSFODNN7EXAMPLE"
  secret_key = "dummy-secret-key-not-real"

  skip_credentials_validation = true
  skip_requesting_account_id  = true
  skip_region_validation      = true
  skip_metadata_api_check     = true

  default_tags {
    tags = {
      project = "cdktn-bench"
      arm     = "hcl-modules"
    }
  }
}

module "preflight_bucket" {
  source  = "terraform-aws-modules/s3-bucket/aws"
  version = "5.16.1"

  bucket = "cdktn-bench-hcl-modules-preflight-example"
}
