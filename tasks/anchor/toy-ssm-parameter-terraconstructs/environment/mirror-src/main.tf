// Build-time only. Consumed by `terraform providers mirror` while building the
// image (which does have network access at build time) to populate the
// filesystem provider mirror baked into the image. Never used at runtime.
//
// Version MUST match what this arm's `cdktn synth` actually emits in the
// generated `terraform.required_providers.aws.version` block (verified by
// running synth and reading cdk.tf.json — see ../Dockerfile's
// TERRAFORM_AWS_PROVIDER_VERSION comment). @cdktn/provider-aws@24.8.0 pins
// hashicorp/aws 6.52.0 — NOT the same version arms/hcl-raw mirrors (6.58.0).
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.52.0"
    }
  }
}
