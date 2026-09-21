# Hand-authored awscdk tier-1 bundle (ROADMAP.md M8: OPA/Rego grades tier 1
# on every arm). `input` is the awscdk arm's synthesized CloudFormation
# template, cdk.out/ScenarioStack.template.json. Intent:
# oracles/asg-launch-template-tag-propagation/intent.md.
#
# Encodes every-required-tag-reaches-instances at the strictness of the TF
# twin oracles/rego/<id>/policy.rego: for EACH of CostCenter=platform-42 and
# Environment=prod, at least one accepted mechanism carries the tag to every
# launched instance -- (a) an ASG Tags entry with that Key/Value and
# PropagateAtLaunch true, or (b) a launch template
# LaunchTemplateData.TagSpecifications entry with ResourceType "instance"
# whose Tags list carries that Key/Value. Both are read as ANY over their
# list, never ALL: a real synth emits CostCenter, Environment and CDK's own
# auto-injected `Name` tag together in one Tags list.
#
# not_verifiable: empty. Every value read is an authored literal.
#
# Strictness vs the retired oracles/cfn-guard/<id>/policy.guard: none -- the
# same disjunction and fail-closed companion, same verdict on every fixture.

package cdktn_bench.asg_launch_template_tag_propagation

import rego.v1

resources_of(t) := {lid: r |
	some lid, r in input.Resources
	r.Type == t
}

asgs := resources_of("AWS::AutoScaling::AutoScalingGroup")

launch_templates := resources_of("AWS::EC2::LaunchTemplate")

required_tags := {"CostCenter": "platform-42", "Environment": "prod"}

# (a) the ASG's own tag-propagation mechanism.
asg_tag_reaches(key, value) if {
	some _, asg in asgs
	some t in object.get(asg, ["Properties", "Tags"], [])
	t.Key == key
	t.Value == value
	t.PropagateAtLaunch == true
}

# (b) the launch template's own instance-resourceType tag specification.
launch_template_instance_tag_reaches(key, value) if {
	some _, lt in launch_templates
	some spec in object.get(lt, ["Properties", "LaunchTemplateData", "TagSpecifications"], [])
	spec.ResourceType == "instance"
	some t in object.get(spec, "Tags", [])
	t.Key == key
	t.Value == value
}

instance_tag_reaches(key, value) if asg_tag_reaches(key, value)

instance_tag_reaches(key, value) if launch_template_instance_tag_reaches(key, value)

deny contains msg if {
	some key, value in required_tags
	not instance_tag_reaches(key, value)
	msg := sprintf(
		"no accepted mechanism (an AWS::AutoScaling::AutoScalingGroup Tags entry with PropagateAtLaunch true, or an AWS::EC2::LaunchTemplate instance-resourceType TagSpecifications entry) carries required tag %s=%s to launched instances",
		[key, value],
	)
}

# Fail-closed: an ASG exists but no launch template exists anywhere in the
# template. Tier 0's own launch-template-exists assert already covers this,
# so this should never be the first rule to catch a real fixture.
deny contains msg if {
	count(asgs) > 0
	count(launch_templates) == 0
	msg := "an AWS::AutoScaling::AutoScalingGroup exists, but no AWS::EC2::LaunchTemplate exists anywhere in the template"
}

not_verifiable contains msg if {
	false
	msg := ""
}
