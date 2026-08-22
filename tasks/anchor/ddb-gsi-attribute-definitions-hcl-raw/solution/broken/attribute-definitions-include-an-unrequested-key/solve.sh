#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the attribute-definitions-include-an-unrequested-key
# catch: gives the table its own `range_key = "status"`, in addition to
# the requested byCustomer GSI. This is a REAL, always-plannable key
# shape -- `terraform validate` and `terraform plan` both SUCCEED
# (verified directly at authoring time, hashicorp/aws 6.58.0, fully
# offline: no "Unused attributes" / "Unmatched indexes" error, `status`
# simply lands in `values.attribute` as a fourth entry). Every OTHER
# structural_assert in this scenario still passes -- only
# `attribute-definitions-are-exactly-the-key-attributes` (tier 1,
# oracles/rego/ddb-gsi-attribute-definitions/policy.rego) catches this:
# the resolved attribute set is {orderId, status, customerId, createdAt},
# and `status` is not IN the allowlist.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_dynamodb_table" "orders" {
  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"
  # Deliberate mistake: the table is given its own range key on `status`
  # -- a real key, not a dangling attribute -- that no ticket text asked
  # for ("each order is identified by orderId" names the table's own key
  # as orderId alone).
  range_key    = "status"

  attribute {
    name = "orderId"
    type = "S"
  }
  attribute {
    name = "status"
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
    name               = "byCustomer"
    hash_key           = "customerId"
    range_key          = "createdAt"
    projection_type    = "INCLUDE"
    non_key_attributes = ["status", "totalAmount"]
  }
}
HCL

bash tests/static_tiers.sh
