# Hand-authored (Batch A scenario authoring, 2026-08-21; REVISED same day
# after an adversarial verifier review -- see below) -- NOT a generator
# stub. oracles/emit.py never overwrites this file once it exists
# (specs/SCHEMA.md §8.2 rule 7), so it is safe across regeneration.
#
# Scenario:      lambda-log-group-ownership-and-retention
#                (specs/lambda-log-group-ownership-and-retention.yaml)
# Intent doc:    oracles/lambda-log-group-ownership-and-retention/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego \
#     'data.cdktn_bench.lambda_log_group_ownership_and_retention.deny' \
#     < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# VERIFIER-REJECTED FIX (2026-08-21, same day as initial authoring). The
# original version of this file required "log group name EXACTLY equals
# `/aws/lambda/<function-name>`" as the ONLY way a declared log group could
# govern a function's logs, and its own header comment claimed "AWS
# Lambda's log destination is determined ENTIRELY by [that] naming
# convention, with no CloudFormation/Terraform-level wiring between the two
# resources at all" -- FALSE. AWS Lambda's advanced logging controls (GA'd
# 2023-11-16) let a function write to a log group of ANY name via
# `logging_config.log_group`, a first-class, Optional, plan-time-known
# string argument on `aws_lambda_function` (verified directly against the
# pinned `hashicorp/aws` 6.58.0 provider schema and a real offline
# `terraform plan`: unset entirely when no `logging_config` block is
# authored -- `.values.logging_config` is simply ABSENT from the plan JSON,
# never `null`/`[]` -- and, when set, `.values.logging_config[0].log_group`
# resolves to the exact string passed, e.g. a reference to another
# resource's own `.name`, itself plan-time-known here per this scenario's
# spec header comment deviation 2). This exact mechanism is what
# `@cdktn/provider-aws` 24.8.0's `logGroup?: string` binding
# (lib/lambda-function/index.d.ts:470, inside `LambdaFunctionLoggingConfig`)
# mirrors 1:1 for the terraconstructs arm, and what `aws-cdk-lib`
# 2.263.0's own `lambda.Function.logGroup` prop compiles to on the awscdk
# arm (`Properties.LoggingConfig.LogGroup` -- see
# oracles/cfn-guard/lambda-log-group-ownership-and-retention/policy.guard's
# own header for that arm's half of this same fix). A hand-built fixture
# using ONLY this wiring mechanism (arbitrary log group name, explicit
# `logging_config.log_group` reference, no `/aws/lambda/...` name anywhere)
# is a genuinely correct solution to this scenario's ticket and used to
# score reward 0.0 here -- the exact "alternative shape scored wrong"
# failure mode this benchmark's batch-A authoring guide (docs/adding-
# scenarios.md §1 item 3a) exists to avoid. Fixed below: `deny` now fires
# only when NEITHER the naming-convention path NOR the explicit-wiring path
# holds. See specs/lambda-log-group-ownership-and-retention.yaml's own
# header comment ("VERIFIER-REJECTED FIX") for the full evidence trail,
# including the corrected aws-cdk#35003 citation (that issue argues AGAINST
# treating the naming convention as exclusive, not for it).
#
# Encodes catch 4 (`log-group-name-diverges-from-function`, graph-dependency)
# and its own tier-1 structural_assert spec
# (`log-group-governs-the-function-tf`, specs/lambda-log-group-
# ownership-and-retention.yaml): a log group that matches the
# `/aws/lambda/...` NAMING PATTERN is not necessarily the group AWS Lambda
# actually writes to (naming must be EXACT, not merely pattern-matching --
# still true and still checked below), AND a log group is not disqualified
# merely for having some OTHER name, as long as the function is explicitly
# wired to it. A log group named `/aws/lambda/processor` while the function
# is actually named `event-processor`, with NOTHING wiring the two
# together, satisfies neither disjunct and is exactly this scenario's own
# catch-4 broken fixture (solution/broken/log-group-name-diverges-from-
# function/ on hcl_raw and terraconstructs) -- passes every tier-0 check in
# this scenario (it exists, it matches the naming PATTERN, retention is 30,
# it isn't retained on delete) while governing nothing.
#
# Both `aws_cloudwatch_log_group.name`, `aws_lambda_function.function_name`,
# and (when present) `aws_lambda_function.logging_config[].log_group` are
# plan-time-known on every enabled arm and every fixture this scenario's
# catches produce -- verified directly at this spec's own authoring time
# (specs/lambda-log-group-ownership-and-retention.yaml's own header comment,
# deviation 2, plus the VERIFIER-REJECTED FIX section above for the wiring
# argument specifically): `function_name` is Required in the pinned
# `hashicorp/aws` provider's own schema (`terraform providers schema
# -json`), so it is never Optional+computed the way an auto-generated
# resource name would be, and `logging_config.log_group` is a plain,
# Optional, never-computed string argument. This is a GENUINE
# string-equality check on both disjuncts, not a graph-edge-only "does it
# reference the right resource" check the way s3-lambda-log-retention's
# SourceArn-scoping rule is (that scenario's own value is plan-time-UNKNOWN
# and can only be checked via `.configuration...expressions.*.references`;
# this scenario's values are plan-time-KNOWN, so comparing the actual
# resolved strings directly is both possible and the honest, stricter
# check).
#
# cfn-guard counterpart for this catch now EXISTS for real (2026-08-21 fix
# -- awscdk's own oracles/cfn-guard/lambda-log-group-ownership-and-
# retention/policy.guard is HAND-AUTHORED, no longer the generator-
# scaffolded placeholder it started as), implementing the SAME
# two-disjunct OR, with one narrower residual gap:
# cfn-guard 3.2.0's rule DSL has no string-concatenation operator, so its
# naming-path disjunct can only check the `^/aws/lambda/` PREFIX, not the
# exact function-name SUFFIX -- see that file's own header comment and
# specs/lambda-log-group-ownership-and-retention.yaml's "RESIDUAL, NARROWER
# TOOL-CAPABILITY GAP" note for the full accounting of what that means for
# catch 4's own awscdk-arm broken fixture (it uses a wholly unrelated name,
# not merely a wrong suffix, to land inside what cfn-guard can actually
# prove).
#
# NO `not_verifiable` RULE, DELIBERATELY (generator/gen.py prints a generic,
# heuristic WARNING at `make gen` time for any tier-1 assert whose
# `tf_jsonpath` touches a `values.<attr>`-shaped path, since THAT SHAPE can
# go plan-time-unknown for OTHER scenarios -- e.g. s3-lambda-log-retention's
# own SourceArn/policy checks). That heuristic does not know what this
# scenario's own header comment proves directly: `aws_lambda_function.
# function_name` is Required in the pinned provider's own schema (never
# Optional+computed), and `logging_config.log_group` is a plain Optional
# string, so every fact `deny` below reads is ALWAYS computable when the
# relevant resource exists -- there is no plan-time-unknown path here to
# document. Adding an always-empty `not_verifiable` rule just to silence
# the heuristic would misrepresent a genuine, verified non-gap as an open
# one; SCHEMA.md §4.2.1 makes the rule OPTIONAL for exactly this reason
# ("a policy.rego that never defines it is treated as declaring no such
# gap").
#
# Verified against real `terraform show -json` plan output, both TF arms:
# this scenario's own solution/solve.sh (exact-name-match path -- PASS, no
# deny), solution/broken/log-group-name-diverges-from-function/solve.sh
# (name built without the function's own function_name, no wiring -- FAIL,
# `deny` fires, and this is the ONLY tier this fixture fails at, per
# gates/oracle_falsifiability.py's own observed_tier check -- see that
# gate's run log for this scenario), and (2026-08-21 fix verification, ad
# hoc fixture, not a permanent repo file) a hand-built plan with an
# arbitrarily-named `aws_cloudwatch_log_group` wired via
# `logging_config { log_group = aws_cloudwatch_log_group.custom.name }` and
# NO name anywhere matching `/aws/lambda/...` -- PASS, no deny, proving the
# wiring disjunct alone is sufficient.

