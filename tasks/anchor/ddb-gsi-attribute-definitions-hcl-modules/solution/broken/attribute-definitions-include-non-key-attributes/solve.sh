#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the attribute-definitions-include-non-key-attributes
# catch: the module's `attributes` list carries shippingAddress, lineItems
# and paymentReference alongside the three real key attributes -- "declare
# your schema", the plausible-wrong reading of the instruction's item-shape
# sentence, and just as available here as on hcl_raw because the module
# renders `attributes` straight into `dynamic "attribute"` with no
# validation of its own (dynamodb-table@5.5.2 main.tf:34-41).
# Reward 0.0 comes from the toolchain step itself (`plan_command`'s
# `terraform plan`): the provider's "all attributes must be indexed"
# check fires on the module's rendered resource exactly as it does on a
# hand-written one. No structural_assert or policy is ever reached;
# plan.json is never produced.
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
    # Over-declared -- used as a table or index key by nothing below.
    # This catch's own mistake.
    { name = "shippingAddress", type = "S" },
    { name = "lineItems", type = "S" },
    { name = "paymentReference", type = "S" },
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
