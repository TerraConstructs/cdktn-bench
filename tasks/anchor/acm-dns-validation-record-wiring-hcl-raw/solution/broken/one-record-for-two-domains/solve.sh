#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the one-record-for-two-domains catch -- THE
# PLAUSIBLE-WRONG SOLUTION (see specs/acm-dns-validation-record-wiring.yaml's
# own catch description for the tfp-aws citations): exactly ONE
# aws_route53_record is authored, built from
# domain_validation_options[0], and reused as the sole input to
# aws_acm_certificate_validation. Whichever domain that index happens to
# be, the OTHER one never gets its own challenge record. Plan-green in
# full (this is syntactically a completely valid single record + a
# validation resource that does reference it). Reward must be 0.0 from
# tier-1 alone -- validation-records-one-per-domain fires on count 1 != 2.
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

# THE MISTAKE: one record, reused for "the" validation -- never a second
# one for the other SAN.
resource "aws_route53_record" "validation" {
  zone_id         = aws_route53_zone.storefront.zone_id
  name            = tolist(aws_acm_certificate.storefront.domain_validation_options)[0].resource_record_name
  type            = tolist(aws_acm_certificate.storefront.domain_validation_options)[0].resource_record_type
  records         = [tolist(aws_acm_certificate.storefront.domain_validation_options)[0].resource_record_value]
  ttl             = 60
  allow_overwrite = true
}

resource "aws_acm_certificate_validation" "storefront" {
  certificate_arn         = aws_acm_certificate.storefront.arn
  validation_record_fqdns = [aws_route53_record.validation.fqdn]
}
HCL

bash tests/static_tiers.sh
