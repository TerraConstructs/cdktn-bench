#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the attribute-definitions-include-an-unrequested-key
# catch: the module call gives the table its own `range_key = "status"` in
# addition to the requested byCustomer index. A real, always-plannable key
# shape -- `status` is genuinely used as a key, so neither the provider nor
# the module has grounds to reject it, and it simply lands in
# `values.attribute` as a fourth entry.
# Caught at tier 1 by oracles/rego/ddb-gsi-attribute-definitions/policy.rego's
# allowlist rule: the resolved attribute set is {orderId, status,
# customerId, createdAt} and `status` is not one of the three.
set -euo pipefail

cat > main.tf <<'HCL'
module "orders" {
  source  = "terraform-aws-modules/dynamodb-table/aws"
  version = "5.5.2"

  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"
  # Deliberate mistake: a table range key on `status` no ticket text asked
  # for ("each order is identified by orderId" names the table's own key as
  # orderId alone).
  range_key    = "status"

  attributes = [
    { name = "orderId", type = "S" },
    { name = "status", type = "S" },
    { name = "customerId", type = "S" },
    { name = "createdAt", type = "S" },
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
