#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the missing-certificate-validation-resource catch:
# both DNS validation records are authored correctly (one per domain,
# correctly zone-scoped), but no aws_acm_certificate_validation resource
# exists at all -- nothing in the plan ever waits for the records to be
# observed. Plan-green in full, and validation-records-one-per-domain
# itself PASSES (count is exactly 2). Reward must be 0.0 from tier-1 alone
# -- validation-waits-for-records fires on zero
# aws_acm_certificate_validation resources existing anywhere.
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

resource "aws_route53_record" "validation_apex" {
  zone_id         = aws_route53_zone.storefront.zone_id
  name            = tolist(aws_acm_certificate.storefront.domain_validation_options)[0].resource_record_name
  type            = tolist(aws_acm_certificate.storefront.domain_validation_options)[0].resource_record_type
  records         = [tolist(aws_acm_certificate.storefront.domain_validation_options)[0].resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_route53_record" "validation_www" {
  zone_id         = aws_route53_zone.storefront.zone_id
  name            = tolist(aws_acm_certificate.storefront.domain_validation_options)[1].resource_record_name
  type            = tolist(aws_acm_certificate.storefront.domain_validation_options)[1].resource_record_type
  records         = [tolist(aws_acm_certificate.storefront.domain_validation_options)[1].resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

# THE MISTAKE: no aws_acm_certificate_validation -- nothing ever waits for
# the two records above to be observed by ACM.
HCL

bash tests/static_tiers.sh
