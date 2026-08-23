# Hand-authored (Batch A scenario authoring, REPAIR ROUND 4 -- the
# awscdk-tier-1 ENGINE MIGRATION, 2026-08-23) -- NOT a generator stub.
# oracles/emit.py never overwrites this file once it exists
# (specs/SCHEMA.md §8.2 rule 7), so it is safe across regeneration.
#
# Scenario:      ddb-gsi-attribute-definitions
#                (specs/ddb-gsi-attribute-definitions.yaml)
# Intent doc:    oracles/ddb-gsi-attribute-definitions/intent.md
# Graded against the awscdk arm's synthesized CloudFormation template
# (`cdk.out/ScenarioStack.template.json`) -- specs/SCHEMA.md §4.5/§8.
# `input` at policy-evaluation time is that TEMPLATE document, NOT the
# `terraform show -json` plan JSON `../rego/ddb-gsi-attribute-definitions/
# policy.rego` sees. A generated tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego \
#     'data.cdktn_bench.ddb_gsi_attribute_definitions.deny' \
#     < cdk.out/ScenarioStack.template.json
# and fails tier-1 iff that result set is non-empty.
#
# =====================================================================
# WHY THIS FILE EXISTS: the cfn-guard rule it replaces was UNSOUND
# =====================================================================
# This scenario's awscdk tier-1 was graded by
# `oracles/cfn-guard/ddb-gsi-attribute-definitions/policy.guard` until
# this round. That file is now DELETED (specs/ddb-gsi-attribute-
# definitions.yaml sets `oracle.awscdk_tier1_engine: rego`, specs/
# SCHEMA.md §4.5), because the fact this scenario's `oracle.intent`
# actually states is a JOIN and cfn-guard 3.2.0 cannot express a join:
#
#     "No attribute definition, anywhere in the DynamoDB resource graph
#      this table participates in, may name anything other than a key
#      attribute of the table itself or of one of its indexes [...]
#      and every key attribute must have a matching definition somewhere
#      in that graph."
#
# That correlates TWO independent lists inside one resource --
# `Properties.AttributeDefinitions[*].AttributeName` against
# `Properties.KeySchema[*].AttributeName` +
# `Properties.GlobalSecondaryIndexes[*].KeySchema[*].AttributeName` +
# `Properties.LocalSecondaryIndexes[*].KeySchema[*].AttributeName`.
# cfn-guard has no cross-list correlation operator (the same limitation
# ROADMAP.md M8 documents for `AWS::IAM::ManagedPolicy.Roles` -> a role's
# logical id), so the rule degraded to a PROXY: a hard-coded allowlist
# `AttributeName IN ["orderId", "customerId", "createdAt"]`.
#
# That proxy is unsound in the "passes what the intent forbids"
# direction, and this repair round REPRODUCED it end to end, offline,
# on the arm's own pinned toolchain (aws-cdk-lib 2.263.0, aws-cdk
# 2.1135.0, cfn-guard 3.2.0, real `npm run build && npx cdk synth`):
#
#   FIXTURE: the reference solution's own L2 `dynamodb.Table` +
#   `addGlobalSecondaryIndex()`, then ONE CDK escape hatch --
#     (table.node.defaultChild as dynamodb.CfnTable)
#       .addPropertyOverride("AttributeDefinitions",
#         [orderId, customerId])          // `createdAt` dropped
#   `cdk synth` EXITS 0 (only a `CloudFormation-Validate::E3039`
#   WARNING: "GSI KeySchema attribute 'createdAt' is not defined in
#   AttributeDefinitions"), so the artifact is produced and graded.
#   RESULT against the PRE-migration oracle: all five tier-0 asserts
#   PASS (none of them reads AttributeDefinitions at all) AND `cfn-guard
#   validate --rules policy.guard` PASSES (every declared name is still
#   inside the allowlist -- the MISSING one is invisible to an
#   allowlist by construction) -> tier0_pass=1, tier1_status=PASS,
#   REWARD 1.0.
#   The byte-equivalent hcl_raw solution is this spec's own
#   `gsi-key-attribute-not-declared` catch, which `terraform plan`
#   rejects outright ("all indexes must match a defined attribute.
#   Unmatched indexes: [\"createdAt\"]") -> REWARD 0.0. A 1.0-vs-0.0
#   cross-arm split on the same intent violation is exactly what
#   DECISIONS.md Amendment 29 §4 forbids, and it is why this file is a
#   Rego bundle and not a .guard file.
#
# The other direction of the same join was ALSO only ever caught by
# accident: a DANGLING attribute definition (declared, never used as any
# key -- this spec's `attribute-definitions-include-non-key-attributes`
# catch) tripped the old allowlist only because `shippingAddress` et al.
# happen not to be spelled `orderId`/`customerId`/`createdAt`. The
# allowlist had no way to say "this name is not used by any key", which
# is the actual defect (`terraform plan` rejects the TF twin with "all
# attributes must be indexed. Unused attributes: [...]"). Rule 2 below
# now states that fact directly.
#
# =====================================================================
# WHAT THIS FILE GRADES (three rules, each falsified by its own fixture)
# =====================================================================
# All three are quantified PER TABLE RESOURCE, keyed on LOGICAL ID
# (`input.Resources[<LogicalId>]`) -- Amendment 29 §4 R1: identity is
# never a physical name, and this policy never reads `Properties.
# TableName` at all, so a solution that sets an explicit table name and
# one that lets CloudFormation generate it score IDENTICALLY. R2
# (cardinality) holds by construction: `some lid, t in tables` is a
# universal quantification over every DynamoDB table in the template, not
# an existential "at least one table is fine" check -- a template with
# two tables where only one is well-formed DENIES.
#
#   RULE 1 (key-attribute allowlist).  DENY when any attribute used as a
#     key -- the table's own `KeySchema`, or any GSI's/LSI's `KeySchema`
#     -- is not one of orderId/customerId/createdAt. Those are the only
#     three attributes this ticket ever makes a key.
#     FALSIFIED BY: solution/broken/attribute-definitions-include-an-
#     unrequested-key (table given `sortKey: status`; `status` is a real
#     key, so rules 2 and 3 both stay silent -- rule 1 alone fires).
#
#   RULE 2 (declared => used as a key; the join, forward direction).
#     DENY when a declared `AttributeDefinitions` entry names an
#     attribute that no KeySchema of this same table or of any of its
#     indexes uses. This is DynamoDB's own rule, and it is the half an
#     allowlist can only approximate.
#     FALSIFIED BY: solution/broken/attribute-definitions-include-non-
#     key-attributes (shippingAddress/lineItems/paymentReference added as
#     attribute definitions via the CfnTable escape hatch; none of them
#     is a key, so rule 1 stays silent -- rule 2 alone fires).
#
#   RULE 3 (used as a key => declared; the join, reverse direction).
#     DENY when a KeySchema entry names an attribute with no matching
#     `AttributeDefinitions` entry on the same table.
#     FALSIFIED BY: solution/broken/gsi-key-attribute-not-declared (the
#     reproduction quoted above -- `createdAt` dropped from
#     AttributeDefinitions while the GSI still ranges on it; rules 1 and
#     2 both stay silent -- rule 3 alone fires).
#
# Rules 1 and 2 together IMPLY the spec's declared tier-1
# structural_assert `attribute-definitions-are-exactly-the-key-
# attributes` (`AttributeDefinitions[*].AttributeName` set_eq
# [orderId, customerId, createdAt]), and imply it STRICTLY MORE
# STRONGLY than the deleted allowlist did: a declared name must be used
# as a key (rule 2), and every key attribute must be one of the three
# (rule 1), therefore every declared name is one of the three. The
# converse half ("all three really ARE declared") is rule 3 composed
# with this arm's own tier-0 asserts, which independently require a HASH
# key `orderId`, a GSI HASH key `customerId` and a GSI RANGE key
# `createdAt` to resolve -- each of those three keys must then have a
# matching definition or rule 3 fires.
#
# NOT GRADED HERE, deliberately: the GSI's existence, its HASH/RANGE key
# values and its projection. On this arm those four facts are tier-0
# `structural_assert`s (`gsi-hash-key-is-customerId`,
# `gsi-range-key-is-createdAt`, `gsi-projection-is-include`,
# `gsi-projects-exactly-status-and-total`, all `applies_to: [awscdk]`)
# and are executed by tests/static_tiers.sh BEFORE this policy runs;
# both tiers gate the same reward. Restating them here would add four
# rules that no fixture can ever falsify at tier 1 (a fixture violating
# any of them fails tier 0 first, so `observed_tier` is "0" and the
# tier-1 restatement is never the catching rule) -- an unfalsified rule
# is untested, so they stay where their fixtures actually exercise them.
# `../rego/ddb-gsi-attribute-definitions/policy.rego` DOES carry those
# four rules because on the TF-shaped arms the same four facts had to be
# moved OUT of tier 0 (a standalone `aws_dynamodb_global_secondary_index`
# resource puts them at a path one `tf_jsonpath` cannot reach); CFN has
# no standalone-GSI resource type at all, so that pressure does not
# exist here.
#
# SHAPE TOLERANCE: `AWS::DynamoDB::GlobalTable` (what `dynamodb.TableV2`
# synthesizes -- aws-cdk-lib 2.263.0's own aws-dynamodb/README.md calls
# TableV2 "the preferred construct for all use cases") is graded exactly
# like `AWS::DynamoDB::Table`. VERIFIED directly this round against a
# real `cdk synth` of solution/reference-alt-tablev2/solve.sh:
# `AttributeDefinitions`, `KeySchema` and `GlobalSecondaryIndexes[*].
# KeySchema` sit at identical paths with identical shapes; the only
# extra property is `Replicas[*].GlobalSecondaryIndexes[*]`, whose
# entries carry an `IndexName` ONLY (no `KeySchema`, no attribute names
# at all -- confirmed in that same template), so ignoring `Replicas` is
# correct rather than a gap.
#
# NO plan-time-unknown / §4.2.1 CAVEAT APPLIES. A synthesized CFN
# template has no "plan" phase: `AttributeName`/`KeyType` are literal
# strings emitted from typed construct props, never `{"Ref": ...}` or
# `{"Fn::GetAtt": [...]}`. The `object.get(..., "AttributeName", "")`
# defaults below are fail-CLOSED backstops for a malformed entry (an
# empty string matches neither the allowlist nor any declared name, so
# the corresponding rule fires) -- not a tolerance for an unresolved
# value.

