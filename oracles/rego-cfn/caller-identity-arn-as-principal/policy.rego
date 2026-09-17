# Hand-authored -- NOT a generator stub. oracles/emit.py never overwrites
# this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   caller-identity-arn-as-principal
# Intent doc: oracles/caller-identity-arn-as-principal/intent.md
# TF half:    ../../rego/caller-identity-arn-as-principal/policy.rego
# `input` is the awscdk arm's synthesized CloudFormation template, not the
# plan JSON the TF half sees (specs/SCHEMA.md §4.5); the generated
# tests/static_tiers.sh evaluates this package's `deny` against that
# template and fails tier 1 on a non-empty set.
#
# REGO AND NOT CFN-GUARD (`oracle.awscdk_tier1_engine: rego`): the fact is a
# cross-resource logical-id JOIN -- the principal's `Fn::GetAtt` target must
# be a resource whose Type is `AWS::IAM::Role` -- and cfn-guard 3.2.0 has no
# operator for one, same as ddb-gsi-attribute-definitions.
#
# Two asymmetries against the TF half, both in the spec's ORACLE MUST
# TOLERATE / DEFEND section: CloudFormation has no caller-identity data
# source, so a declared role is this arm's whole answer, and this static
# template makes "and nothing broader" gate on EVERY Allow principal here.

package cdktn_bench.caller_identity_arn_as_principal

import rego.v1

resources := object.get(input, "Resources", {})

bucket_policies[id] := r if {
	some id, r in resources
	r.Type == "AWS::S3::BucketPolicy"
}

# ALLOW statements only: a Deny naming a broad principal is a restriction,
# not an over-grant.
allow_statements(r) := [stmt |
	some stmt in _as_list(object.get(r, ["Properties", "PolicyDocument", "Statement"], []))
	object.get(stmt, "Effect", "Allow") == "Allow"
]

_as_list(v) := v if is_array(v)

_as_list(v) := [v] if is_object(v)

_as_list(v) := [] if {
	not is_array(v)
	not is_object(v)
}

# Every principal entry a statement names, whatever key it arrived under
# (`AWS`, `Service`, `*`) and whether it is a bare value or a list.
principals(stmt) := [p |
	some entry in _principal_values(object.get(stmt, "Principal", null))
	some p in _flatten(entry)
]

_principal_values(v) := [x | some _, x in v] if is_object(v)

_principal_values(v) := [v] if is_string(v)

_principal_values(v) := [] if {
	not is_object(v)
	not is_string(v)
}

_flatten(v) := v if is_array(v)

_flatten(v) := [v] if not is_array(v)

# The join: this principal is `{"Fn::GetAtt": [<id>, "Arn"]}` and <id> names
# a role declared in this same template.
is_declared_role(p) if {
	getatt := object.get(p, "Fn::GetAtt", [])
	getatt[1] == "Arn"
	resources[getatt[0]].Type == "AWS::IAM::Role"
}

deny contains msg if {
	some id, r in bucket_policies
	some stmt in allow_statements(r)
	some p in principals(stmt)
	not is_declared_role(p)
	msg := sprintf(
		"%s: the bucket policy grants to principal %v, which is not an IAM role this template declares -- CloudFormation cannot resolve the deploying identity, so the grant has to name a role the stack itself creates (an Fn::GetAtt on its Arn). An account-root ARN, a wildcard and a hand-typed role ARN all fail here.",
		[id, p],
	)
}

# Fail closed on a policy with no grant at all: an empty or Deny-only
# statement list would otherwise satisfy the rule above vacuously while
# granting the pipeline nothing.
deny contains msg if {
	some id, r in bucket_policies
	count([p |
		some stmt in allow_statements(r)
		some p in principals(stmt)
	]) == 0
	msg := sprintf(
		"%s: the bucket policy names no principal in any Allow statement -- the pipeline role is granted nothing",
		[id],
	)
}
