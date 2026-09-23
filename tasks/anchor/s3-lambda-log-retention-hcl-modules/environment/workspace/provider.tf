# cdktn-bench hcl-modules arm — provider bootstrap. NOT agent-owned: byte-copied
# unmodified into every generated task's workspace (see ../../README.md and
# ../../../hcl-raw/README.md "Generated-task workspace split"); the agent's
# entry_file is main.tf.
#
# Identical to arms/hcl-raw/environment/workspace/provider.tf apart from the
# `arm` tag, on purpose: the two Terraform arms differ only in whether the
# agent composes registry modules, so a provider-configuration difference
# between them would be a confound in every cross-arm comparison.

terraform {
  required_version = ">= 1.15"
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.66.0"
    }
  }
}

provider "aws" {
  region = "us-east-1"

  default_tags {
    tags = {
      project = "cdktn-bench"
      arm     = "hcl-modules"
    }
  }
}