package cdktn_bench.lambda_log_group_ownership_and_retention

import rego.v1

planned_resources := input.planned_values.root_module.resources

log_groups := [r |
	some r in planned_resources
	r.type == "aws_cloudwatch_log_group"
]

lambda_functions := [r |
	some r in planned_resources
	r.type == "aws_lambda_function"
]

# Path (a): the EXACT name AWS Lambda uses for this function's own log
# destination BY CONVENTION, when nothing wires the function to a log
# group explicitly.
expected_log_group_name(fn) := sprintf("/aws/lambda/%s", [fn.values.function_name])

governs_by_convention(fn) if {
	some lg in log_groups
	lg.values.name == expected_log_group_name(fn)
}

# Path (b): the function is EXPLICITLY wired to a log group this plan
# declares, via `logging_config[].log_group` -- a first-class,
# never-computed Lambda argument (verified against hashicorp/aws 6.58.0's
# own schema; mirrored 1:1 by @cdktn/provider-aws 24.8.0's `logGroup?:
# string` binding) that tells Lambda exactly where to write, overriding
# the naming convention entirely and making ANY log group name a valid,
# governed destination. `fn.values.logging_config` is simply absent (not
# null/[]) when no `logging_config` block is authored -- `some cfg in
# fn.values.logging_config` on an absent key yields zero results, not an
# error (standard Rego `in`-over-undefined semantics), so this disjunct is
# safely a no-op for every fixture that never sets it.
governs_by_wiring(fn) if {
	some cfg in fn.values.logging_config
	some lg in log_groups
	cfg.log_group == lg.values.name
}

any_log_group_governs(fn) if governs_by_convention(fn)

any_log_group_governs(fn) if governs_by_wiring(fn)

deny contains msg if {
	some fn in lambda_functions
	not any_log_group_governs(fn)
	msg := sprintf(
		"%s: no aws_cloudwatch_log_group in this plan governs this function's logs -- neither named exactly %q (this function's own implicit log destination) nor explicitly wired via logging_config[].log_group to a log group this plan declares",
		[fn.address, expected_log_group_name(fn)],
	)
}

# Fail-closed: an aws_lambda_function exists but NO aws_cloudwatch_log_group
# resource exists anywhere in the plan at all. The `deny` rule above
# iterates `lambda_functions` and checks `any_log_group_governs`, which is
# vacuously false (not merely "no violation found") when `log_groups` is
# empty -- so this duplicates that outcome by design, not by accident: it
# exists so this policy is self-consistent even if the comparison logic
# above is ever refactored to iterate `log_groups` instead. It never
# changes an OBSERVED tier for any of this scenario's own fixtures (catch
# 1's "left implicit" fixture already fails tier-0's `log-group-exists`
# first, per gates/oracle_falsifiability.py's own observed_tier semantics
# -- the lowest failing tier wins).
deny contains msg if {
	count(lambda_functions) > 0
	count(log_groups) == 0
	msg := "an aws_lambda_function exists, but no aws_cloudwatch_log_group resource exists anywhere in the plan"
}
