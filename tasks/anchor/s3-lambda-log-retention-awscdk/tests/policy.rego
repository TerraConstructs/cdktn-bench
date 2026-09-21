# awscdk tier-1 for s3-lambda-log-retention. `input` is the synthesized
# CloudFormation template, not the plan JSON the TF half
# (../../rego/s3-lambda-log-retention/policy.rego) sees. Intent:
# oracles/s3-lambda-log-retention/intent.md.
#
# The fact is a cross-resource logical-id JOIN: an s3.amazonaws.com-
# principal'd permission's SourceArn must resolve to an AWS::S3::Bucket
# declared here, which is what the TF half checks by reference.
#
# Strictness: the reference is read with `expr_names` below, never a
# top-level `Fn::GetAtt` lookup, because the TF half accepts the bucket named
# through ANY expression its `.references` list reports -- one CFN spelling
# only would reject the Fn::Sub/Fn::Join forms of the same reference, the
# cross-arm strictness break Amendment 29 (equal-strictness grading across
# arms is binding) forbids. Stricter than the retired cfn-guard bundle, whose
# `SourceArn.'Fn::GetAtt' EXISTS` proxy passed a GetAtt on any other
# GetAtt-addressable resource at all.
# not_verifiable has no case -- both halves of the join are logical ids.

package cdktn_bench.s3_lambda_log_retention

import rego.v1

resources := object.get(input, "Resources", {})

s3_buckets[id] := r if {
	some id, r in resources
	r.Type == "AWS::S3::Bucket"
}

s3_invoke_permissions[id] := r if {
	some id, r in resources
	r.Type == "AWS::Lambda::Permission"
	object.get(r, ["Properties", "Principal"], null) == "s3.amazonaws.com"
}

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

# The join. A hardcoded or wildcard ARN is a plain string and names nothing;
# an intrinsic on some other resource names a logical id whose Type is not
# AWS::S3::Bucket.
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

# Fail closed: a comprehension over zero permissions denies nothing, however
# badly the template is missing the grant entirely.
deny contains msg if {
	count(s3_buckets) > 0
	count(s3_invoke_permissions) == 0
	msg := "an AWS::S3::Bucket exists, but no AWS::Lambda::Permission granting Principal s3.amazonaws.com exists anywhere in the template -- S3 cannot invoke the Lambda function without one"
}
