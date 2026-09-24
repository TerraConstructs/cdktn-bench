# oracles/rego/s3-acl-vs-object-ownership-log-delivery/policy.rego --
# HAND-AUTHORED (SCHEMA.md §8.2 rule 7). Encodes
# specs/s3-acl-vs-object-ownership-log-delivery.yaml's one tier-"1"
# structural_assert (no-ownership-control-leaves-acls-enabled) +
# oracle.rego_hints. Graded against `terraform show -json` plan JSON for all
# three TF-shaped arms (hcl_raw, terraconstructs, hcl_modules). `input` at
# policy-evaluation time is that plan JSON document.
#
# Intent doc: oracles/s3-acl-vs-object-ownership-log-delivery/intent.md
#
# THE CLAIM: no ownership control declared anywhere in this workspace may leave
# S3 access control lists ENABLED. The two settings that leave them enabled are
# `ObjectWriter` (the seed's own value) and `BucketOwnerPreferred` -- the latter
# is the half-measure this scenario's `acls-left-enabled-on-the-destination-
# bucket` catch is about, because it sounds like it satisfies "the bucket owner
# owns everything written to it" and does not: it only changes ownership of
# objects uploaded with the `bucket-owner-full-control` canned ACL, and ACLs
# stay on. `BucketOwnerEnforced` is the only compliant value.
#
# WHY THIS IS TIER 1 AND NOT TIER 0. The claim is universally quantified over a
# collection -- "NO ownership control, ANYWHERE" -- and a jq path can pin one
# value, not the absence of a shape across all of them. This scenario declares
# no tier-0 twin of it, deliberately: a tier-1 assert whose only negative
# fixture trips a tier-0 assert first is a tier-1 assert nothing falsifies, and
# `make tier1-coverage` refused the pair.
#
# `planned_values` is read for the ownership controls and every CONFIGURATION
# SCOPE for the bucket policy. The plan normaliser hoists module-authored
# resources into `planned_values.root_module.resources`; it does not touch
# `configuration`, so the second half walks the module bodies itself.
#
# WHY IT FAILS CLOSED ON SHAPE DRIFT (rego_hints, second entry). An
# `aws_s3_bucket_ownership_controls` resource whose `rule` list is missing or
# empty in the plan is DENIED rather than skipped: a rule that only ever looked
# inside `rule[*]` would report "compliant" for a resource that declares no
# ownership at all, which is precisely the vacuous-satisfaction shape this
# repo's oracles are audited for. Note this rule deliberately does NOT deny the
# ABSENCE of the resource type altogether: a workspace that stops managing
# ownership controls has not changed the deployed bucket, which is a fact about
# the ACCOUNT, and `tests/live_check.py` reads the deployed setting directly.
# Denying it here would also make the awscdk twin, which cannot see a Terraform
# resource type at all, asymmetrically weaker.
#
# THE SECOND TIER-1 ASSERT
# (`destination-bucket-policy-carries-the-log-delivery-grant`) IS CONDITIONAL,
# and the conditionality is the whole reason it is here rather than in a jq
# path. Two halves:
#
#   (a) UNCONDITIONAL: a bucket policy must be PLANNED -- read from
#       planned_values, not from configuration, because a module body declares
#       its policy resource whatever its `count` resolves to. With ACLs disabled
#       it is the only thing that can authorize log delivery, so a solution with
#       none has silently switched delivery off.
#   (b) CONDITIONAL: if the policy DOCUMENT is readable from the graded
#       artifact, it must name `logging.s3.amazonaws.com`. Whether it is
#       readable depends on the arm AND on the shape the agent chose, all three
#       measured 2026-08-26 by planning a correct and an incorrect grant and
#       diffing the artifacts:
#         * `policy = jsonencode({...})` interpolating the bucket ARN (hcl_raw's
#           idiom) -> `.configuration` keeps only `{"references": [...]}`.
#           NOTHING readable. This rule stays SILENT, and
#           `tests/live_check.py` -- which reads the ACCOUNT, not the artifact
#           -- is the tier that answers. Denying here would score a CORRECT
#           hcl_raw solution 0.0.
#         * cdktn's `cdk.tf.json` (terraconstructs) -> Terraform's JSON syntax
#           records the whole document as `expressions.policy.constant_value`,
#           `${...}` markers and all. FULLY readable, principal included.
#         * `data "aws_iam_policy_document"` (terraconstructs' own
#           `addToResourcePolicy`, and a legitimate hcl_raw idiom too) -> the
#           literals live one hop away, in the data source's own
#           `.configuration` node. Readable, via the hop below -- the same
#           one-hop-indirection pattern
#           `oracles/rego/s3-notification-authoritative-singleton/policy.rego`
#           documents for a bucket policy.
#
# What (b) deliberately does NOT do is evaluate the grant: no action check, no
# resource-ARN coverage check, no condition-key evaluation, no Deny handling.
# Those need a request context, and the artifact has none. `tests/live_check.py`
# does all of it against real deployed state and is GATING; this rule is the
# cheap, static half that catches the crude version of the same mistake before
# a live check is even reached. Written as "the document must MENTION the
# principal" precisely so it can never deny a correct solution over a shape it
# failed to anticipate.

