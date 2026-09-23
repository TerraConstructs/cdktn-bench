#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-key-attribute-not-declared catch: the
# `global_secondary_indexes` input keys the index on customerId/createdAt
# while the `attributes` input omits both -- the mirror image of
# attribute-definitions-include-non-key-attributes, and the mistake the
# module's two-separate-inputs shape invites: nothing in
# dynamodb-table@5.5.2 cross-checks one list against the other.
# Reward 0.0 comes from the toolchain step itself: the provider's "all
# indexes must match a defined attribute" check fires on the module's
# rendered resource. No structural_assert or policy is ever reached.
set -euo pipefail

cat > main.tf <<'HCL'
module "orders" {
  source  = "terraform-aws-modules/dynamodb-table/aws"
  version = "5.5.2"

  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  # customerId / createdAt deliberately NOT declared here, even though the
  # index below keys on both -- this catch's own mistake.
  attributes = [
    { name = "orderId", type = "S" },
  ]

  global_secondary_indexes = [
    {
      name               = "byCustomer"
      hash_key           = "customerId"
      range_key          = "createdAt"
      projection_type    = "INCLUDE"
      non_key_attributes = ["status", "totalAmount"]
    },
  ]
}
HCL

bash tests/static_tiers.sh
