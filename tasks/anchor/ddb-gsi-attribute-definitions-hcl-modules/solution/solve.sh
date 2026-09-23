#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT main.tf and runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite this
# file (destructive-safe rule).
#
# MODULE CHOICE (docs/design/hcl-modules-spec-matrix.md §1): the single
# `aws_dynamodb_table` this scenario grades is authored by
# `terraform-aws-modules/dynamodb-table/aws` 5.5.2. Nothing here is raw:
# every resource the scenario grades has a module that authors it.
#
# The module takes the attribute-definition set and the index key schemas as
# two SEPARATE inputs -- `attributes` (list(map(string))) and
# `global_secondary_indexes` (type `any`) -- and validates neither, so
# keeping them consistent is the solution's own job here exactly as it is on
# hcl_raw. Only the three attributes used as a table or index key are
# declared: DynamoDB is schemaless for non-key data, and the provider
# rejects an `attribute` block no key uses.
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
