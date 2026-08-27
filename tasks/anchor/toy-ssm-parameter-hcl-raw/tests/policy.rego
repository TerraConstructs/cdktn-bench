# Hand-authored (benchmark-integrity review finding F2, fixed 2026-08-06;
# widened 2026-08-06 by the residual-findings fix below) -- NOT a generator
# stub. oracles/emit.py never overwrites this file once it exists
# (specs/SCHEMA.md §8.2 rule 7), so it is safe across regeneration.
#
# Scenario:      toy-ssm-parameter (specs/_toy/toy-ssm-parameter.yaml)
# Intent doc:    oracles/toy-ssm-parameter/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.toy_ssm_parameter.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# --- IAM-shape-coverage fix (residual finding "tier-1 oracle vacuity --
# IAM shape coverage", 2026-08-06) ---------------------------------------
# PROVEN vacuous before this fix: an `aws_iam_policy` (standalone/managed,
# Action="*"/Resource="*") attached to the role via a SEPARATE
# `aws_iam_role_policy_attachment` resource scored tier1_status=PASS,
# because every rule below only ever inspected `aws_iam_role_policy`
# (inline) resources -- `role_policies`/`planned_role_policies` filtered
# `r.type == "aws_iam_role_policy"` ONLY, so the whole `deny` set was empty
# for a plan containing zero `aws_iam_role_policy` resources, no matter how
# wide-open the plan's `aws_iam_policy` resource was. Verified directly:
#   $ opa eval -f raw -I -d policy.rego 'data.cdktn_bench.toy_ssm_parameter.deny' \
#       < <(terraform show -json against a wildcard aws_iam_policy +
#           aws_iam_role_policy_attachment plan)
#   []
# Fixed by widening the collection both deny rules iterate from
# `role_policies`/`planned_role_policies` (aws_iam_role_policy only) to
# `policy_resources`/`planned_policy_resources` (aws_iam_role_policy OR
# aws_iam_policy -- both attribute the IAM policy document JSON directly at
# `.expressions.policy` / `.values.policy`, so every existing rule body
# needs zero further changes to cover the new shape), PLUS a new
# `role_has_no_recognized_policy` deny that fails closed when an
# `aws_iam_role` exists but NO resource of either recognized shape exists
# at all (the comprehension-based deny rules above are vacuously silent on
# an EMPTY `policy_resources` list -- "some rp in [] ..." can never
# generate a violation -- so that gap needed its own rule, not just a wider
# collection). `aws_iam_role_policy_attachment`/
# `aws_iam_role_policy_attachments_exclusive` themselves carry no policy
# content (just a role<->policy-arn edge) and are intentionally NOT
# separately inspected -- the `aws_iam_policy` resource they point at is
# what's checked, which the widened collection already does regardless of
# how (or whether) it's actually attached.
#
# Encodes the two tier-"1" structural_asserts from the spec, now covering
# both recognized policy-resource shapes:
#
#   policy-resource-scoped-not-wildcard-tf (hcl_raw + terraconstructs):
#     graph-edge check -- input.configuration.root_module.resources[] with
#     type in {"aws_iam_role_policy", "aws_iam_policy"} must have an
#     expressions.policy.references entry matching ^aws_ssm_parameter\. --
#     deliberately NOT reading input.planned_values...values.policy for
#     this fact: that string is plan-time-unknown whenever the referenced
#     ARN attribute (e.g. .arn) is itself provider-computed
#     (specs/SCHEMA.md §4.2.1, the G2 fix). Also follows ONE hop through a
#     data.aws_iam_policy_document indirection -- the shape terraconstructs'
#     own L2 Role.addToPolicy() idiom (and equally valid hand-written HCL)
#     produces, per the spec's own rego_hints -- before deciding the check
#     fails. And fails closed (role_has_no_recognized_policy) when zero
#     policy resources of either shape exist at all.
#
#   policy-actions-read-only (all TF arms):
#     genuine value-content check -- when the SAME encoded `policy` string
#     IS plan-time-known (verified via `values.policy` != null, i.e. no
#     provider-computed reference anywhere in it -- e.g. an agent that
#     referenced the parameter's own `.name` instead of its `.arn`), every
#     granted Action must be in the read-only allowlist. When it is
#     unresolved (null) and the graph-edge check above already passed, this
#     fact is NOT independently verifiable from plan JSON alone (spec's own
#     CAVEAT) -- NOT silently treated as "not denied": see the
#     `not_verifiable` fix immediately below.
#
# --- not_verifiable, made non-silent (residual finding "tier-1
# action-allowlist silently skipped on TF arms (plan-time-unknown path)",
# fixed 2026-08-06) --------------------------------------------------------
# PROVEN: an hcl_raw solution with `Resource = aws_ssm_parameter.greeting.arn`
# and `Action = ["ssm:*", "iam:*", "s3:*"]` -- the exact wildcard action set
# the negative fixture above uses, just referencing `.arn` instead of
# `.name` -- leaves `values.policy` plan-time-unknown (SCHEMA.md §4.2.1),
# so the `policy-actions-read-only` deny rule above is silently never
# evaluated for it (its `pv.values.policy != null` guard is false), the
# graph-edge rule passes (the `.arn` reference IS present), tier0 passes,
# and nothing anywhere records that the action allowlist was never actually
# checked. specs/SCHEMA.md §4.2.1 option 3 mandates this case be "logged,
# not silently denied OR silently allowed" -- this policy allowed it (per
# spec: an unverifiable fact must not be guessed as a denial) but was
# SILENT about it, which is the part this fix closes. `not_verifiable`
# below is a second top-level rule set (NOT `deny` -- reward is unaffected,
# matching the spec's "do not silently deny" half) that a generated
# tests/static_tiers.sh (build_static_tiers_sh) now evaluates separately
# and, when non-empty, tees to /logs/verifier/tier1-not-verifiable --
# mirroring the existing tier1-unavailable/aws-unavailable
# non-silent-marker convention. `.configuration...expressions.policy` was
# considered as a plan-time-known source for the Action list (SCHEMA.md
# §4.2.1's "Better" alternative) but verified NOT to carry it: a
# `jsonencode(...)` call collapses to `{"references": [...]}` only, no
# nested Action structure survives into Terraform's own configuration JSON
# representation --
#   $ jq '.configuration.root_module.resources[]
#         | select(.type=="aws_iam_role_policy") | .expressions.policy' plan.json
#   {"references": ["aws_ssm_parameter.greeting.arn", "aws_ssm_parameter.greeting"]}
# -- so this fix implements the mandated non-silent-logging half, which is
# the part achievable from plan JSON alone.
#
# Verified against real `terraform show -json` plan output for both TF
# arms' reference fixtures (generator/tests/fixtures/toy-ssm-parameter/):
# hcl_raw's good/bad main.tf and terraconstructs' L1-construct
# scenario-stack.ts (see generator/check_reference_paths.py's own proof and
# this fix's DECISIONS.md entry for the exact `jq`/`opa eval` transcripts),
# PLUS the two new solution/broken/policy-scoped-to-parameter-alt-shape/
# fixtures (aws_iam_policy + aws_iam_role_policy_attachment) added by the
# IAM-shape-coverage fix above (gates/oracle_falsifiability.py's own run of
# them scores reward 0.0), PLUS a hand-run `.arn`-referencing wildcard-action
# fixture proving `not_verifiable` now fires non-empty where it used to be
# silent.

