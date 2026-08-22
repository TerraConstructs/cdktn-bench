#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the include-projection-without-non-key-attributes
# catch: sets `projection_type = "INCLUDE"` and omits `non_key_attributes`.
# UNLIKE the typed arms, this does NOT fail the toolchain step -- VERIFIED
# DIRECTLY at authoring time against the pinned hashicorp/aws 6.58.0, fully
# offline: `terraform validate` AND `terraform plan` both succeed, with
# `non_key_attributes` resolving to `[]` in planned_values. Reward must
# still be 0.0, via the `gsi-projects-exactly-status-and-total`
# structural_assert: `set_eq` against `["status","totalAmount"]` fails
# because the resolved set is empty. See
# specs/ddb-gsi-attribute-definitions.yaml's own header comment for the
# full verification transcript.
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
    projection_type = "INCLUDE"
    # non_key_attributes deliberately omitted -- this catch's own mistake
  }
}
HCL

bash tests/static_tiers.sh
