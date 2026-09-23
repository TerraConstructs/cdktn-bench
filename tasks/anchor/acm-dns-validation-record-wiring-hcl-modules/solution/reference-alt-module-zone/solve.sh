#!/usr/bin/env bash
# Alternate reference -- HAND-AUTHORED, required to score 1.0 by
# `make falsifiability`. Regenerating this scenario will NOT overwrite it.
#
# The shape a real trial on this arm produced: the hosted zone comes from a
# `terraform-aws-modules/route53` call too, so the acm module's `zone_id`
# names a module OUTPUT (`module.route53_zone.id`) instead of a raw
# `aws_route53_zone.<name>.zone_id`. The records still land in the zone this
# configuration creates, which is what the oracle's "referencing the hosted
# zone created in this configuration" means -- the policy's
# `created_zone_call_prefixes` is what makes that reading hold, and this
# fixture is its proof. The sibling ../solve.sh keeps the raw-zone shape.
set -euo pipefail

cat > main.tf <<'HCL'
module "route53_zone" {
  source  = "terraform-aws-modules/route53/aws"
  version = "6.5.1"

  name = "storefront.example.com"
}

module "acm" {
  source  = "terraform-aws-modules/acm/aws"
  version = "6.3.1"

  domain_name               = "storefront.example.com"
  subject_alternative_names = ["www.storefront.example.com"]

  zone_id = module.route53_zone.id

  validation_method    = "DNS"
  validate_certificate = true
  wait_for_validation  = true
}
HCL

bash tests/static_tiers.sh