package cdktn_bench.toy_ssm_parameter

import rego.v1

allowed_actions := {"ssm:GetParameter", "ssm:GetParameters"}

configured_resources := input.configuration.root_module.resources

# Both recognized policy-resource shapes: `aws_iam_role_policy` (inline,
# embeds the role address directly) and `aws_iam_policy` (standalone/
# managed, attached to a role via a separate aws_iam_role_policy_attachment
# / aws_iam_role_policy_attachments_exclusive resource -- see the
# IAM-shape-coverage fix note above). Both carry the policy document JSON
# at the same `.expressions.policy` / `.values.policy` attribute name, so
# every rule below that consumes this collection needs no per-shape branch.
policy_resources := [r |
	some r in configured_resources
	r.type in {"aws_iam_role_policy", "aws_iam_policy"}
]

iam_roles := [r |
	some r in configured_resources
	r.type == "aws_iam_role"
]

# address -> resource, for the one-hop `data "aws_iam_policy_document"`
# indirection (terraconstructs' L2 Role.addToPolicy() idiom).
data_policy_docs[addr] := r if {
	some r in configured_resources
	r.mode == "data"
	r.type == "aws_iam_policy_document"
	addr := sprintf("data.aws_iam_policy_document.%s", [r.name])
}

policy_references(rp) := object.get(rp.expressions.policy, "references", [])

