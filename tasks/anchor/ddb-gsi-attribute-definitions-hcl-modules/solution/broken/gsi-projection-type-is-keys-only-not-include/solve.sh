#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-projection-type-is-keys-only-not-include
# catch: the index's `projection_type` is KEYS_ONLY and `non_key_attributes`
# is omitted (KEYS_ONLY neither needs nor accepts one). A complete, valid
# projection, so nothing is toolchain-caught; the module passes the value
# through untouched (`global_secondary_indexes` is type `any`).
# Caught at tier 1 by oracles/rego/ddb-gsi-attribute-definitions/policy.rego:
# projection_type is not INCLUDE, and the projected set is empty rather
# than {status, totalAmount}.
set -euo pipefail

cat > main.tf <<'HCL'
module "orders" {
  source  = "terraform-aws-modules/dynamodb-table/aws"
  version = "5.5.2"

  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  attributes = [
    { name = "orderId", type = "S" },
    { name = "customerId", type = "S" },
    { name = "createdAt", type = "S" },
  ]

  global_secondary_indexes = [
    {
      name      = "byCustomer"
      hash_key  = "customerId"
      range_key = "createdAt"
      # Deliberate mistake: KEYS_ONLY instead of INCLUDE -- the listing
      # needs status/totalAmount without a second read of the whole item.
      projection_type = "KEYS_ONLY"
    },
  ]
}
HCL

bash tests/static_tiers.sh
