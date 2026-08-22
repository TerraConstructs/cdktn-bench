#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-key-attribute-not-declared catch: adds the GSI
# on customerId (hash) / createdAt (range) but leaves both out of the
# table's `attribute` set -- the mirror image of
# attribute-definitions-include-non-key-attributes. Reward must be 0.0
# from the toolchain step itself (`plan_command`'s `terraform plan`):
# VERIFIED DIRECTLY at authoring time against the pinned hashicorp/aws
# 6.58.0, fully offline (`terraform validate` passes; `terraform plan`
# fails with "Error: all indexes must match a defined attribute. Unmatched
# indexes: [\"createdAt\" \"customerId\"]" -- byte-identical to this
# scenario's own surviving evidence, tfp-aws#46322). No structural_assert
# or policy is ever reached; plan.json is never even produced.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_dynamodb_table" "orders" {
  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  # customerId / createdAt deliberately NOT declared here, even though
  # they're used as the GSI's key below -- this catch's own mistake.
  attribute {
    name = "orderId"
    type = "S"
  }

  global_secondary_index {
    name               = "byCustomer"
    hash_key           = "customerId"
    range_key          = "createdAt"
    projection_type    = "INCLUDE"
    non_key_attributes = ["status", "totalAmount"]
  }
}
HCL

bash tests/static_tiers.sh
