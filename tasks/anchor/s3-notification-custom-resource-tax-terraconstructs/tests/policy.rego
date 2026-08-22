# Hand-authored (Batch A scenario-authoring task, 2026-08-21) -- NOT a
# generator stub. emit_oracles() never overwrites this file once it exists
# (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   s3-notification-custom-resource-tax (specs/s3-notification-custom-resource-tax.yaml)
# Intent doc: oracles/s3-notification-custom-resource-tax/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.s3_notification_custom_resource_tax.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Two families of rule, mirroring oracles/rego/s3-lambda-log-retention/
# policy.rego's own graph-edge + fail-closed pairing exactly (per this
# spec's own comment: lambda-permission-scoped-to-bucket-{cfn,tf} is
# REUSED VERBATIM from that scenario):
#
#   1. lambda-permission-scoped-to-bucket-tf -- deny if an aws_lambda_permission
#      resource's principal is s3.amazonaws.com but its source_arn
#      expression has no reference to an aws_s3_bucket resource at all.
#      Fail-closed companion: deny if a bucket exists but no such
#      permission exists anywhere.
#   2. notification-targets-created-function-tf (THIS SCENARIO'S OWN new
#      rule, notification-targets-the-wrong-function's tier-1 assert) --
#      deny if an aws_s3_bucket_notification resource's lambda_function
#      block(s) carry no reference to the aws_lambda_function resource this
#      configuration creates. Fail-closed companion: deny if a Lambda
#      function exists but no aws_s3_bucket_notification resource exists
#      anywhere.
#
# `principal` is read from `.planned_values` (always plan-time-known -- a
# literal, never provider-computed), joined by `.address` to the
# `.configuration` resource for the source_arn graph-edge check --
# mirrors s3-lambda-log-retention/policy.rego's own CORRECTION (never read
# `.expressions.principal.constant_value`, which is silently empty for an
# equally-correct `local`/`var`-indirected principal).
#
# Verified against real `terraform show -json` plan output (both hcl_raw
# and terraconstructs) at authoring time: this scenario's own reference
# solution/solve.sh (source_arn references aws_s3_bucket.*.arn AND
# lambda_function[0].lambda_function_arn references
# aws_lambda_function.*.arn -- PASS, deny empty), and the
# notification-targets-the-wrong-function broken fixture
# (lambda_function_arn is a hardcoded literal ARN string, no
# aws_lambda_function reference at all -- FAIL, deny non-empty, while the
# permission-scoping rule stays green since that fixture leaves the
# permission itself untouched -- confirms the two rule families fire
# independently, for the right reason).

package cdktn_bench.s3_notification_custom_resource_tax

import rego.v1

configured_resources := input.configuration.root_module.resources

planned_resources := input.planned_values.root_module.resources

s3_buckets := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket"
]

lambda_functions := [r |
	some r in configured_resources
	r.type == "aws_lambda_function"
]

notifications := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket_notification"
]

# principal is always plan-time-known (a static agent-authored literal,
# never provider-computed), so read it from `.planned_values`, joined by
# `.address` to the `.configuration` resource below for the source_arn
# graph-edge check -- identical pattern to s3-lambda-log-retention/policy.rego.
principal_by_addr := {r.address: r.values.principal |
	some r in planned_resources
	r.type == "aws_lambda_permission"
}

permission_configs := [r |
	some r in configured_resources
	r.type == "aws_lambda_permission"
]

s3_invoke_permissions := [r |
	some r in permission_configs
	principal_by_addr[r.address] == "s3.amazonaws.com"
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

# notification-targets-created-function-tf: `lambda_function` is a nested
# BLOCK LIST on aws_s3_bucket_notification (0+ entries) -- each entry's own
# `.lambda_function_arn` is itself an expression object carrying
# `.references`/`.constant_value`, same shape as any top-level attribute
# expression.
notification_lambda_targets(n) := object.get(n.expressions, "lambda_function", [])

target_references_created_function(n) if {
	some t in notification_lambda_targets(n)
	some ref in object.get(t.lambda_function_arn, "references", [])
	regex.match(`^aws_lambda_function\.`, ref)
}

deny contains msg if {
	some n in notifications
	not target_references_created_function(n)
	msg := sprintf(
		"%s: no lambda_function target references the aws_lambda_function resource this configuration creates -- a hardcoded/unrelated ARN does not satisfy 'notify the claims processor'",
		[n.address],
	)
}

# Fail-closed: a Lambda function exists but no aws_s3_bucket_notification
# resource exists anywhere -- guards the same vacuous-comprehension gap the
# permission-scoping fail-closed rule above guards (a comprehension over an
# empty `notifications` list produces zero denies no matter how badly the
# plan is missing the wiring entirely).
deny contains msg if {
	count(lambda_functions) > 0
	count(notifications) == 0
	msg := "an aws_lambda_function exists, but no aws_s3_bucket_notification resource exists anywhere in the plan to wire uploads to it"
}
