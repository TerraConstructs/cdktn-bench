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
#
# MODULE-AWARE CONFIGURATION WALK. The plan normaliser hoists `planned_values`
# but leaves `configuration` in module bodies (oracles/rego/README.md), so on
# the hcl_modules arm the bucket policy's own configuration lives inside the
# called module and `configuration.root_module.resources` is empty. Read
# through `config_of` alone, this rule denied a CORRECT solution with an empty
# reference list -- MEASURED, reward 0.0 -- because the policy resource the
# s3-bucket module writes references `var.policy` and no role. The fix is the
# one the README prescribes and the three pilot policies carry: union every
# configuration scope, qualify each body's addresses and references with its
# call path so both sides share one address domain, and resolve what a module
# body cannot know -- the value of `var.policy` -- from one scope UP, the
# module CALL's own `policy` argument. Strictness is unchanged: the argument
# read is `policy` and nothing else, so a role reference passed as some other
# input cannot satisfy the graph edge, and on a module-free plan the prefix is
# empty and the whole walk is exactly `configuration.root_module.resources`.

package cdktn_bench.caller_identity_arn_as_principal

import rego.v1

role_arn_re := `^arn:aws:iam::[0-9]{12}:role/`

# A reference qualified with a call path names the same source as the bare one,
# so every pattern below tolerates a leading module path -- and NOTHING else.
# `(^|\.)` would have done it too and was wrong: it also matches
# `data.aws_iam_role.existing.arn`, a role this plan does NOT declare, which is
# exactly the wrong answer `names_a_role` exists to refuse.
call_path := `^(module\.[^.\[]+\.)*`

# The two ways a principal can name a role the plan ties to itself: a role
# this configuration declares, and the issuer role of the deploying session.
role_source_res := concat("", [call_path, `aws_iam_role\.`])

role_source_session := concat("", [call_path, `data\.aws_iam_session_context\..+\.issuer_arn$`])

# `.arn` specifically. The bare `data.aws_caller_identity.<name>` address
# accompanies every attribute reference including the innocuous
# `.account_id`, and terraconstructs' own AwsStack emits a caller-identity
# data source for ARN formatting on every scenario.
session_arn_ref := concat("", [call_path, `data\.aws_caller_identity\..+\.arn$`])

session_arn_value := `(:sts::)|(assumed-role)`

bucket_policies := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_s3_bucket_policy"
]

# A configuration scope is the document root or the value of a
# `module_calls.<name>.module` key; its call path is every name that follows a
# `module_calls` step. `walk` rather than recursion, which Rego forbids.
config_scope_path(path) if count(path) == 0

config_scope_path(path) if path[count(path) - 1] == "module"

module_prefix(path) := concat(".", [sprintf("module.%s", [path[i]]) |
	some i
	path[i - 1] == "module_calls"
])

qualify(prefix, name) := name if prefix == ""

qualify(prefix, name) := concat(".", [prefix, name]) if prefix != ""

config_scopes contains scope if {
	walk(input.configuration.root_module, [path, body])
	is_object(body)
	config_scope_path(path)
	scope := {"prefix": module_prefix(path), "resources": object.get(body, "resources", [])}
}

# Address and references qualified together, every reference kind included:
# enumerating which kinds name a resource is the list that goes stale when a
# new kind appears.
qualified_resource(prefix, r) := object.union(r, {
	"address": qualify(prefix, r.address),
	"expressions": {attr: qualified_expression(prefix, expr) |
		some attr, expr in object.get(r, "expressions", {})
	},
})

qualified_expression(prefix, expr) := out if {
	is_object(expr)
	refs := object.get(expr, "references", null)
	is_array(refs)
	out := object.union(expr, {"references": [qualify(prefix, ref) | some ref in refs]})
}

