# Preflight fixture 3 of 4: a registry module that calls its OWN submodules by
# relative path.
#
# ecs 7.6.1's root main.tf calls `./modules/cluster` and `./modules/service`,
# and the latter calls `../container-definition`, so `.terraform/modules/
# modules.json` records three entries whose `Source` is a RELATIVE PATH and not
# a registry address. That is what this fixture exists to put on the record:
# Amendment 46 (c)'s second half reads "a modules.json Source that is not a
# registry source is a deny", and applied literally to every entry it would
# refuse ecs, eks and rds — legitimate registry modules, denied for their own
# internals. The rule the phase-5 verifier has to implement is scoped to the
# calls the ROOT module makes (a `Key` with no dot); everything below one of
# those belongs to the installed module's own tree.
#
# preflight.sh asserts both halves here: the root call is a registry source,
# and at least three nested entries are not — so the scoped rule is exercised
# rather than passing vacuously the way it does on the other two fixtures.
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
# preflight fixture uses — never used to sign a real API call. See
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

module "preflight_cluster" {
  source  = "terraform-aws-modules/ecs/aws"
  version = "7.6.1"

  cluster_name = "cdktn-bench-hcl-modules-preflight"
}
