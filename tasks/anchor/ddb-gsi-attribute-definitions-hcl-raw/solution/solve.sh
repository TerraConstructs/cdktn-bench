#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# Verified directly at authoring time (fully offline `terraform init` +
# `validate` + `plan` against hashicorp/aws 6.58.0 -- see
# specs/ddb-gsi-attribute-definitions.yaml's own header comment): this
# exact shape plans clean, and `terraform show -json`'s planned_values
# resolves every structural_assert this scenario declares.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_dynamodb_table" "orders" {
  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  # Only the three attributes actually used as a table or index key are
  # declared here -- shippingAddress/lineItems/paymentReference are real
  # item attributes (see the instruction) but DynamoDB is schemaless for
  # non-key data, and the provider rejects any `attribute` block that
  # isn't used by some key (verified directly: `terraform plan` fails
  # with "all attributes must be indexed. Unused attributes: [...]" the
  # moment an unused one is added).
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
    name               = "byCustomer"
    hash_key           = "customerId"
    range_key          = "createdAt"
    projection_type    = "INCLUDE"
    non_key_attributes = ["status", "totalAmount"]
  }
}
HCL

bash tests/static_tiers.sh
