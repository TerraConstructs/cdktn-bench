// Build-time only. Consumed by `terraform providers mirror` while building the
// image (which does have network access at build time) to populate the
// filesystem provider mirror baked into the image. Never used at runtime.
terraform {
  required_providers {
    aws = {
      source  = "hashicorp/aws"
      version = "6.58.0"
    }
  }
}
