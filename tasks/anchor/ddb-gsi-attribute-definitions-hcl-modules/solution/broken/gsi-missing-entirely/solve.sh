#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-missing-entirely catch: the module call
# carries only the table's own primary key and leaves
# `global_secondary_indexes` at its empty default, so the byCustomer index
# is never declared at all. A real, always-plannable shape.
#
# It also carries the same ORPHAN standalone
# `aws_dynamodb_global_secondary_index` the hcl_raw fixture carries (no
# module authors that resource type, so it stays raw here), naming a table
# that does not exist in this plan. That keeps the TABLE-ASSOCIATION FIX in
# oracles/rego/ddb-gsi-attribute-definitions/policy.rego under test on this
# arm too: an unrelated index must not satisfy the orders table's own
# existence requirement -- and here the table is a MODULE resource, hoisted
# out of `module.orders`, while the orphan is the root module's own.
# Caught at tier 1 by that policy's existence deny rule.
set -euo pipefail

cat > main.tf <<'HCL'
module "orders" {
  source  = "terraform-aws-modules/dynamodb-table/aws"
  version = "5.5.2"

  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders-broken-missing-gsi"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  # Deliberate mistake: `global_secondary_indexes` is left unset, so the
  # byCustomer index (customerId hash / createdAt range) is never declared.
  attributes = [
    { name = "orderId", type = "S" },
  ]
}

# Orphan: NOT associated with the orders table -- its table_name names a
# different table entirely, and one that does not exist in this plan.
resource "aws_dynamodb_global_secondary_index" "unrelated" {
  table_name = "totally-unrelated-table"
  index_name = "someOtherIndex"

  key_schema {
    attribute_name = "someKey"
    attribute_type = "S"
    key_type       = "HASH"
  }

  projection {
    projection_type = "ALL"
  }
}
HCL

bash tests/static_tiers.sh
