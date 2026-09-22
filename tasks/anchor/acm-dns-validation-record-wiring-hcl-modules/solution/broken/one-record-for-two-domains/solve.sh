#!/usr/bin/env bash
# Negative fixture for the `one-record-for-two-domains` catch -- HAND-AUTHORED
# (SCHEMA.md §8.2 point 8), the module-arm sibling of
# ../../../../acm-dns-validation-record-wiring-hcl-raw/solution/broken/one-record-for-two-domains/solve.sh.
# Regenerating this scenario will NOT overwrite this file.
#
# `distinct_domain_names` (variables.tf:120, default `[]`) is taken VERBATIM
# ahead of the module's own `distinct()` of apex+SANs
# (`coalescelist(var.distinct_domain_names, distinct(...))`, main.tf:6), so
# naming only the apex plans exactly ONE validation record while the
# certificate still carries the `www` SAN. The apex validates; `www` is left
# in PENDING_VALIDATION with no record of its own -- the same wrong end state
# the hcl_raw fixture reaches by indexing `domain_validation_options[0]`, here
# reached through the module's own interface. Tier 0 passes in full;
# `validation-records-one-per-domain` denies with "found 1".
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

  distinct_domain_names = ["storefront.example.com"]
}
HCL

bash tests/static_tiers.sh
