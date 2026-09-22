#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf and runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): the whole
# certificate side is one `terraform-aws-modules/acm/aws` call -- that module
# authors the `aws_acm_certificate`, one `aws_route53_record` per distinct
# validated domain name (main.tf:52-54, `count = length(local.
# distinct_domain_names)` over a `distinct()`ed apex+SAN list) and the
# `aws_acm_certificate_validation` that waits on them (main.tf:69), which is
# exactly the graph this scenario asks for. The hosted zone has NO module
# counterpart in this arm's vendored set (`terraform-aws-modules/route53`
# creates records and delegation sets, not the zone this scenario needs
# created here), so it stays a raw `aws_route53_zone` -- and wiring that raw
# zone into the module through `zone_id` is what makes the two records land
# in the zone this configuration creates rather than in nothing.
#
# `validation_method = "DNS"` is explicit: the module's own default is `null`
# (variables.tf:61), which plans a certificate with no validation method at
# all and no records.
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

  # The zone created above, threaded into the module: every validation record
  # the module plans reads this for its own `zone_id` (main.tf:54).
  zone_id = aws_route53_zone.storefront.zone_id
}
HCL

bash tests/static_tiers.sh
