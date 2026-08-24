# Hand-authored (Slice D, 2026-08-06) -- NOT a generator stub. emit_oracles()
# never overwrites this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   s3-lambda-log-retention (specs/s3-lambda-log-retention.yaml)
# Intent doc: oracles/s3-lambda-log-retention/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.s3_lambda_log_retention.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Encodes s3-lambda-invoke-permission-scoped's tf_jsonpath spec
# (lambda-permission-scoped-to-bucket-tf, specs/s3-lambda-log-retention.yaml):
# the Lambda permission's source_arn must genuinely REFERENCE the S3 bucket
# this scenario creates -- checked via the plan-time-known graph-edge path
# (`.configuration...expressions.source_arn.references`), never the
# plan-time-unknown value path (`.planned_values...values.source_arn`,
# absent whenever the reference is to another resource's provider-computed
# `.arn` -- specs/SCHEMA.md §4.2.1, re-verified directly against this
# scenario's own hcl_raw and terraconstructs reference fixtures at
# authoring time: `values.source_arn` is entirely absent from a correct,
# `.arn`-referencing plan's `.planned_values`).
#
# Two rules, mirroring oracles/rego/toy-ssm-parameter/policy.rego's own
# graph-edge + fail-closed pair:
#   1. deny if a permission exists whose principal is s3.amazonaws.com but
#      whose source_arn expression has no reference to an aws_s3_bucket
#      resource at all (covers both "hardcoded/wildcard ARN" and "omitted
#      source_arn" -- both leave `.expressions.source_arn.references` empty
#      or entirely absent).
#   2. fail-closed: deny if an aws_s3_bucket resource exists in the plan but
#      NO aws_lambda_permission resource with principal "s3.amazonaws.com"
#      exists anywhere -- guards against rule 1's comprehension being
#      vacuously silent when the permission is omitted entirely rather than
#      merely mis-scoped (rule 1 only ever inspects EXISTING permission
#      resources; an empty collection produces zero violations from a
#      comprehension no matter how badly the plan is missing the resource).
#
# CORRECTION (2026-08-06, benchmark-integrity review finding
# "s3-lambda-log-retention / policy.rego false-positive on a correct TF
# solution"): `s3_invoke_permissions` used to select permissions by
# `r.expressions.principal.constant_value == "s3.amazonaws.com"` --
# `.expressions.<attr>.constant_value` is ONLY populated when the HCL
# author wrote a literal string directly in the resource block. Any
# equally-correct solution that indirects the principal through a `local`,
# a `var`, or a `for_each` value (an entirely ordinary Terraform idiom) has
# `.expressions.principal.references` instead, never `.constant_value` --
# so the old comprehension silently selected NOTHING for such a solution,
# and rule 2's fail-closed check then (wrongly) denied it as if the
# permission didn't exist at all. Verified directly: a plan with
# `values.principal == "s3.amazonaws.com"` in `.planned_values` (always
# plan-time-known -- SCHEMA.md §4.2's default case, principal is never
# provider-computed) but supplied via `local.s3_principal` in HCL produced
# a false deny under the old rule. Fixed by mirroring
# oracles/rego/apigw-openapi/policy.rego's own pattern exactly: read
# `principal` from `.planned_values` (join by `.address` to the
# `.configuration` resource for the source_arn graph-edge check), never
# from `.expressions...constant_value`.
#
# Verified against real `terraform show -json` plan output: this
# scenario's own reference solution/solve.sh (source_arn references
# aws_s3_bucket.*.arn -- PASS, deny empty), the s3-lambda-invoke-permission-
# scoped broken fixture (source_arn omitted entirely -- FAIL, deny
# non-empty), and a hand-built principal-via-local fixture (FAIL under the
# OLD rule, PASS -- correctly -- under this one), plus the
# log-retention-not-a-valid-enum-value broken fixtures (never reach this
# policy at all -- terraform validate itself rejects them before plan.json
# exists, see that catch's own description).

package cdktn_bench.s3_lambda_log_retention

import rego.v1

configured_resources := input.configuration.root_module.resources

planned_resources := input.planned_values.root_module.resources

s3_buckets := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket"
]

# principal is always plan-time-known (a static agent-authored literal,
# never provider-computed -- same rationale as apigw-openapi's own
# `permitted_principals`), so read it from `.planned_values` and join back
# to the `.configuration` resource below for the source_arn graph-edge
# check. See the ROUND 15 note under this comment for why that join is on
# `[type, name]` and not on `.address`.
# ROUND 15 (2026-08-24) -- THE JOIN IS ON `[type, name]`, NOT ON `.address`.
#
# The `.address` join above was latent-broken in exactly the way
# oracles/rego/s3-notification-authoritative-singleton/policy.rego's was,
# and it is fixed here at the same time so the pattern does not survive by
# being copied: a `count`/`for_each` meta-argument on the permission makes
# the PLANNED address `aws_lambda_permission.<name>[0]` while the
# CONFIGURATION address stays `aws_lambda_permission.<name>`. The lookup
# never matches, `s3_invoke_permissions` comes back EMPTY, the source_arn
# scoping rule is silently disabled, and the fail-closed fallback fires with
# a message the plan flatly contradicts. A fully correct solution with
# `count = 1` added scored REWARD 0.0 on the sibling scenario, executed.
#
# A SET of `[type, name]` pairs, not an object keyed by them: a
# `for_each`-expanded permission has N planned instances sharing one key,
# and an object rule binding one key to two different principals raises
# `eval_conflict_error`, which ABORTS evaluation and scores a correct
# solution 0.0 with no deny message at all. A set cannot conflict.
s3_invoke_principal_keys := {[r.type, r.name] |
	some r in planned_resources
	r.type == "aws_lambda_permission"
	object.get(r, ["values", "principal"], null) == "s3.amazonaws.com"
}

permission_configs := [r |
	some r in configured_resources
	r.type == "aws_lambda_permission"
]

s3_invoke_permissions := [r |
	some r in permission_configs
	[r.type, r.name] in s3_invoke_principal_keys
]

source_arn_references(rp) := object.get(rp.expressions.source_arn, "references", [])

references_bucket(rp) if {
	some ref in source_arn_references(rp)
	regex.match(`^aws_s3_bucket\.`, ref)
}

deny contains msg if {
	some rp in s3_invoke_permissions
	not references_bucket(rp)
	msg := sprintf(
		"%s: principal is s3.amazonaws.com but source_arn does not reference the created aws_s3_bucket (no wildcard/hardcoded/omitted SourceArn permitted)",
		[rp.address],
	)
}

# Fail-closed: a bucket exists but no s3.amazonaws.com-principal'd Lambda
# permission exists anywhere in the plan at all.
deny contains msg if {
	count(s3_buckets) > 0
	count(s3_invoke_permissions) == 0
	msg := "an aws_s3_bucket exists, but no aws_lambda_permission resource granting principal s3.amazonaws.com exists anywhere in the plan -- S3 cannot invoke the Lambda function without one"
}
