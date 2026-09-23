# Preflight fixture 2 of 3: a module whose OWN source resolves a second module.
#
# route53 6.5.1's main.tf:114 calls `terraform-aws-modules/kms/aws` at 4.0.0
# with no `count`/`for_each` on the call, so `init` must fetch kms 4.0.0 from
# the sidecar even though `enable_dnssec` defaults false and the key is never
# created. That second hop is why the allowlist carries kms twice (4.2.2, the
# version an agent would pick, and this pinned 4.0.0): a responder that served
# only the newest version of each name would pass fixture 1 and fail here.
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

module "preflight_zone" {
  source  = "terraform-aws-modules/route53/aws"
  version = "6.5.1"

  name = "cdktn-bench-hcl-modules-preflight.example.com"
}
