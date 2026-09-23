# Hand-authored (2026-08-21) -- NOT a generator stub. emit_oracles() never
# overwrites this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   asg-launch-template-tag-propagation (specs/asg-launch-template-tag-propagation.yaml)
# Intent doc: oracles/asg-launch-template-tag-propagation/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document.
#
# Encodes the every-required-tag-reaches-instances tier-1 structural_assert: the ONE genuinely two-mechanism fact
# in this scenario (see the spec's own "ORACLE MUST TOLERATE / DEFEND"
# header comment for the full analysis). A required tag reaches launched
# instances if EITHER:
#   (a) some aws_autoscaling_group has a `tag` block with that key/value
#       and propagate_at_launch == true, OR
#   (b) some aws_launch_template has a `tag_specifications` entry with
#       resource_type == "instance" whose `tags` map carries that
#       key/value.
# Every value this rule reads is plan-time-known on a correct solution --
# none of it is built from another resource's provider-computed output
# (SCHEMA.md §4.2.1's plan-time-unknown concern does not apply anywhere in
# this scenario), so unlike s3-lambda-log-retention's/toy-ssm-parameter's
# own Rego there is no `.configuration...expressions.*.references`
# graph-edge fallback needed here -- everything is read straight from
# `.planned_values`.
#
# Verified directly (opa 1.19.0) against REAL `terraform plan` output, not
# hand-built JSON fixtures -- re-confirmed 2026-08-21 against real
# terraform 1.15.8 + hashicorp/aws 6.58.0 (the exact pinned versions) after
# this scenario's cfn-guard sibling rule (oracles/cfn-guard/.../
# policy.guard) was found, in this same verifier round, to have shipped an
# unrepresentative hand-built-fixture proof that missed a real bug -- this
# file's own claim is raised to the same evidence standard even though this
# rule itself was never broken (`object.get(spec.tags, key, null) == value`
# is a map lookup, not a quantifier, so there is no ALL-vs-ANY hazard here
# the way there was in the cfn-guard Tags[*] block):
#   - a real hcl_raw `main.tf` using ONLY mechanism (a) (ASG tag blocks,
#     propagate_at_launch true, launch template untagged -- this
#     scenario's own reference solutions) -> `terraform init && plan`,
#     `opa eval` deny is EMPTY (PASS).
#   - a real hcl_raw `main.tf` using ONLY mechanism (b) (launch template
#     `tag_specifications {resource_type = "instance"}`, no ASG `tag{}`
#     blocks) -> deny is EMPTY (PASS) -- this is the alternative shape
#     this scenario's own reference solutions do not use but the oracle
#     must still tolerate.
#   - the `instances-never-tagged` broken fixture (neither mechanism,
#     volume tag_specifications correct, nothing else -- run through the
#     real toolchain on every arm via `solution/broken/
#     instances-never-tagged/solve.sh`) -> deny lists BOTH required keys
#     (FAIL).
#   - terraconstructs is graded by this identical file against the
#     identical `terraform show -json` plan JSON shape for
#     `aws_launch_template`/`aws_autoscaling_group` (both TF-shaped arms
#     plan against the same hashicorp/aws provider schema) -- the hcl_raw
#     proof above carries over structurally; not separately re-run through
#     a terraconstructs synth for this specific shape.

package cdktn_bench.asg_launch_template_tag_propagation

import rego.v1

planned_resources := input.planned_values.root_module.resources

asgs := [r |
	some r in planned_resources
	r.type == "aws_autoscaling_group"
]

launch_templates := [r |
	some r in planned_resources
	r.type == "aws_launch_template"
]

required_tags := {"CostCenter": "platform-42", "Environment": "prod"}

# (a) the ASG's own tag-propagation mechanism.
asg_tag_reaches(key, value) if {
	some asg in asgs
	some t in object.get(asg.values, "tag", [])
	t.key == key
	t.value == value
	t.propagate_at_launch == true
}

# (b) the launch template's own instance-resourceType tag specification.
launch_template_instance_tag_reaches(key, value) if {
	some lt in launch_templates
	some spec in object.get(lt.values, "tag_specifications", [])
	spec.resource_type == "instance"
	object.get(spec.tags, key, null) == value
}

instance_tag_reaches(key, value) if asg_tag_reaches(key, value)

instance_tag_reaches(key, value) if launch_template_instance_tag_reaches(key, value)

deny contains msg if {
	some key, value in required_tags
	not instance_tag_reaches(key, value)
	msg := sprintf(
		"no accepted mechanism (aws_autoscaling_group tag block with propagate_at_launch=true, or aws_launch_template instance-resourceType tag_specifications) carries required tag %s=%s to launched instances",
		[key, value],
	)
}

# Fail-closed: an ASG exists but no launch template exists anywhere in the
# plan at all. Defense in depth -- this scenario's own tier-0
# launch-template-exists assert already covers this case directly, so this
# rule should never be the FIRST thing to catch a real broken fixture, but
# it keeps the comprehensions above from being vacuously silent if it ever
# is (mirrors every other scenario's own fail-closed convention, e.g.
# oracles/rego/s3-lambda-log-retention/policy.rego's own second rule).
deny contains msg if {
	count(asgs) > 0
	count(launch_templates) == 0
	msg := "an aws_autoscaling_group exists, but no aws_launch_template exists anywhere in the plan"
}

# not_verifiable: gen.py's generation-time heuristic (SCHEMA.md §4.2.1)
# flags any tier-1 assert reading a `.planned_values...values.*` path as a
# POSSIBLE plan-time-unknown case and warns if no not_verifiable rule is
# defined -- always empty here on purpose, not merely unauthored. Every
# value asg_tag_reaches/launch_template_instance_tag_reaches read (tag
# key/value/propagate_at_launch, tag_specifications resource_type/tags) is
# an agent-authored literal on every correct solution in THIS scenario --
# none of it is ever built from another resource's provider-computed
# output (no `.arn`/`.id` reference anywhere in this scenario's own
# reference solutions or catch fixtures), so the plan-time-unknown
# contagion SCHEMA.md §4.2.1 warns about structurally cannot arise here.
# Declared explicitly (rather than left undefined) so this is a reviewed,
# recorded "no" rather than a silent gap -- see the toy-ssm-parameter
# precedent this convention is modeled on.
not_verifiable contains msg if {
	false
	msg := ""
}
