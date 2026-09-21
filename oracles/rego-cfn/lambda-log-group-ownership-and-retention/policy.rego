# awscdk tier-1 for lambda-log-group-ownership-and-retention. `input` is the
# synthesized CloudFormation template; cross-resource references are {"Ref": ...}
# / {"Fn::GetAtt": [...]} objects naming a logical id.
#
# Intent: a log group this template declares actually governs the function's
# logs, by either mechanism AWS offers and with neither preferred -- named
# exactly /aws/lambda/<the function's own name>, or wired via LoggingConfig.
#
# not_verifiable: a log group whose LogGroupName is an intrinsic this policy
# cannot resolve (anything but a literal, an Fn::Join of a literal prefix with a
# reference, or an Fn::Sub naming a logical id). Deny still fails closed; the
# marker records that the name was not read.
#
# STRICTNESS DIFFERENCE from the retired cfn-guard bundle, weaker on both
# disjuncts: with no string-concatenation operator it checked only the
# ^/aws/lambda/ PREFIX, so an unwired group named /aws/lambda/processor beside a
# function named event-processor passed there and denies here; and its wiring
# check was a bare "LoggingConfig.LogGroup exists", so a function pointed at a
# group outside the template passed there and denies here. Both now match the
# plan-JSON twin -- the equal-strictness cross-arm grading Amendment 29 binds.

package cdktn_bench.lambda_log_group_ownership_and_retention

import rego.v1

resources := object.get(input, "Resources", {})

log_group_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::Logs::LogGroup"
}

function_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::Lambda::Function"
}

properties(lid) := object.get(resources[lid], "Properties", {})

convention_prefix := "/aws/lambda/"

# True iff `node` is a CloudFormation reference naming logical id `lid`. Ref on
# AWS::Lambda::Function returns the function NAME and Ref on AWS::Logs::LogGroup
# returns the log group NAME, so Ref is the correct spelling on both edges this
# policy walks.
references_logical_id(node, lid) if {
	is_object(node)
	node.Ref == lid
}

references_logical_id(node, lid) if {
	is_object(node)
	is_array(node["Fn::GetAtt"])
	node["Fn::GetAtt"][0] == lid
}

references_logical_id(node, lid) if {
	is_object(node)
	is_string(node["Fn::GetAtt"])
	split(node["Fn::GetAtt"], ".")[0] == lid
}

log_group_name(lid) := object.get(properties(lid), "LogGroupName", null)

# --- mechanism (a): the convention name, resolved three ways ---------------
# A literal name, which is what a hardcoded `/aws/lambda/<name>` string emits.
# Exact, not prefix: the suffix must be this function's own name.
names_convention_of(gid, fid) if {
	name := log_group_name(gid)
	is_string(name)
	fn_name := object.get(properties(fid), "FunctionName", null)
	is_string(fn_name)
	name == concat("", [convention_prefix, fn_name])
}

# `logGroupName: `/aws/lambda/${fn.functionName}`` -- CDK renders template
# interpolation off the function's own name as an Fn::Join, never a string.
# The reference in the second segment names the function's logical id, so this
# shape IS the exact convention name whether or not FunctionName is set.
names_convention_of(gid, fid) if {
	join := object.get(log_group_name(gid), "Fn::Join", null)
	is_array(join)
	join[0] == ""
	segments := join[1]
	count(segments) == 2
	segments[0] == convention_prefix
	references_logical_id(segments[1], fid)
}

# The Fn::Sub spelling of the same interpolation, `/aws/lambda/${LogicalId}`.
names_convention_of(gid, fid) if {
	sub := object.get(log_group_name(gid), "Fn::Sub", null)
	is_string(sub)
	sub == concat("", [convention_prefix, "${", fid, "}"])
}

governed_by_convention(fid) if {
	some gid in log_group_ids
	names_convention_of(gid, fid)
}

# --- mechanism (b): explicit wiring ---------------------------------------
# LoggingConfig.LogGroup tells Lambda exactly where to write and accepts a log
# group of any name, so a group reached this way governs the function whatever
# it is called. It must nevertheless be a log group THIS template declares --
# the join the retired cfn-guard rule could not make.
wired_log_group(fid) := object.get(object.get(properties(fid), "LoggingConfig", {}), "LogGroup", null)

governed_by_wiring(fid) if {
	some gid in log_group_ids
	references_logical_id(wired_log_group(fid), gid)
}

governed_by_wiring(fid) if {
	some gid in log_group_ids
	wired := wired_log_group(fid)
	is_string(wired)
	wired == log_group_name(gid)
}

governed(fid) if governed_by_convention(fid)

governed(fid) if governed_by_wiring(fid)

deny contains msg if {
	some fid in function_ids
	not governed(fid)
	msg := sprintf(
		"AWS::Lambda::Function %q: no AWS::Logs::LogGroup in this template governs its logs -- none is named exactly %q (this function's own implicit log destination) and its LoggingConfig.LogGroup wires it to none of them",
		[fid, concat("", [convention_prefix, object.get(properties(fid), "FunctionName", "<generated at deploy time>")])],
	)
}

# Fail-closed companion: a function exists and the template declares no log
# group at all. The rule above already covers this, since `governed` is
# vacuously false over an empty set; this states the fact directly so the
# message names the real shortfall.
deny contains msg if {
	count(function_ids) > 0
	count(log_group_ids) == 0
	msg := "an AWS::Lambda::Function exists, but the template declares no AWS::Logs::LogGroup at all"
}

name_is_readable(gid) if is_string(log_group_name(gid))

name_is_readable(gid) if is_array(object.get(log_group_name(gid), "Fn::Join", null))

name_is_readable(gid) if is_string(object.get(log_group_name(gid), "Fn::Sub", null))

not_verifiable contains msg if {
	some gid in log_group_ids
	log_group_name(gid) != null
	not name_is_readable(gid)
	msg := sprintf(
		"AWS::Logs::LogGroup %q has a LogGroupName this policy cannot resolve statically, so it was not matched against any function's convention name",
		[gid],
	)
}