package cdktn_bench.ddb_gsi_attribute_definitions

import rego.v1

# The only three attributes this ticket ever makes a key: the table's own
# partition key (orderId) plus the byCustomer index's partition/sort keys
# (customerId/createdAt). Nothing else may be a key, and -- via rule 2 --
# nothing else may be declared either.
required_attributes := {"orderId", "customerId", "createdAt"}

table_types := {"AWS::DynamoDB::Table", "AWS::DynamoDB::GlobalTable"}

# Keyed on LOGICAL ID, never on Properties.TableName (Amendment 29 §4 R1).
tables[lid] := r if {
	some lid, r in input.Resources
	r.Type in table_types
}

properties(t) := object.get(t, "Properties", {})

# Every attribute name this table uses as a KEY, from all three places
# CloudFormation lets a DynamoDB table put one: its own KeySchema, each
# global secondary index's KeySchema, each local secondary index's
# KeySchema. `Replicas[*].GlobalSecondaryIndexes[*]` (GlobalTable only)
# is deliberately excluded -- those entries carry an IndexName and no key
# material at all (see this file's SHAPE TOLERANCE note).
key_attribute_names(t) := names if {
	own := {object.get(ks, "AttributeName", "") |
		some ks in object.get(properties(t), "KeySchema", [])
	}
	gsi := {object.get(ks, "AttributeName", "") |
		some idx in object.get(properties(t), "GlobalSecondaryIndexes", [])
		some ks in object.get(idx, "KeySchema", [])
	}
	lsi := {object.get(ks, "AttributeName", "") |
		some idx in object.get(properties(t), "LocalSecondaryIndexes", [])
		some ks in object.get(idx, "KeySchema", [])
	}
	names := (own | gsi) | lsi
}

