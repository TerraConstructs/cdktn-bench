#!/usr/bin/env bash
# THIRD, alternate-shape reference solution -- HAND-AUTHORED, proving the
# STANDALONE-GSI shape-tolerance fix documented in specs/ddb-gsi-attribute-
# definitions.yaml's own "STANDALONE-GSI SHAPE-TOLERANCE FIX" header
# comment and oracles/rego/ddb-gsi-attribute-definitions/policy.rego's own
# header comment (same section name). NOT auto-discovered by
# gates/oracle_falsifiability.py or gates/grading_proof.py -- both walk
# `solution/solve.sh` (the canonical `hash_key`/`range_key`-shaped
# reference) and `solution/broken/*` (required to score 0.0) only; the
# harness has no slot for "a third, equally CORRECT shape", so this
# fixture is a manually-run, additional proof, not part of the automated
# gate chain -- the same convention as `solution/reference-alt-key-schema/`
# (hcl_raw) and `solution/reference-alt-tablev2/` (awscdk).
#
# `aws_dynamodb_global_secondary_index` is `hashicorp/aws`'s STANDALONE
# resource for an "externally managed" GSI -- as opposed to the inline
# `global_secondary_index` block nested inside `aws_dynamodb_table` (the
# shape both solution/solve.sh and solution/reference-alt-key-schema/ use).
# LIVE-CONFIRMED at authoring time via `terraform providers schema -json`
# against the filesystem-mirrored hashicorp/aws 6.58.0 provider: a real,
# GA resource (tfp-aws PR #44999 added it 2026-01-06, PR #47747 removed
# its experimental flag 2026-05-05) with `table_name`/`index_name`
# (required), a `key_schema` block list (`attribute_name`/
# `attribute_type`/`key_type`, all required), and a `projection` block
# (`projection_type` required, `non_key_attributes` optional). Named, by
# link, in the SAME paragraph of `website/docs/r/dynamodb_table.
# html.markdown` line 19 this scenario's own primary evidence citation
# quotes (see the spec's own header comment for the full sentence): "When
# using [`aws_dynamodb_global_secondary_index`](...), you do not need to
# define attributes for externally managed GSIs in the
# `aws_dynamodb_table` resource."
#
# Under `terraform init` + `validate` + `plan` against the filesystem-
# cached hashicorp/aws 6.58.0 provider, this exact shape plans CLEAN with
# zero warnings, "Plan: 2 to add, 0 to change, 0 to destroy".
# `terraform show -json`'s `planned_values` for
# `aws_dynamodb_table.orders` has NO `global_secondary_index` key at all
# (genuinely plan-time-unknown in this shape -- the field is entirely
# externally managed); the GSI's own facts live on the separate
# `aws_dynamodb_global_secondary_index.by_customer` resource instead, at
# `.values.key_schema[*]` and `.values.projection[0]`. Under the real,
# regenerated tests/static_tiers.sh (which, like every hcl_raw run, needs
# live AWS credentials): tier-0's sole remaining hcl_raw assert
# (table-hash-key-is-orderId) passes
# (gsi-projection-is-include/gsi-projects-exactly-status-and-total/
# gsi-hash-key-is-customerId/gsi-range-key-is-createdAt no longer apply to
# hcl_raw as of this fix -- see each assert's own description in the
# spec), and tier-1's policy.rego -- shape-tolerant as of this fix --
# resolves every GSI fact from the standalone resource via `table_gsis()`
# and ALLOWs, scoring reward 1.0.
#
# Note the table's own `attribute` set here contains ONLY orderId --
# customerId/createdAt's `attribute_type` lives inside the standalone
# resource's own `key_schema` blocks instead, never on the table object.
# This is not optional: LIVE-VERIFIED directly that declaring
# customerId/createdAt as `attribute` blocks on the table TOO (even though
# they are real key attributes, just on a sibling resource) still fails
# `terraform plan` with "all attributes must be indexed. Unused
# attributes" -- the table's own attribute-usage validator only ever
# looks at that same resource's own hash_key/range_key/inline-GSI/LSI
# keys, never a sibling resource's externally-managed index.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_dynamodb_table" "orders" {
  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders-alt2"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  # Only orderId is declared here -- this table has no inline GSI, so its
  # own attribute-usage validator only ever looks at its own hash_key
  # (there is no range_key, no inline global_secondary_index, no LSI).
  # customerId/createdAt's types are declared below, on the standalone
  # index resource that owns them.
  attribute {
    name = "orderId"
    type = "S"
  }
}

resource "aws_dynamodb_global_secondary_index" "by_customer" {
  table_name = aws_dynamodb_table.orders.name
  index_name = "byCustomer"

  key_schema {
    attribute_name = "customerId"
    attribute_type = "S"
    key_type       = "HASH"
  }
  key_schema {
    attribute_name = "createdAt"
    attribute_type = "S"
    key_type       = "RANGE"
  }

  projection {
    projection_type    = "INCLUDE"
    non_key_attributes = ["status", "totalAmount"]
  }
}
HCL

bash tests/static_tiers.sh
