# Hand-authored -- NOT a generator stub. oracles/emit.py never overwrites
# this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:    caller-identity-arn-as-principal
# Intent doc:  oracles/caller-identity-arn-as-principal/intent.md
# awscdk half: ../../rego-cfn/caller-identity-arn-as-principal/policy.rego
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms.
# The generated tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego \
#     'data.cdktn_bench.caller_identity_arn_as_principal.deny' < plan.json
# and fails tier-1 iff the result set is non-empty.
#
# A GRAPH RULE, NOT A VALUE CHECK: an `aws_s3_bucket_policy`'s `policy`
# attribute is absent from `.planned_values` whenever the document embeds
# the created bucket's provider-computed `.arn`, which every correct answer
# to this ticket does. The principal is therefore read from the reference
# graph, which is always present, plus the resolved
# `statement[*].principals[*].identifiers` of a
# `data "aws_iam_policy_document"` when the policy is built that way.

package cdktn_bench.caller_identity_arn_as_principal

import rego.v1

role_arn_re := `^arn:aws:iam::[0-9]{12}:role/`

# The two ways a principal can name a role the plan ties to itself: a role
# this configuration declares, and the issuer role of the deploying session.
role_source_res := `^aws_iam_role\.`

role_source_session := `^data\.aws_iam_session_context\..+\.issuer_arn$`

# `.arn` specifically. The bare `data.aws_caller_identity.<name>` address
# accompanies every attribute reference including the innocuous
# `.account_id`, and terraconstructs' own AwsStack emits a caller-identity
# data source for ARN formatting on every scenario.
session_arn_ref := `^data\.aws_caller_identity\..+\.arn$`

session_arn_value := `(:sts::)|(assumed-role)`

bucket_policies := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_s3_bucket_policy"
]

config_of(addr) := c if {
	some c in input.configuration.root_module.resources
	c.address == addr
}

planned_of(addr) := p if {
	some p in input.planned_values.root_module.resources
	p.address == addr
}

# Every reference the policy argument itself carries -- for a
# `jsonencode(...)` document this is the only view of the principal there is.
policy_refs(bp) := {ref |
	some ref in object.get(config_of(bp.address), ["expressions", "policy", "references"], [])
}

# Addresses of the `data "aws_iam_policy_document"` resources the policy is
# built from, if any.
policy_document_addrs(bp) := {addr |
	some ref in policy_refs(bp)
	startswith(ref, "data.aws_iam_policy_document.")
	parts := split(ref, ".")
	addr := concat(".", [parts[0], parts[1], parts[2]])
}

# References carried by a policy document's principal identifiers alone --
# strictly more precise than the whole-policy reference set, which also
# carries the bucket ARNs the Resource list names.
document_principal_refs(bp) := {ref |
	some addr in policy_document_addrs(bp)
	some stmt in object.get(config_of(addr), ["expressions", "statement"], [])
	some p in object.get(stmt, "principals", [])
	some ref in object.get(p, ["identifiers", "references"], [])
}

principal_refs(bp) := refs if {
	count(policy_document_addrs(bp)) > 0
	refs := document_principal_refs(bp)
} else := policy_refs(bp)

# Principal strings that are actually resolved at plan time, from ALLOW
# statements only -- a Deny statement naming a broad principal is a
# restriction, not an over-grant. A principal built from a role this
# configuration creates resolves to `null` here and is deliberately absent
# from this set: unknown is not a violation.
resolved_principals(bp) := {id |
	some addr in policy_document_addrs(bp)
	some stmt in object.get(planned_of(addr), ["values", "statement"], [])
	object.get(stmt, "effect", "Allow") == "Allow"
	some p in object.get(stmt, "principals", [])
	some id in object.get(p, "identifiers", [])
	is_string(id)
} | {id |
	doc := json.unmarshal(object.get(bp, ["values", "policy"], "null"))
	some stmt in object.get(doc, "Statement", [])
	object.get(stmt, "Effect", "Allow") == "Allow"
	aws := object.get(stmt, ["Principal", "AWS"], null)
	some id in _as_list(aws)
	is_string(id)
}

