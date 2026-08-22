#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the attribute-definitions-include-non-key-attributes
# catch: declares `attribute` blocks for shippingAddress, lineItems and
# paymentReference in addition to the three real key attributes -- "declare
# your schema", the plausible-wrong reading of the instruction's item-shape
# sentence. Reward must be 0.0 from the toolchain step itself
# (`plan_command`'s `terraform plan`): VERIFIED DIRECTLY at authoring time
# against the pinned hashicorp/aws 6.58.0, fully offline (`terraform
# validate` passes; `terraform plan` fails with "Error: all attributes must
# be indexed. Unused attributes: [\"lineItems\" \"paymentReference\"
# \"shippingAddress\"]"). No structural_assert or policy is ever reached;
# plan.json is never even produced.
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
  # Over-declared -- not used as a table or index key by anything below.
  # This catch's own mistake.
  attribute {
    name = "shippingAddress"
    type = "S"
  }
  attribute {
    name = "lineItems"
    type = "S"
  }
  attribute {
    name = "paymentReference"
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