package cdktn_bench.s3_acl_vs_object_ownership_log_delivery

import rego.v1

default allow := false

allow if {
	count(deny) == 0
}

ownership_controls := [r |
	some r in object.get(object.get(input, "planned_values", {}), "root_module", {}).resources
	r.type == "aws_s3_bucket_ownership_controls"
]

acls_enabled_settings := {"ObjectWriter", "BucketOwnerPreferred"}

# A rule that leaves ACLs enabled.
deny contains msg if {
	some r in ownership_controls
	some rule in object.get(object.get(r, "values", {}), "rule", [])
	setting := object.get(rule, "object_ownership", "")
	setting in acls_enabled_settings
	msg := sprintf(
		"%s sets object_ownership = %q, which leaves S3 access control lists ENABLED on that bucket; the only setting that disables them is BucketOwnerEnforced",
		[object.get(r, "address", "aws_s3_bucket_ownership_controls.?"), setting],
	)
}

# Shape drift: an ownership-controls resource that declares no rule at all, or
# a rule with no readable object_ownership. Denied rather than skipped -- see
# this file's header.
deny contains msg if {
	some r in ownership_controls
	count(object.get(object.get(r, "values", {}), "rule", [])) == 0
	msg := sprintf(
		"%s declares no ownership rule at all, so it cannot be shown to disable access control lists",
		[object.get(r, "address", "aws_s3_bucket_ownership_controls.?")],
	)
}

deny contains msg if {
	some r in ownership_controls
	some rule in object.get(object.get(r, "values", {}), "rule", [])
	object.get(rule, "object_ownership", null) == null
	msg := sprintf(
		"%s has an ownership rule whose object_ownership is absent or plan-time-unknown, so it cannot be shown to disable access control lists",
		[object.get(r, "address", "aws_s3_bucket_ownership_controls.?")],
	)
}

# --------------------------------------------------------------------------
# not_verifiable (SCHEMA.md §4.2.1): informational, never denies, never affects
# reward. Empty DELIBERATELY, and the reason is worth stating because this
# scenario does have a plan-time-unknown surface -- the bucket policy document
# -- and this is the one place a marker for it would go. It is not written here
# because the unreadable case is not a GAP in this policy: it is the exact
# condition under which `verifier.live_check` (enabled, hand-authored, GATING)
# owns the fact instead, against real deployed state rather than against the
# artifact. A `not_verifiable` marker is for a fact NOTHING can check; this one
# is checked, just not here.
# --------------------------------------------------------------------------
not_verifiable contains msg if {
	false
	msg := ""
}

# --------------------------------------------------------------------------
# destination-bucket-policy-carries-the-log-delivery-grant
# --------------------------------------------------------------------------

logging_service_principal := "logging.s3.amazonaws.com"

# A CONFIGURATION SCOPE is the document root or the value of a
# `module_calls.<name>.module` key, carried with the call path its resources'
# addresses need. `configuration` is NOT hoisted by the plan normaliser, so on
# the hcl_modules arm the bucket policy the s3-bucket module authors is
# invisible from `configuration.root_module.resources` and rule (a) below would
# report "no bucket policy is declared" for a CORRECT solution. Reading every
# scope fixes that at equal strictness on every arm: a module-free plan has one
# scope with an empty prefix, which is the root resource list this rule used to
# read and nothing else. `walk` rather than recursion, which Rego forbids
# (oracles/rego/README.md).
config_scope_path(path) if count(path) == 0

config_scope_path(path) if path[count(path) - 1] == "module"

module_prefix(path) := concat(".", [sprintf("module.%s", [path[i]]) |
	some i
	path[i - 1] == "module_calls"
])

qualify(prefix, name) := name if prefix == ""

qualify(prefix, name) := concat(".", [prefix, name]) if prefix != ""

