#!/usr/bin/env bash
# Negative fixture for the `no-validation-records-at-all` catch -- HAND-AUTHORED
# (SCHEMA.md §8.2 point 8), the module-arm sibling of
# ../../../../acm-dns-validation-record-wiring-hcl-raw/solution/broken/no-validation-records-at-all/solve.sh.
# Regenerating this scenario will NOT overwrite this file.
#
# The certificate and the hosted zone are both planned and the certificate
# still asks for DNS validation, but `create_route53_records = false`
# (variables.tf:78, default `true`) zeroes the module's own
# one-record-per-domain `count` (main.tf:52). Nothing in the toolchain objects
# -- it is a published boolean input -- and the plan is green: the end state is
# the hcl_raw fixture's, a certificate whose DNS challenge no record ever
# answers. Tier 0 passes in full; `validation-records-one-per-domain` denies
# with "found 0".
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

  create_route53_records = false
}
HCL

bash tests/static_tiers.sh
