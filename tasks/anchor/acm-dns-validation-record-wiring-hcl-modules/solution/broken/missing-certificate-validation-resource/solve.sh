#!/usr/bin/env bash
# Negative fixture for the `missing-certificate-validation-resource` catch -- HAND-AUTHORED
# (SCHEMA.md §8.2 point 8), the module-arm sibling of
# ../../../../acm-dns-validation-record-wiring-hcl-raw/solution/broken/missing-certificate-validation-resource/solve.sh.
# Regenerating this scenario will NOT overwrite this file.
#
# Both validation records are planned correctly, but `wait_for_validation =
# false` (variables.tf:25, default `true`) gates the module's
# `aws_acm_certificate_validation` `count` to 0 (main.tf:69): nothing in the
# plan ever waits for ACM to observe the records, so the load balancer the
# ticket mentions could attach to a still-PENDING_VALIDATION certificate.
#
# The BLOCK stays in `configuration` either way -- only its instance count
# changes -- which is why the tier-1 rule counts PLANNED
# `aws_acm_certificate_validation` resources rather than configuration ones.
# Tier 0 passes in full; `validation-waits-for-records` denies.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_route53_zone" "storefront" {
  name = "storefront.example.com"
}

module "certificate" {
  source  = "terraform-aws-modules/acm/aws"
  version = "6.3.1"

  domain_name               = "storefront.example.com"
  subject_alternative_names = ["www.storefront.example.com"]
  validation_method         = "DNS"

  zone_id = aws_route53_zone.storefront.zone_id

  wait_for_validation = false
}
HCL

bash tests/static_tiers.sh