_as_list(v) := v if is_array(v)

_as_list(v) := [v] if is_string(v)

_as_list(v) := [] if {
	not is_array(v)
	not is_string(v)
}

names_a_role(bp) if {
	some ref in principal_refs(bp)
	regex.match(role_source_res, ref)
}

names_a_role(bp) if {
	some ref in principal_refs(bp)
	regex.match(role_source_session, ref)
}

# THE POSITIVE REQUIREMENT, STATED FAIL-CLOSED. A resolved string that
# merely LOOKS like a role ARN is deliberately not accepted here: the
# `principal-hardcoded-to-a-foreign-arn` catch is a syntactically valid role
# ARN, so a value-shaped test would pass exactly the fixture it must fail.
deny contains msg if {
	some bp in bucket_policies
	not names_a_role(bp)
	msg := sprintf(
		"%s: the bucket policy's principal names no IAM role this plan contains -- it references neither an aws_iam_role declared here nor the issuer_arn of an aws_iam_session_context, so nothing ties the grant to the pipeline identity (references: %v)",
		[bp.address, sort(principal_refs(bp))],
	)
}

# "and nothing broader": one correct principal must not launder a second,
# wider one alongside it.
deny contains msg if {
	some bp in bucket_policies
	some id in resolved_principals(bp)
	not regex.match(role_arn_re, id)
	msg := sprintf(
		"%s: the bucket policy grants to principal %q, which is not an IAM role ARN -- the ticket allows the pipeline role and nothing broader",
		[bp.address, id],
	)
}

# The deploying SESSION rather than its issuer -- the plausible-wrong
# solution, stated separately because its remedy is different: resolve the
# issuer, do not pick a different identity.
deny contains msg if {
	some bp in bucket_policies
	some id in resolved_principals(bp)
	regex.match(session_arn_value, id)
	msg := sprintf(
		"%s: the bucket policy's principal is the deploying session's own ARN (%q), an ephemeral STS session identity that IAM refuses as a policy principal -- its issuer role is what a policy can name",
		[bp.address, id],
	)
}

deny contains msg if {
	some bp in bucket_policies
	some ref in principal_refs(bp)
	regex.match(session_arn_ref, ref)
	msg := sprintf(
		"%s: the bucket policy's principal is %s, the caller's SESSION arn -- under assume-role credentials that is an arn:aws:sts::...:assumed-role/... identity, which IAM refuses as a policy principal",
		[bp.address, ref],
	)
}

# not_verifiable (SCHEMA.md §4.2.1's third bullet): non-gating, never
# affects reward, teed to /logs/verifier/tier1-not-verifiable by the
# generated tests/static_tiers.sh.
#
# Only "AND NOTHING BROADER" has a gap. That claim is about every
# statement's RESOLVED principal strings, which reach plan JSON only from a
# `data "aws_iam_policy_document"` or from a surviving `values.policy` --
# and `values.policy` does not survive a document embedding the created
# bucket's computed `.arn`. For a `jsonencode(...)` policy both sources are
# empty and a second Allow naming `:root` or `"*"` is invisible:
# `.configuration...expressions.policy` collapses the call to a bare
# `{"references": [...]}` list with no statement structure to walk. The
# awscdk half (static template) and the policy-document shape gate that
# sub-fact; hcl_raw's `jsonencode(...)` logs it here rather than guessing
# either way. The positive requirement above is graph-derived and has no gap.
not_verifiable contains msg if {
	some bp in bucket_policies

	# Only where the graph-edge requirement above is SATISFIED: a genuine
	# violation is already a `deny`, and must not be softened into a note.
	names_a_role(bp)
	count(policy_document_addrs(bp)) == 0
	object.get(bp, ["values", "policy"], null) == null
	msg := sprintf(
		"%s: the principal names a role this plan contains, but 'and nothing broader' could not be checked -- the policy is not built from a data \"aws_iam_policy_document\" and its rendered `policy` string is plan-time-unknown, so no statement's resolved principals are visible in plan JSON",
		[bp.address],
	)
}