config_scopes contains scope if {
	walk(object.get(object.get(input, "configuration", {}), "root_module", {}), [path, body])
	is_object(body)
	config_scope_path(path)
	scope := {"prefix": module_prefix(path), "resources": object.get(body, "resources", [])}
}

# The configuration side, keyed by the address a PLANNED resource carries: the
# scope's call path prefixed on, and the instance key a configuration address
# never has removed from the planned one.
configured_bucket_policies[addr] := entry if {
	some scope in config_scopes
	some r in scope.resources
	r.type == "aws_s3_bucket_policy"
	addr := qualify(scope.prefix, object.get(r, "address", "aws_s3_bucket_policy.?"))
	entry := {"resource": r, "scope": scope}
}

base_addr(addr) := regex.replace(addr, `\[[^\]]*\]`, "")

# WHICH SIDE OF THE PLAN ANSWERS "IS THERE A BUCKET POLICY": planned_values, not
# configuration. A module body DECLARES `aws_s3_bucket_policy.this` with a
# `count` that is zero unless one of its `attach_*` inputs is set, and the
# configuration representation lists a resource whatever its count resolves to
# -- so reading the configuration reports a policy for a workspace that plans
# none, which is this scenario's `log-delivery-grant-missing-entirely` scoring
# 1.0. planned_values carries the resource only if it is really being created,
# and the plan normaliser has already hoisted module-authored resources into
# `root_module.resources`. No arm loses strictness: a resource written without a
# `count` appears on both sides, so hcl_raw and terraconstructs are unchanged.
planned_resources := object.get(
	object.get(object.get(input, "planned_values", {}), "root_module", {}),
	"resources",
	[],
)

# An unjoinable configuration node yields the empty scope rather than dropping
# the planned policy: losing it would take rule (a) with it.
config_entry(addr) := e if {
	e := configured_bucket_policies[base_addr(addr)]
} else := {"resource": {}, "scope": {"prefix": "", "resources": []}}

bucket_policies contains bp if {
	some p in planned_resources
	p.type == "aws_s3_bucket_policy"
	addr := object.get(p, "address", "aws_s3_bucket_policy.?")
	entry := config_entry(addr)
	bp := {"address": addr, "resource": entry.resource, "scope": entry.scope}
}

# (a) There must be one at all.
deny contains msg if {
	count(bucket_policies) == 0
	msg := sprintf(
		"this configuration plans no aws_s3_bucket_policy. With access control lists disabled on the log destination bucket, a bucket policy granting %q is the only thing that can authorize server access log delivery",
		[logging_service_principal],
	)
}

policy_expression(bp) := object.get(object.get(bp.resource, "expressions", {}), "policy", {})

# The document as a literal string, which is what Terraform's JSON syntax
# (cdktn's cdk.tf.json) produces.
policy_constant(bp) := v if {
	v := object.get(policy_expression(bp), "constant_value", null)
	is_string(v)
}

# One hop: `policy = data.aws_iam_policy_document.X.json`. The referenced data
# source's own configuration node keeps its statement literals.
referenced_policy_documents(bp) := [d |
	some ref in object.get(policy_expression(bp), "references", [])
	startswith(ref, "data.aws_iam_policy_document.")
	some d in bp.scope.resources
	d.type == "aws_iam_policy_document"
	startswith(ref, sprintf("data.aws_iam_policy_document.%s", [object.get(d, "name", "")]))
]

# Every string anywhere inside a node -- shape-agnostic on purpose, because the
# exact nesting of `statement[].principals[].identifiers[].constant_value`
# differs between provider versions and between the L2s that emit it, and this
# rule's job is "does the document mention this principal", not "is it nested
# where I expect".
mentions_logging_principal(node) if {
	walk(node, [_, value])
	is_string(value)
	contains(value, logging_service_principal)
}

readable_document(bp) := doc if {
	doc := policy_constant(bp)
} else := doc if {
	docs := referenced_policy_documents(bp)
	count(docs) > 0
	doc := docs
}

# (b) If it is readable, it must name the logging service principal. A module
# that hands its own policy resource a module-local value (s3-bucket 5.16.1's
# `policy = local.policy`) carries nothing readable in any plan document, so
# this rule stays silent there and `tests/live_check.py` grades the grant.
deny contains msg if {
	some bp in bucket_policies
	doc := readable_document(bp)
	not mentions_logging_principal(doc)
	msg := sprintf(
		"%s declares a bucket policy whose document IS readable from the graded artifact and never mentions %q -- with access control lists disabled, nothing in it can authorize S3 server access log delivery",
		[bp.address, logging_service_principal],
	)
}
