# oracles/rego/iam-e2e-role/policy.rego -- HAND-AUTHORED (SCHEMA.md §8.2
# point 7; the generator-stub marker has been removed on purpose -- do not
# re-add it). Graded against `terraform show -json` plan JSON for both
# TF-shaped arms (hcl_raw and terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document.
#
# Scenario:   iam-e2e-role (specs/iam-e2e-role.yaml)
# Intent doc: oracles/iam-e2e-role/intent.md
#
# Encodes the ONE tier-"1" structural_assert this scenario declares
# (s3-resource-not-overbroad, THE wildcard-matches-protected-bucket catch)
# plus the IAM-shape-coverage fail-closed rule the toy spec's own oracle
# established as this repo's standing convention for "an aws_iam_role
# exists but no recognized policy resource shape covers it".
#
# Every other tier-1-shaped fact this scenario cares about (no admin
# wildcards, no invalid action names, no wildcard trust principal, an
# ExternalId condition present) is instead expressed as a tier-"0" check
# in specs/iam-e2e-role.yaml (see that spec's own oracle.structural_asserts
# -- jq's `in`/`not_regex`/`exists` ops cover them directly, so they run in
# the generated tests/static_tiers.sh with no OPA dependency at all). This
# file therefore intentionally has ONE real rule, not several.
package cdktn_bench.iam_e2e_role

import rego.v1

# The pre-provisioned decoy bucket (specs/iam-e2e-role.yaml's Route53-drop
# / fixture-provisioning notes; ops/fixtures/iam-e2e-role/provision.sh
# creates it). NOT part of any plan this policy ever evaluates -- a fixed
# literal, matching oracles/iam-e2e-role/intent.md's own wording. The
# account id is templated with a glob so this rule doesn't need editing
# per-account; account ids are always 12 digits.
decoy_bucket_arn_pattern := "arn:aws:s3:::cdktn-bench-iam-e2e-tfstate-[0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9][0-9]-us-east-1"

# --- recognized IAM policy-document shapes (IAM-shape-coverage) -----------
# Mirrors specs/_toy/toy-ssm-parameter.yaml's own rego_hints lesson: do not
# inspect ONLY the inline aws_iam_role_policy shape. A standalone
# aws_iam_policy attached via aws_iam_role_policy_attachment is an equally
# idiomatic shape and must be checked identically -- both carry the policy
# document JSON at the same attribute name (.values.policy), just on a
# different resource type.
inline_role_policies contains p if {
	some r in input.planned_values.root_module.resources
	r.type == "aws_iam_role_policy"
	p := json.unmarshal(r.values.policy)
}

standalone_policies contains p if {
	some r in input.planned_values.root_module.resources
	r.type == "aws_iam_policy"
	p := json.unmarshal(r.values.policy)
}

all_policy_documents contains p if {
	some p in inline_role_policies
}

all_policy_documents contains p if {
	some p in standalone_policies
}

roles_exist if {
	some r in input.planned_values.root_module.resources
	r.type == "aws_iam_role"
}

# Fail closed: an aws_iam_role exists in this plan but neither recognized
# policy shape appears anywhere for it. A silently-empty
# all_policy_documents set must never read as "nothing to deny" -- an
# agent who authored a role with NO permissions policy at all (or one this
# rule's shape-recognition misses) should not pass the s3-overbroad check
# below by vacuous absence of evidence.
deny contains msg if {
	roles_exist
	count(all_policy_documents) == 0
	msg := "an aws_iam_role exists in this plan but no recognized IAM policy-document shape (aws_iam_role_policy or aws_iam_policy) was found for it -- cannot verify least-privilege"
}

# --- s3-resource-not-overbroad (wildcard-matches-protected-bucket) --------
# For every statement in every recognized policy document whose Action set
# includes at least one S3 action, deny if ANY of its Resource entries
# glob-matches the decoy bucket's ARN. glob.match(pattern, delimiters,
# match) treats its FIRST argument as the glob pattern -- here that is the
# AGENT'S OWN resource string (which may itself contain "*"), tested
# against the fixed decoy ARN literal. This is deliberately the general
# case: ANY overbroad pattern the agent writes that happens to cover the
# decoy bucket is caught, not just the one specific bad string the real
# episode's own over-grant (A11) used.
deny contains msg if {
	some doc in all_policy_documents
	some stmt in doc.Statement
	stmt.Effect == "Allow"
	actions := as_array(stmt.Action)
	some a in actions
	startswith(a, "s3:")
	resources := as_array(stmt.Resource)
	some r in resources
	glob.match(r, [], decoy_bucket_arn_pattern)
	msg := sprintf("S3 action %q has a Resource pattern (%q) that matches the pre-provisioned decoy bucket %q -- this is an over-broad grant, not a legitimate scope", [a, r, decoy_bucket_arn_pattern])
}

as_array(x) := x if {
	is_array(x)
}

as_array(x) := [x] if {
	not is_array(x)
}

default allow := false

allow if {
	count(deny) == 0
}

# not_verifiable: no assert in THIS policy targets a plan-time-unknown
# attribute (unlike specs/_toy/toy-ssm-parameter.yaml's own IAM
# ARN-reference example). NOTE (grantXxx-derivation rework, see
# DECISIONS.md): the workload role's KMS decrypt statement, on the
# awscdk/terraconstructs reference solutions, DOES reference a
# provider/deploy-time-supplied value (a CfnParameter Ref / Terraform
# variable interpolation for the real CMK ARN -- Key.fromKeyArn() can't
# know it offline) -- but this policy's own only rule
# (s3-resource-not-overbroad) never inspects KMS statements at all, so
# that plan-time-unknown value is genuinely irrelevant to anything this
# file evaluates. Left empty deliberately (SCHEMA.md §4.2.1: optional, and
# correct to omit when there is genuinely no such gap FOR THIS POLICY'S
# OWN RULES).
not_verifiable contains msg if {
	false
	msg := ""
}
