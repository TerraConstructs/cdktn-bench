#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-projection-type-is-keys-only-not-include
# catch: sets `projection_type = "KEYS_ONLY"` instead of "INCLUDE", and
# omits `non_key_attributes` (KEYS_ONLY neither needs nor accepts one).
# This is a complete, valid projection on its own -- `terraform validate`
# and `terraform plan` both SUCCEED (verified directly at authoring time)
# -- so nothing here is toolchain-caught. Caught by the two tier-0 asserts
# already in this scenario: `gsi-projection-is-include` (expected
# "INCLUDE", resolved "KEYS_ONLY") and
# `gsi-projects-exactly-status-and-total` (expected {status, totalAmount},
# resolved [] -- KEYS_ONLY has no non_key_attributes at all).
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_dynamodb_table" "orders" {
  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  attribute {
    name = "orderId"
    type = "S"
  }
  attribute {
    name = "customerId"
    type = "S"
  }
  attribute {
    name = "createdAt"
    type = "S"
  }

  global_secondary_index {
    name            = "byCustomer"
    hash_key        = "customerId"
    range_key       = "createdAt"
    # Deliberate mistake: KEYS_ONLY instead of INCLUDE -- the listing
    # needs status/totalAmount without a second read, which KEYS_ONLY
    # does not provide.
    projection_type = "KEYS_ONLY"
  }
}
HCL

bash tests/static_tiers.sh
