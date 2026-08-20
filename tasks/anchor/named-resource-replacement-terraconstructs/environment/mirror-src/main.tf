// Build-time only. Consumed by `terraform providers mirror` while building the
// image (which does have network access at build time) to populate the
// filesystem provider mirror baked into the image. Never used at runtime.
//
// Version MUST match what this arm's `cdktn synth` actually emits in the
// generated `terraform.required_providers.aws.version` block (verified by
// running synth and reading cdk.tf.json — see ../Dockerfile's
// TERRAFORM_AWS_PROVIDER_VERSION comment). @cdktn/provider-aws@24.8.0 pins
// hashicorp/aws 6.52.0 — NOT the same version arms/hcl-raw mirrors (6.58.0).
//
// hashicorp/archive 2.8.0 added by the "apigw-openapi / terraconstructs arm
// -- catch cannot fire at all in the real image" fix (benchmark-integrity
// review, 2026-08-06): `@cdktn/provider-archive@13.1.0` (this arm's own
// package.json peerDependency) always tracks hashicorp/archive `~> 2.2`,
// currently `2.8.0` -- verified against the installed package's own
// README.md ("Terraform archive provider version 2.8.0"). Any reference
// solution or negative fixture using `compute.Code.fromInline(...)`
// (InlineCode.bind() constructs a `@cdktn/provider-archive` DataArchiveFile,
// lib/aws/compute/code.js:40/:332) synthesizes a stack whose
// required_providers block names BOTH hashicorp/aws and hashicorp/archive;
// without this entry, `terraform init` failed offline
// ("provider registry.terraform.io/hashicorp/archive was not found in any
// of the search locations") for every solution/negative fixture that uses
// the arm's own idiomatic inline-code L2 path, making the affected catches
// undiscriminating on this arm for a reason that had nothing to do with the
// catch itself.
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.52.0"
    }
    archive = {
      source  = "hashicorp/archive"
      version = "2.8.0"
    }
  }
}
