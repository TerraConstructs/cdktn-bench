# awscdk tier-1 for s3-notification-custom-resource-tax. `input` is the
# synthesized CloudFormation template, not the plan JSON the TF half
# (../../rego/s3-notification-custom-resource-tax/policy.rego) sees.
# Intent: oracles/s3-notification-custom-resource-tax/intent.md.
#
# Both facts are cross-resource logical-id JOINS, stated by reference on the
# TF side: the permission's SourceArn must resolve to an AWS::S3::Bucket
# declared here, the notification's Function to an AWS::Lambda::Function
# declared here. Scope is unchanged -- only the native
# NotificationConfiguration.LambdaConfigurations shape, never
# Custom::S3BucketNotifications, and EventBridge is out of v1.
#
# Strictness: both joins read the reference with `expr_names` below, never a
# top-level `Fn::GetAtt` lookup, because the TF half accepts the target named
# through ANY expression its `.references` list reports -- one CFN spelling
# only would reject the Fn::Sub/Fn::Join forms of the same reference, the
# cross-arm strictness break Amendment 29 (equal-strictness grading across
# arms is binding) forbids. Stricter than the retired cfn-guard bundle, whose
# `'Fn::GetAtt' EXISTS` proxy passed a GetAtt on any other resource at all.
# not_verifiable has no case -- both halves of each join are logical ids.

package cdktn_bench.s3_notification_custom_resource_tax

import rego.v1

resources := object.get(input, "Resources", {})

s3_buckets[id] := r if {
	some id, r in resources
	r.Type == "AWS::S3::Bucket"
}

lambda_functions[id] := r if {
	some id, r in resources
	r.Type == "AWS::Lambda::Function"
}

s3_invoke_permissions[id] := r if {
	some id, r in resources
	r.Type == "AWS::Lambda::Permission"
	object.get(r, ["Properties", "Principal"], null) == "s3.amazonaws.com"
}

notification_configs := [[id, cfg] |
	some id, bucket in s3_buckets
	some cfg in object.get(bucket, ["Properties", "NotificationConfiguration", "LambdaConfigurations"], [])
]

# --- which logical ids does an intrinsic expression NAME? ------------------
#
# The CFN-side equivalent of the TF half's pre-computed `.references` list:
# `expr_names` walks an arbitrary expression to any depth, `node_names`
# decodes one node. A literal string, a number or an absent property yields
# the empty set, which is what makes "hardcoded ARN" and "no SourceArn at
# all" fail the same rule they fail on the TF-shaped arms.

# `${Logical}` / `${Logical.Attr}` inside an Fn::Sub template string.
# `${!Literal}` is Fn::Sub's own escape and names nothing.
sub_tokens(s) := {name |
	some m in regex.find_n(`\$\{[^}]*\}`, s, -1)
	inner := trim_suffix(trim_prefix(m, "${"), "}")
	not startswith(inner, "!")
	name := split(inner, ".")[0]
}

# In the two-element Fn::Sub form a `${X}` naming a key of the variable map
# is a local substitution, not a logical id. The map's VALUES are ordinary
# expressions and are walked on their own.
sub_declared_vars(a) := {k |
	is_object(a[1])
	some k, _ in a[1]
}

node_names(node) := names if {
	refs := {n |
		n := node.Ref
		is_string(n)
	}
	getatt_list := {n |
		a := node["Fn::GetAtt"]
		is_array(a)
		n := a[0]
		is_string(n)
	}
	getatt_string := {n |
		s := node["Fn::GetAtt"]
		is_string(s)
		n := split(s, ".")[0]
	}
	sub_string := {n |
		s := node["Fn::Sub"]
		is_string(s)
		some n in sub_tokens(s)
	}
	sub_list := {n |
		a := node["Fn::Sub"]
		is_array(a)
		is_string(a[0])
		some n in sub_tokens(a[0])
		not n in sub_declared_vars(a)
	}
	names := (((refs | getatt_list) | getatt_string) | sub_string) | sub_list
}

expr_names(v) := {n |
	walk(v, [_, node])
	some n in node_names(node)
}

# --- the permission's SourceArn resolves to a bucket in this template ----

source_arn_resolves_to_a_bucket(r) if {
	some name in expr_names(object.get(r, ["Properties", "SourceArn"], null))
	s3_buckets[name]
}

deny contains msg if {
	some id, r in s3_invoke_permissions
	not source_arn_resolves_to_a_bucket(r)
	msg := sprintf(
		"%s: Principal is s3.amazonaws.com but SourceArn does not resolve to an AWS::S3::Bucket declared in this template (no wildcard/hardcoded/omitted SourceArn permitted)",
		[id],
	)
}

deny contains msg if {
	count(s3_buckets) > 0
	count(s3_invoke_permissions) == 0
	msg := "an AWS::S3::Bucket exists, but no AWS::Lambda::Permission granting Principal s3.amazonaws.com exists anywhere in the template -- S3 cannot invoke the Lambda function without one"
}

# --- the notification's Function resolves to a function in this template --

function_resolves_to_a_lambda(cfg) if {
	some name in expr_names(object.get(cfg, "Function", null))
	lambda_functions[name]
}

deny contains msg if {
	some entry in notification_configs
	not function_resolves_to_a_lambda(entry[1])
	msg := sprintf(
		"%s: a NotificationConfiguration.LambdaConfigurations entry's Function does not resolve to an AWS::Lambda::Function declared in this template -- a hardcoded/unrelated ARN does not satisfy \"notify the claims processor\"",
		[entry[0]],
	)
}

# Fail closed: a comprehension over zero notification entries denies
# nothing, however badly the wiring is missing entirely.
deny contains msg if {
	count(lambda_functions) > 0
	count(notification_configs) == 0
	msg := "an AWS::Lambda::Function exists, but no AWS::S3::Bucket NotificationConfiguration.LambdaConfigurations entry exists anywhere in the template to wire uploads to it"
}
