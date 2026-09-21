# awscdk tier-1 for toy-ssm-parameter. `input` is the synthesized
# CloudFormation template, not the plan JSON the TF half
# (../../rego/toy-ssm-parameter/policy.rego) sees. Intent:
# oracles/toy-ssm-parameter/intent.md.
#
# Three IAM policy shapes carry a document here and all three are graded the
# same way: AWS::IAM::Policy, AWS::IAM::ManagedPolicy, and an inline entry in
# AWS::IAM::Role.Properties.Policies. A per-shape rule is silent on a template
# that uses none of them, so a fail-closed rule stands between "no recognized
# policy shape" and a vacuous pass.
#
# Strictness vs the TF half: weaker on one edge. The TF half requires the
# policy to REFERENCE the created parameter; this file only refuses a wildcard
# Resource, because that is what the retired cfn-guard bundle graded and this
# scenario is the schema's worked example rather than a corpus scenario. The
# gap is the same logical-id join the corpus bundles now make, and closing it
# here needs new fixtures on both arms.

package cdktn_bench.toy_ssm_parameter

import rego.v1

allowed_actions := {"ssm:GetParameter", "ssm:GetParameters"}

resources := object.get(input, "Resources", {})

as_list(v) := v if is_array(v)

as_list(v) := [v] if not is_array(v)

role_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::IAM::Role"
}

# [owner logical id, policy document] for every recognized shape, so one pair
# of rules grades all three and no shape can be added without being graded.
policy_documents := standalone | inline

standalone := {[lid, doc] |
	some lid, r in resources
	r.Type in {"AWS::IAM::Policy", "AWS::IAM::ManagedPolicy"}
	doc := object.get(r, ["Properties", "PolicyDocument"], null)
	is_object(doc)
}

inline := {[lid, doc] |
	some lid, r in resources
	r.Type == "AWS::IAM::Role"
	some entry in object.get(r, ["Properties", "Policies"], [])
	doc := object.get(entry, "PolicyDocument", null)
	is_object(doc)
}

statements(doc) := as_list(object.get(doc, "Statement", []))

# Fail-closed: a role exists and no recognized policy shape does, so every
# rule below is vacuously satisfied.
deny contains msg if {
	count(role_ids) > 0
	count(policy_documents) == 0
	msg := "an AWS::IAM::Role exists, but no AWS::IAM::Policy, AWS::IAM::ManagedPolicy or inline Role Policies entry exists anywhere in the template to scope its permissions"
}

deny contains msg if {
	some entry in policy_documents
	some stmt in statements(entry[1])
	some resource in as_list(object.get(stmt, "Resource", []))
	resource == "*"
	msg := sprintf(
		"%s: an IAM policy statement grants Resource \"*\" -- the role must be scoped to the parameter it reads, not to every resource in the account",
		[entry[0]],
	)
}

deny contains msg if {
	some entry in policy_documents
	some stmt in statements(entry[1])
	some action in as_list(object.get(stmt, "Action", []))
	not action in allowed_actions
	msg := sprintf(
		"%s: an IAM policy statement grants disallowed action %v -- only %v are read-only parameter reads",
		[entry[0], action, sort([a | some a in allowed_actions])],
	)
}