declared_attribute_names(t) := names if {
	names := {object.get(ad, "AttributeName", "") |
		some ad in object.get(properties(t), "AttributeDefinitions", [])
	}
}

# RULE 1 -- key-attribute allowlist.
deny contains msg if {
	some lid, t in tables
	some name in key_attribute_names(t)
	not name in required_attributes
	msg := sprintf(
		"DynamoDB table %q (logical id) uses attribute %q as a key (its own KeySchema, or one of its secondary indexes'), which is none of orderId/customerId/createdAt -- those three are the only attributes this table's primary key and its byCustomer index are keyed on, and every attribute definition must be one of them because it must be a key (see the companion 'declared but never used as a key' rule)",
		[lid, name],
	)
}

# RULE 2 -- declared => used as a key (the join, forward direction).
deny contains msg if {
	some lid, t in tables
	some name in declared_attribute_names(t)
	not name in key_attribute_names(t)
	msg := sprintf(
		"DynamoDB table %q (logical id) declares an attribute definition for %q, but no KeySchema on this table or on any of its global/local secondary indexes uses %q as a key -- DynamoDB is schemaless for non-key data, so an attribute definition that is not a key of the table or one of its indexes is invalid, not merely redundant",
		[lid, name, name],
	)
}

# RULE 3 -- used as a key => declared (the join, reverse direction).
deny contains msg if {
	some lid, t in tables
	some name in key_attribute_names(t)
	not name in declared_attribute_names(t)
	msg := sprintf(
		"DynamoDB table %q (logical id) uses attribute %q as a key (its own KeySchema, or one of its secondary indexes'), but declares no AttributeDefinitions entry for %q -- every key attribute must have a matching attribute definition on the same table",
		[lid, name, name],
	)
}

default allow := false

allow if {
	count(deny) == 0
}

# not_verifiable (SCHEMA.md §4.2.1's optional third bullet): deliberately
# NOT defined here, for a stronger reason than the TF-side bundle's. That
# rule exists for plan-time-unknown values, and a synthesized
# CloudFormation template has no plan phase at all -- every value this
# policy reads is a literal string the CDK construct emitted at synth
# time. There is nothing here that could ever be unverifiable.
