#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the no-validation-records-at-all catch: the zone and
# certificate are created, and nothing else -- no aws_route53_record, no
# aws_acm_certificate_validation. Plan-green (tier 0 passes in full: zone
# exists, certificate exists with the right domain/SAN/validation method).
# Reward must be 0.0 from tier-1 (policy.rego) alone --
# validation-records-one-per-domain fires on count 0 != 2, and
# validation-waits-for-records fires on zero
# aws_acm_certificate_validation resources existing at all.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_route53_zone" "storefront" {
  name = "storefront.example.com"
}

resource "aws_acm_certificate" "storefront" {
  domain_name               = "storefront.example.com"
  subject_alternative_names = ["www.storefront.example.com"]
  validation_method          = "DNS"
}
HCL

bash tests/static_tiers.sh