# One hop through a data.aws_iam_policy_document's own `statement` block
# expressions -- each `statement {}` block's `resources`/`resource_arns`
# attribute carries its own `.references`. A single comprehension (always
# exactly one value, possibly empty) rather than two rule heads keyed on
# "was there a match" -- avoids a multi-value conflict if a policy ever
# references more than one data source.
indirect_references(rp) := [r2 |
	some ref in policy_references(rp)
	doc := data_policy_docs[ref]
	some stmt in object.get(doc.expressions, "statement", [])
	some attr in ["resources", "resource_arns"]
	some r2 in object.get(object.get(stmt, attr, {}), "references", [])
]

references_parameter(rp) if {
	some ref in policy_references(rp)
	regex.match(`^aws_ssm_parameter\.`, ref)
}

references_parameter(rp) if {
	some ref in indirect_references(rp)
	regex.match(`^aws_ssm_parameter\.`, ref)
}

deny contains msg if {
	some rp in policy_resources
	not references_parameter(rp)
	msg := sprintf(
		"%s: policy does not reference the created aws_ssm_parameter (no wildcard/hardcoded Resource permitted)",
		[rp.address],
	)
}

# Fail-closed: an aws_iam_role exists but NO policy resource of a
# recognized shape (aws_iam_role_policy inline, or a standalone
# aws_iam_policy -- attached or not) exists anywhere in the plan. The
# `deny` rule above iterates `policy_resources`, which is silently empty
# in this case (a comprehension over an empty list can never produce a
# violation), so an unrecognized/absent policy shape would otherwise pass
# vacuously exactly like the IAM-shape-coverage finding this fix closes.
deny contains msg if {
	count(iam_roles) > 0
	count(policy_resources) == 0
	msg := "an aws_iam_role exists, but no IAM policy resource of a recognized shape (aws_iam_role_policy or aws_iam_policy) exists anywhere in the plan to scope its permissions"
}

# --- policy-actions-read-only ---------------------------------------------
# Only checkable when the encoded policy is plan-time-known. Iterates the
# same widened `policy_resources` shape set (by planned-values address) as
# the graph-edge check above.

planned_policy_resources := [pv |
	some pv in input.planned_values.root_module.resources
	pv.type in {"aws_iam_role_policy", "aws_iam_policy"}
]

as_array(x) := x if is_array(x)

as_array(x) := [x] if not is_array(x)

deny contains msg if {
	some pv in planned_policy_resources
	pv.values.policy != null
	doc := json.unmarshal(pv.values.policy)
	some stmt in doc.Statement
	some action in as_array(stmt.Action)
	not action in allowed_actions
	msg := sprintf("%s: statement grants disallowed action %q", [pv.address, action])
}

# --- not_verifiable ---------------------------------------------------------
# Fires exactly for the case the deny rule above cannot evaluate: the
# policy resource DOES reference the created parameter (graph-edge check
# passed -- this is a legitimately-scoped solution, not the
# policy-resource-scoped-not-wildcard-tf violation), but its encoded
# `policy` value is plan-time-unknown, so the action allowlist inside it
# cannot be independently verified from plan JSON. A separate top-level set
# (not `deny`) -- evaluating this does not change whether the plan is
# denied, only whether the fact "this was never checked" gets recorded.
not_verifiable contains msg if {
	some rp in policy_resources
	references_parameter(rp)
	some pv in planned_policy_resources
	pv.address == rp.address
	# `object.get`, not `pv.values.policy == null`: an attribute whose
	# ENTIRE value is plan-time-unknown is OMITTED from `.values` in real
	# `terraform show -json` output (Rego sees this as the key simply not
	# existing, undefined -- NOT present-with-literal-null), verified
	# directly against a real `.arn`-referencing plan. `pv.values.policy ==
	# null` would silently never match an omitted key either (undefined ==
	# null is itself undefined, not true) -- the same silent-skip class of
	# bug this whole fix exists to close, caught here before it shipped by
	# actually running this rule against a real plan.json (see the fix's
	# proof).
	object.get(pv.values, "policy", null) == null
	msg := sprintf(
		"%s: policy references the created aws_ssm_parameter, but its encoded value is plan-time-unknown (a provider-computed reference, e.g. .arn, is embedded in it) -- the policy-actions-read-only allowlist check cannot be independently verified from plan JSON for this resource; NOT scored as a denial (per specs/SCHEMA.md §4.2.1, an unverifiable fact is never guessed as a violation), logged here for human review instead of being silent",
		[rp.address],
	)
}
