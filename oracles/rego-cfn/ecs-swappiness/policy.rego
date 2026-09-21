# awscdk tier-1 for ecs-swappiness. `input` is the synthesized CloudFormation
# template; resources live under input.Resources[<LogicalId>].
#
# Intent: a container definition that sets LinuxParameters.Swappiness must also
# set LinuxParameters.MaxSwap -- ECS silently ignores swappiness without it, so
# a tuned value that is present in the artifact but ineffective in the account
# is not a solution. Same conditional, same strictness, as the plan-JSON twin
# oracles/rego/ecs-swappiness/policy.rego.
#
# not_verifiable: a task definition whose ContainerDefinitions is not a readable
# array (an intrinsic standing in for the whole list), so no container can be
# reached. Both properties are literals in every shape aws-cdk-lib emits.
#
# No strictness difference from the retired cfn-guard bundle: it applied the
# same `when Swappiness exists { MaxSwap exists }` over the same properties.
# solution/broken/swappiness-requires-maxswap-cfn-override (a raw override
# forcing LinuxParameters: {Swappiness: 42} with no MaxSwap) fires this rule on
# both engines; the other two fixtures pass tier 1 on both.

package cdktn_bench.ecs_swappiness

import rego.v1

resources := object.get(input, "Resources", {})

task_def_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::ECS::TaskDefinition"
}

# `object.get` at every level: a task definition may legitimately carry no
# ContainerDefinitions, a container no LinuxParameters. An undefined lookup
# would make the enclosing deny rule silently not fire -- the fail-open
# direction, which an oracle may never take.
container_definitions(lid) := cds if {
	cds := object.get(object.get(resources[lid], "Properties", {}), "ContainerDefinitions", [])
	is_array(cds)
}

linux_parameters(c) := lp if {
	lp := object.get(c, "LinuxParameters", {})
	is_object(lp)
}

swappiness_set(c) if {
	object.get(linux_parameters(c), "Swappiness", null) != null
}

maxswap_set(c) if {
	object.get(linux_parameters(c), "MaxSwap", null) != null
}

deny contains msg if {
	some lid in task_def_ids
	some c in container_definitions(lid)
	swappiness_set(c)
	not maxswap_set(c)
	msg := sprintf(
		"AWS::ECS::TaskDefinition %q: container %q sets LinuxParameters.Swappiness but no LinuxParameters.MaxSwap -- AWS ECS silently ignores swappiness without maxSwap, so the tuned value has no effect",
		[lid, object.get(c, "Name", "<unnamed>")],
	)
}

not_verifiable contains msg if {
	some lid in task_def_ids
	not is_array(object.get(object.get(resources[lid], "Properties", {}), "ContainerDefinitions", []))
	msg := sprintf(
		"AWS::ECS::TaskDefinition %q: ContainerDefinitions is not a readable array in the template, so no container's swappiness/maxSwap pairing could be checked",
		[lid],
	)
}