# A nested BLOCK's expression is a list of blocks, and a constant carries no
# references at all. Both pass through: an undefined expression would make the
# whole enclosing resource undefined and drop it from the configuration
# silently, which is the wrong-answer-no-error failure this join exists to
# avoid. `principals` inside a policy-document data source is read as a block
# below, and the module bodies this oracle grades declare none.
qualified_expression(_, expr) := expr if not is_object(expr)

qualified_expression(_, expr) := expr if {
	is_object(expr)
	not is_array(object.get(expr, "references", null))
}

configured_resources := [r |
	some scope in config_scopes
	some res in scope.resources
	r := qualified_resource(scope.prefix, res)
]

# A planned address carries instance keys a configuration address never does
# (`module.a.aws_s3_bucket_policy.this[0]`), so the two sides join on the
# address with every `[...]` removed.
base_addr(addr) := regex.replace(addr, `\[[^\]]*\]`, "")

config_of(addr) := c if {
	some c in configured_resources
	base_addr(c.address) == base_addr(addr)
}

# A data source Terraform could read DURING the plan is reported in
# `prior_state`, not in `planned_values` -- and a policy document whose every
# argument is a literal is exactly that. MEASURED on the hcl_modules
# reference, whose bucket name is a literal because the module authors the
# bucket and its policy together: `data.aws_iam_policy_document.artifacts`
# was in `prior_state` alone, so reading `planned_values` only left the
# "and nothing broader" rule below silently unevaluated on a solution the
# `not_verifiable` rule also could not see. Both sections are read here, on
# every arm: this can only ADD resolved principals, never remove one.
# `prior_state` is NOT normalised, so its module resources stay nested in
# `child_modules` -- hence the walk -- while their addresses are already
# fully qualified.
prior_resources contains r if {
	walk(object.get(input, ["prior_state", "values", "root_module"], {}), [_, body])
	is_object(body)
	some r in object.get(body, "resources", [])
}

planned_of(addr) := p if {
	some p in input.planned_values.root_module.resources
	base_addr(p.address) == base_addr(addr)
} else := p if {
	some p in prior_resources
	base_addr(p.address) == base_addr(addr)
}

# The call path a hoisted resource was declared under, as one prefix.
resource_prefix(r) := concat(".", object.get(r, "x_module_path", []))

# Every `module` block, with the prefix its body's resources carry and the
# scope its own arguments are written in.
module_call_sites contains site if {
	walk(input.configuration.root_module, [path, body])
	is_object(body)
	path[count(path) - 1] == "module_calls"
	some name, call in body
	parent := module_prefix(array.slice(path, 0, count(path) - 1))
	site := {"parent": parent, "prefix": qualify(parent, sprintf("module.%s", [name])), "call": call}
}

# What the CALL's own `policy` argument references, qualified to the caller's
# scope. A module body names that value `var.policy` and the plan carries no
# link back, so this is the only place a module-authored bucket policy's
# document is visible. Only `policy` is read: any other argument naming a role
# says nothing about who the policy grants to.
call_policy_refs(bp) := {ref |
	some site in module_call_sites
	site.prefix == resource_prefix(bp)
	some raw in object.get(site.call, ["expressions", "policy", "references"], [])
	ref := qualify(site.parent, raw)
}

# Every reference the policy argument itself carries -- for a
# `jsonencode(...)` document this is the only view of the principal there is.
policy_refs(bp) := refs if {
	own := {ref | some ref in object.get(config_of(bp.address), ["expressions", "policy", "references"], [])}
	refs := own | call_policy_refs(bp)
}

# Addresses of the `data "aws_iam_policy_document"` resources the policy is
# built from, if any.
policy_document_addrs(bp) := {addr |
	some ref in policy_refs(bp)
	addr := _document_addr(ref)
}

# The document's own address, keeping whatever call path prefix qualified it,
# so it joins the same address domain everything else here uses.
_document_addr(ref) := addr if {
	found := regex.find_n(`^(?:.*\.)?data\.aws_iam_policy_document\.[^.\[]+`, ref, 1)
	addr := found[0]
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
