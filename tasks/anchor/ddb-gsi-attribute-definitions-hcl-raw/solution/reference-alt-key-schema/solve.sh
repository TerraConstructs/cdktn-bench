#!/usr/bin/env bash
# SECOND, alternate-shape reference solution -- HAND-AUTHORED, proving the
# KEY_SCHEMA shape-tolerance fix documented in specs/ddb-gsi-attribute-
# definitions.yaml's own "KEY_SCHEMA SHAPE-TOLERANCE FIX" header comment
# and oracles/rego/ddb-gsi-attribute-definitions/policy.rego's own header
# comment. NOT auto-discovered by gates/oracle_falsifiability.py or
# gates/grading_proof.py -- both walk `solution/solve.sh` (the canonical
# `hash_key`/`range_key`-shaped reference) and `solution/broken/*`
# (required to score 0.0) only; the harness has no third slot for "a
# second, equally CORRECT shape", so this fixture is a manually-run,
# additional proof, not part of the automated gate chain (the same
# convention as the awscdk arm's own
# solution/reference-alt-tablev2/solve.sh).
#
# `key_schema` is `aws_dynamodb_table`'s NON-deprecated way to declare a
# global secondary index's HASH/RANGE key -- LIVE-READ, this session,
# from hashicorp/terraform-provider-aws's `main`,
# website/docs/r/dynamodb_table.html.markdown, line 407: "key_schema -
# (Optional) Configuration block(s) for the key schema... Required if
# `hash_key` is not specified." (line 406/412: `hash_key`/`range_key` are
# each "(Optional, Deprecated) ... Use `key_schema` instead."). REPRODUCED
# directly at authoring time (fully offline `terraform init` + `validate`
# + `plan` against the filesystem-cached hashicorp/aws 6.58.0 provider,
# dummy credentials, no AWS API ever contacted): this exact shape plans
# CLEAN with zero warnings (the canonical hash_key/range_key-shaped
# solve.sh, by contrast, plans with a deprecation warning on both
# arguments -- confirmed directly, this fixture has none). `terraform
# show -json`'s `planned_values` for the GSI is
# `{key_schema:[{customerId,HASH},{createdAt,RANGE}], name,
# non_key_attributes, projection_type:"INCLUDE", range_key:""}` -- no
# `hash_key` key at all (that field is genuinely plan-time-unknown in
# this shape; `planned_values` omits unknown values rather than exposing
# a placeholder). Running the real, regenerated tests/static_tiers.sh
# against it end to end: every tier-0 assert passes (gsi-hash-key-is-
# customerId/gsi-range-key-is-createdAt no longer apply to hcl_raw as of
# this fix -- see the two structural_asserts' own descriptions in the
# spec), and tier-1's policy.rego -- shape-tolerant as of this fix --
# resolves the GSI's HASH/RANGE key from the `key_schema` blocks below
# and ALLOWs. Verified directly by running it: reward 1.0.
set -euo pipefail

cat > main.tf <<'HCL'
resource "aws_dynamodb_table" "orders" {
  name         = "cdktn-bench-ddb-gsi-attribute-definitions-orders-alt"
  billing_mode = "PAY_PER_REQUEST"
  hash_key     = "orderId"

  # Only the three attributes actually used as a table or index key are
  # declared here -- see the canonical solution/solve.sh for the same
  # reasoning (the provider rejects any `attribute` block that isn't used
  # by some key).
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
    name                = "byCustomer"
    projection_type     = "INCLUDE"
    non_key_attributes  = ["status", "totalAmount"]

    # key_schema -- the current, NON-deprecated way to declare a GSI's
    # HASH/RANGE key (see this file's own header comment for the live
    # provider-doc citation). Semantically identical to the canonical
    # solve.sh's `hash_key = "customerId"` / `range_key = "createdAt"`.
    key_schema {
      attribute_name = "customerId"
      key_type       = "HASH"
    }
    key_schema {
      attribute_name = "createdAt"
      key_type       = "RANGE"
    }
  }
}
HCL

bash tests/static_tiers.sh
