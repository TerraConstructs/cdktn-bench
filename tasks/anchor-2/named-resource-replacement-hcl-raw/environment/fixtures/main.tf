# Minimal preflight fixture for the hcl-raw arm's toolchain gate.
#
# `terraform validate` needs nothing beyond the provider *schema*, which comes
# from the plugin binary in the filesystem mirror — no credentials, no network,
# no AWS account. That's the hard offline requirement this arm must satisfy.
#
# `terraform plan` is a different story: the AWS provider still has to
# *configure* an SDK client, and depending on provider version/config it may
# try to call STS (GetCallerIdentity, to validate credentials / resolve the
# account id for ARN construction) or the EC2 instance-metadata service. The
# four `skip_*` flags below plus static dummy credentials are what let plan
# succeed against a brand-new (no prior state, no data sources) resource
# without ever reaching the network — see README.md "What `terraform plan`
# needs" for the full breakdown of which flag suppresses which network call.
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

  # Dummy, non-functional credentials — never used to sign a real API call in
  # this preflight; plan only works because of the skip_* flags below.
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

resource "aws_s3_bucket" "preflight" {
  bucket = "cdktn-bench-hcl-raw-preflight-example"
}
