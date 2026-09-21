# awscdk tier-1 for named-resource-replacement. `input` is the synthesized
# CloudFormation template; resources live under input.Resources[<LogicalId>].
#
# Intent: the security group fronting the interface VPC endpoint keeps its
# ingress scoped to the VPC -- no ingress rule may allow 0.0.0.0/0 or ::/0.
# Egress is out of scope: the seed allows all outbound, so denying it would make
# the seed non-compliant and the widened-ingress catch unfalsifiable. Both
# shapes CDK emits are covered, as in oracles/rego/named-resource-replacement/
# policy.rego: the inline SecurityGroupIngress list and the standalone
# AWS::EC2::SecurityGroupIngress resource.
#
# STRICTNESS DIFFERENCE from the retired cfn-guard bundle, unsound in the
# REJECTING direction: comparing an intrinsic-valued CidrIp against the string
# "0.0.0.0/0" raised a ComparisonError it scored as a violation, so the
# idiomatic `Peer.ipv4(vpc.vpcCidrBlock)` -- CidrIp as {"Fn::GetAtt": [vpc,
# "CidrBlock"]} -- failed with a message claiming it allowed 0.0.0.0/0. Here
# such an entry denies nothing and is reported not_verifiable, as its plan-JSON
# twin already does. solution/broken/ingress-widened-to-the-internet fires the
# deny rules on both engines.

package cdktn_bench.named_resource_replacement

import rego.v1

resources := object.get(input, "Resources", {})

security_group_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::EC2::SecurityGroup"
}

standalone_ingress_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::EC2::SecurityGroupIngress"
}

properties(lid) := object.get(resources[lid], "Properties", {})

# `object.get` with a list default everywhere: a security group with no inline
# ingress list at all is a legal template, and an undefined lookup would make
# the deny rules below silently not fire.
inline_ingress(lid) := entries if {
	entries := object.get(properties(lid), "SecurityGroupIngress", [])
	is_array(entries)
}

open_ipv4 := "0.0.0.0/0"

open_ipv6 := "::/0"

deny contains msg if {
	some lid in security_group_ids
	some entry in inline_ingress(lid)
	object.get(entry, "CidrIp", "") == open_ipv4
	msg := sprintf(
		"AWS::EC2::SecurityGroup %q has an inline ingress rule open to 0.0.0.0/0 -- this security group fronts an interface VPC endpoint and its ingress must stay scoped to the VPC",
		[lid],
	)
}

deny contains msg if {
	some lid in security_group_ids
	some entry in inline_ingress(lid)
	object.get(entry, "CidrIpv6", "") == open_ipv6
	msg := sprintf(
		"AWS::EC2::SecurityGroup %q has an inline ingress rule open to ::/0 -- this security group fronts an interface VPC endpoint and its ingress must stay scoped to the VPC",
		[lid],
	)
}

# The same fact for the standalone-resource shape CDK emits for SG-to-SG peers
# and for rules added after the group is referenced elsewhere. A rule that read
# only the inline shape would be bypassed by an otherwise-idiomatic
# `Peer.anyIpv4()` added through this one.
deny contains msg if {
	some lid in standalone_ingress_ids
	object.get(properties(lid), "CidrIp", "") == open_ipv4
	msg := sprintf(
		"AWS::EC2::SecurityGroupIngress %q opens ingress to 0.0.0.0/0 -- this security group fronts an interface VPC endpoint and its ingress must stay scoped to the VPC",
		[lid],
	)
}

deny contains msg if {
	some lid in standalone_ingress_ids
	object.get(properties(lid), "CidrIpv6", "") == open_ipv6
	msg := sprintf(
		"AWS::EC2::SecurityGroupIngress %q opens ingress to ::/0 -- this security group fronts an interface VPC endpoint and its ingress must stay scoped to the VPC",
		[lid],
	)
}

# An entry whose source is an intrinsic that only CloudFormation can resolve
# (e.g. CidrIp: {"Fn::GetAtt": [vpc, "CidrBlock"]}) and which names no
# security-group or prefix-list source either.
source_is_unreadable(entry) if {
	not is_string(object.get(entry, "CidrIp", null))
	not is_string(object.get(entry, "CidrIpv6", null))
	object.get(entry, "SourceSecurityGroupId", null) == null
	object.get(entry, "SourcePrefixListId", null) == null
	object.get(entry, "CidrIp", null) != null
}

source_is_unreadable(entry) if {
	not is_string(object.get(entry, "CidrIpv6", null))
	object.get(entry, "CidrIpv6", null) != null
}

not_verifiable contains msg if {
	some lid in security_group_ids
	some entry in inline_ingress(lid)
	source_is_unreadable(entry)
	msg := sprintf(
		"AWS::EC2::SecurityGroup %q has an inline ingress rule whose source is an unresolved CloudFormation intrinsic; its scope could not be checked",
		[lid],
	)
}

not_verifiable contains msg if {
	some lid in standalone_ingress_ids
	source_is_unreadable(properties(lid))
	msg := sprintf(
		"AWS::EC2::SecurityGroupIngress %q has a source that is an unresolved CloudFormation intrinsic; its scope could not be checked",
		[lid],
	)
}
