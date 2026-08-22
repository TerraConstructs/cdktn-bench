#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-missing-entirely catch: writes only the
# table's own primary key and never adds the byCustomer GSI at all -- no
# inline `global_secondary_index` block, no standalone
# `aws_dynamodb_global_secondary_index` resource. This is a REAL,
# always-plannable shape -- `terraform validate` and `terraform plan` both
# SUCCEED (verified directly at authoring time, hashicorp/aws 6.58.0,
# fully offline: "Plan: 1 to add", no error).
#
# Added in the adversarial-verification repair round that followed the
# STANDALONE-GSI SHAPE-TOLERANCE FIX (see
# specs/ddb-gsi-attribute-definitions.yaml's own header comment, section
# "EXISTENCE + TOTAL-PROJECTION FIX", and
# oracles/rego/ddb-gsi-attribute-definitions/policy.rego's own header
# comment, same section name): removing gsi-hash-key-is-customerId et al.
# from hcl_raw's tier-0 applies_to left nothing rejecting this fixture
# until this round added an explicit existence deny rule to policy.rego.
#
# REPAIR ROUND 3 addition (2026-08-22, "TABLE-ASSOCIATION FIX" in
# policy.rego's own header comment): also carries an ORPHAN standalone
# `aws_dynamodb_global_secondary_index` resource whose `table_name` names
# an UNRELATED table -- not `aws_dynamodb_table.orders`, and no resource
# by that name exists in this plan at all. `terraform plan` still
# succeeds cleanly (a `table_name` string with no corresponding managed
# resource is never validated against anything at plan time, no AWS API
# involved -- LIVE-VERIFIED directly at authoring time, "Plan: 2 to add").
# Before this round's TABLE-ASSOCIATION FIX, `table_gsis` associated ANY
# standalone GSI resource in the whole plan with EVERY table regardless of
# `table_name`, so this orphan alone made the existence deny rule fire
# vacuously-false (i.e. NOT fire) for the orders table, scoring this
# fixture reward 1.0 despite the orders table genuinely having no index of
# its own -- exactly the false-accept this addition exists to prove is
# now closed.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_dynamodb_table" "orders" {
  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders-broken-missing-gsi"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  # Deliberate mistake: the byCustomer index (customerId hash / createdAt
  # range) is never declared at all -- no inline global_secondary_index
  # block, no standalone aws_dynamodb_global_secondary_index resource
  # associated with THIS table.
  attribute {
    name = "orderId"
    type = "S"
  }
}

# Orphan: NOT associated with aws_dynamodb_table.orders -- its table_name
# names a different table entirely (and one that doesn't exist in this
# plan at all). Exercises the TABLE-ASSOCIATION FIX: this resource must
# NOT be able to satisfy the orders table's own GSI-existence requirement.
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
