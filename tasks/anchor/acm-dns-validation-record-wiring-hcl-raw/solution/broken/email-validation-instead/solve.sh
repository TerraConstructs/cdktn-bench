#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the email-validation-instead catch: validation_method
# is set to "EMAIL" -- a typed, valid value the provider schema never
# rejects -- so the certificate requires a human to click a confirmation
# link and can never reach ISSUED unattended. No DNS validation records
# are needed or created for this method at all. Plan-green in full (every
# other tier-0 fact -- zone, certificate, domain, SAN -- is still correct).
# Reward must be 0.0 from tier-0's own validation-method-is-dns check
# alone (a plain typed-value existence+equality check, the cheapest tier
# there is -- no tier-1 policy involvement needed to catch this one).
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_route53_zone" "storefront" {
  name = "storefront.example.com"
}

resource "aws_acm_certificate" "storefront" {
  domain_name               = "storefront.example.com"
  subject_alternative_names = ["www.storefront.example.com"]
  validation_method          = "EMAIL"
}
HCL

bash tests/static_tiers.sh
