#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the include-projection-without-non-key-attributes
# catch: `projection_type = "INCLUDE"` with `non_key_attributes` omitted.
# As on hcl_raw this is NOT a toolchain rejection -- the provider accepts
# it and resolves the projected list to `[]` -- and the module adds no
# check of its own (`lookup(..., "non_key_attributes", null)`,
# dynamodb-table@5.5.2 main.tf:64).
# Caught at tier 1 by oracles/rego/ddb-gsi-attribute-definitions/policy.rego:
# an empty projected set can never equal {status, totalAmount}.
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
      name            = "byCustomer"
      hash_key        = "customerId"
      range_key       = "createdAt"
      projection_type = "INCLUDE"
      # non_key_attributes deliberately omitted -- this catch's own mistake
    },
  ]
}
HCL

bash tests/static_tiers.sh
