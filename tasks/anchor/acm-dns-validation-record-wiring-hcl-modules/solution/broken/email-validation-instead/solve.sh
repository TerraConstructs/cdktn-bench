#!/usr/bin/env bash
# Negative fixture for the `email-validation-instead` catch -- HAND-AUTHORED
# (SCHEMA.md §8.2 point 8), the module-arm sibling of
# ../../../../acm-dns-validation-record-wiring-hcl-raw/solution/broken/email-validation-instead/solve.sh.
# Regenerating this scenario will NOT overwrite this file.
#
# `validation_method` is a plain passthrough (variables.tf:61 -> main.tf:22),
# so `"EMAIL"` reaches the planned certificate unchanged and unrejected,
# exactly as the hand-written literal does on hcl_raw. EMAIL validation needs
# a human to click a link in mail sent to admin@/administrator@/hostmaster@/
# postmaster@/webmaster@ at the domain, which the ticket rules out. Caught at
# TIER 0 by `validation-method-is-dns`. (The module also plans no validation
# records when the method is not DNS, so tier 1 would deny too -- tier 0 runs
# first and is the tier that decides it, same as on the other three arms.)
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
  validation_method         = "EMAIL"

  zone_id = aws_route53_zone.storefront.zone_id

}
HCL

bash tests/static_tiers.sh
