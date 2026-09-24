# Hand-authored (Slice D). NOT a generator stub.
#
# Scenario:      ecs-swappiness (specs/ecs-swappiness.yaml)
# Intent doc:    oracles/ecs-swappiness/intent.md
# Graded against `terraform show -json` plan JSON for every TF-shaped arm --
# hcl_raw, terraconstructs and hcl_modules -- specs/SCHEMA.md §4.2/§8. On
# hcl_modules the task definition is declared inside a module body; the plan
# normaliser hoists it into `root_module.resources`, so the one filter below
# reads it there like any other arm's, with the module call path on `.address`.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.ecs_swappiness.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Encodes the spec's one tier-"1" structural_assert,
# maxswap-present-when-swappiness-tuned, in its fuller "IF swappiness is set
# THEN maxSwap must also be set" form (the spec's own tf_jsonpath is the
# unconditional-existence simplification that holds for THIS scenario, since
# the instruction always asks for a tuned swappiness value -- see that
# assert's description in the spec for why).
#
# WHY THIS IS TIER 1, NOT A SECOND TIER-0 STRUCTURAL_ASSERT (spec's own
# swappiness-requires-maxswap catch carries the full reasoning; summarized
# here since it's this file's reason to exist at all): aws-cdk-lib's
# LinuxParameters construct (aws-ecs/lib/linux-parameters.ts:116) and
# terraconstructs 0.2.13's own port (lib/aws/compute/ecs/linux-parameters.js:55,
# read directly from the pinned installed package at spec-authoring time)
# BOTH silently drop `swappiness` to absent whenever `maxSwap` is unset --
# `this.swappiness = props.maxSwap ? props.swappiness : undefined;`,
# byte-for-byte identical in both. So on awscdk AND terraconstructs, a
# "forgot maxSwap" mistake already fails the EXISTING tier-0
# swappiness-value-correct assert (Swappiness is simply absent from the
# synthesized artifact) -- this rule can only ever fire against those two
# arms via a deliberate L1/override escape-hatch fixture. Neither hcl_raw nor
# hcl_modules has such construct-level protection: the raw
# `container_definitions` is an untyped jsonencode()'d JSON blob, and the ecs
# container-definition submodule types both fields as bare `optional(number)`
# and supplies neither, so `swappiness: 42` with no `maxSwap` key sits right
# there, literal and structurally well-formed, in real plan JSON --
# THIS rule is the only thing that ever catches that on either arm. Verified
# against real `terraform show -json` output for a hand-built hcl_raw
# negative fixture (swappiness=42, no maxSwap key at all):
#   $ jq '.planned_values.root_module.resources[]
#         | select(.type=="aws_ecs_task_definition")
#         | .values.container_definitions | fromjson' plan.json
#   [{"name":"app","image":"...","memory":256,"essential":true,
#     "linuxParameters":{"swappiness":42}}]
# -- swappiness fully present and plan-time-known, no maxSwap anywhere.

package cdktn_bench.ecs_swappiness

import rego.v1

task_defs := [pv |
	some pv in input.planned_values.root_module.resources
	pv.type == "aws_ecs_task_definition"
]

# `values.container_definitions` is a jsonencode()'d STRING (same |fromjson
# case the tier-0 asserts document in the spec) -- decode it once per task
# definition resource into a list of container objects.
containers(td) := json.unmarshal(td.values.container_definitions)

# `object.get` at every level, not direct field access: `linuxParameters`
# itself may be entirely absent from a container object (not just its
# `swappiness`/`maxSwap` children), and direct access on a missing key
# errors the whole rule instead of evaluating false.
swappiness_set(c) if {
	lp := object.get(c, "linuxParameters", {})
	object.get(lp, "swappiness", null) != null
}

maxswap_set(c) if {
	lp := object.get(c, "linuxParameters", {})
	object.get(lp, "maxSwap", null) != null
}

deny contains msg if {
	some td in task_defs
	some c in containers(td)
	swappiness_set(c)
	not maxswap_set(c)
	msg := sprintf(
		"%s: container %q sets linuxParameters.swappiness but no linuxParameters.maxSwap -- AWS ECS silently ignores swappiness without maxSwap, so the tuned value has no effect",
		[td.address, object.get(c, "name", "<unnamed>")],
	)
}

# No `not_verifiable` rule (SCHEMA.md §4.2.1's residual-findings fix,
# see toy-ssm-parameter/policy.rego for the worked example this scenario's
# generator warning points at): that mechanism exists for a value derived
# from ANOTHER resource's provider-computed output (an ARN, a generated
# id) going `(known after apply)` at plan time. Nothing this scenario asks
# for puts such a value inside container_definitions -- the image is a
# literal registry string and the swappiness/maxSwap pair are literal
# numbers -- and on hcl_modules the only value the container-definition
# submodule interpolates is the log group NAME it sets itself, which is
# plan-time-known. Measured on real plan JSON for every enabled arm's
# reference through `make falsifiability`, where tier 1 reports PASS rather
# than an unresolved path. The generator's plan-time-value-path warning is a
# blanket heuristic on any tier-1 tf_jsonpath under `.values...` -- correct
# to flag generically, verified not to apply to this scenario.
