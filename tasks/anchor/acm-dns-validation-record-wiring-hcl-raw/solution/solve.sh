#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf (verified against a real `terraform plan` run at
# authoring time -- see specs/acm-dns-validation-record-wiring.yaml's own
# "ORACLE MUST TOLERATE / DEFEND" header comment, points 1/2/4a), then runs
# the same tests/static_tiers.sh a real trial's verifier runs. Regenerating
# this scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape choice (one of two accepted -- see the spec's own comment): two
# explicitly-named `aws_route53_record` resources, indexed directly into
# `aws_acm_certificate.storefront.domain_validation_options` by position,
# rather than a `for_each` transform. Chosen for THIS reference solution
# specifically because `for_each` over a not-yet-created certificate's own
# computed `domain_validation_options` is documented as "known only after
# apply" on first apply (tfp-aws#27299) -- this explicit shape keeps a
# reference fixture's own offline `terraform plan` unconditionally stable.
# An agent solution using `for_each` instead is equally correct and scores
# 1.0 -- the oracle (oracles/rego/acm-dns-validation-record-wiring/policy.rego)
# counts `.planned_values` instances by qualifying config address, which
# works identically for either shape.
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

# One explicit record per validated domain name (apex + www) -- NOT one
# record reused for both (that is this scenario's own
# one-record-for-two-domains catch). `type`/`name`/`records` are read from
# the certificate's own `domain_validation_options`, which is itself
# plan-time-unknown on first apply (verified directly: `terraform plan`
# shows every one of these three attributes as "(known after apply)") --
# this is expected and is why the oracle's tier-1 check never reads them,
# only the `zone_id` graph edge and the resource type/count.
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

# Waits for both records to be observed before the certificate is
# considered ISSUED -- the resource this scenario's
# missing-certificate-validation-resource catch omits.
resource "aws_acm_certificate_validation" "storefront" {
  certificate_arn         = aws_acm_certificate.storefront.arn
  validation_record_fqdns = [
    aws_route53_record.validation_apex.fqdn,
    aws_route53_record.validation_www.fqdn,
  ]
}
HCL

bash tests/static_tiers.sh
