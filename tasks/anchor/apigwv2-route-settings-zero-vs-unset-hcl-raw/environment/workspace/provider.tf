# cdktn-bench hcl-raw arm — provider bootstrap. NOT agent-owned: byte-copied
# unmodified into every generated task's workspace (see ../../README.md
# "Generated-task workspace split"); the agent's entry_file is main.tf.

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

  default_tags {
    tags = {
      project = "cdktn-bench"
      arm     = "hcl-raw"
    }
  }
}
