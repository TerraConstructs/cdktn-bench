# Hand-authored -- NOT a generator stub. oracles/emit.py never overwrites
# this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   s3-bucket-hardening-decomposition
# Intent doc: oracles/s3-bucket-hardening-decomposition/intent.md
# TF half:    ../../rego/s3-bucket-hardening-decomposition/policy.rego
# `input` is the awscdk arm's synthesized CloudFormation template, not the
# plan JSON the TF half sees (specs/SCHEMA.md §4.5); the generated
# tests/static_tiers.sh evaluates this package's `deny` against that
# template and fails tier 1 on a non-empty set.
#
# Two facts, both cross-resource logical-id JOINS stated by reference on the
# TF side and unavailable to cfn-guard 3.2.0: the TLS-deny statements must
# cover THIS bucket twice (its own ARN and an object-ARN derived from it),
# and KMSMasterKeyID must name a KMS key declared here. cfn-guard's proxies
# were weaker in both places -- `count(Resource.*) >= 2` passes two entries
# naming an unrelated bucket, `KMSMasterKeyID.'Fn::GetAtt' EXISTS` passes a
# GetAtt on any other resource. No fixture verdict changes. not_verifiable:
# a literal ARN against a bucket whose BucketName is generated at deploy.

package cdktn_bench.s3_bucket_hardening_decomposition

import rego.v1

resources := object.get(input, "Resources", {})

s3_buckets[id] := r if {
	some id, r in resources
	r.Type == "AWS::S3::Bucket"
}

kms_keys[id] := r if {
	some id, r in resources
	r.Type == "AWS::KMS::Key"
}

# Every logical id an intrinsic anywhere inside `value` names, at any depth,
# so this is independent of whether the reference is spelled as a bare Ref,
# an Fn::GetAtt, or either nested inside an Fn::Join or an Fn::Sub.
referenced_ids(value) := {id |
	walk(value, [_, node])
	is_object(node)
	id := _intrinsic_target(node)
}

_intrinsic_target(node) := node.Ref if is_string(node.Ref)

_intrinsic_target(node) := node["Fn::GetAtt"][0] if is_array(node["Fn::GetAtt"])

_intrinsic_target(node) := id if {
	is_string(node["Fn::Sub"])
	[[id]] := regex.find_all_string_submatch_n(`\$\{([A-Za-z0-9]+)[.}]`, node["Fn::Sub"], 1)
}

as_list(v) := v if is_array(v)

as_list(v) := [v] if not is_array(v)

# --- the bucket policy, and the TLS-deny statements inside it -------------

bucket_policies_for(bucket_id) := {id |
	some id, r in resources
	r.Type == "AWS::S3::BucketPolicy"
	bucket_id in referenced_ids(object.get(r, ["Properties", "Bucket"], null))
}

tls_deny_statements(policy_id) := [stmt |
	some stmt in as_list(object.get(resources, [policy_id, "Properties", "PolicyDocument", "Statement"], []))
	object.get(stmt, "Effect", null) == "Deny"
	object.get(stmt, ["Condition", "Bool", "aws:SecureTransport"], null) == "false"
]

# A Resource entry that resolves to this bucket: by logical id, or -- when
# the bucket pins a literal BucketName -- by a literal ARN built from it,
# the awscdk equivalent of the TF half's resolved-value fallback.
_covers(bucket_id, entry) if {
	bucket_id in referenced_ids(entry)
}

_covers(bucket_id, entry) if {
	is_string(entry)
	name := object.get(s3_buckets[bucket_id], ["Properties", "BucketName"], null)
	is_string(name)
	startswith(entry, sprintf("arn:aws:s3:::%s", [name]))
}

covering_entries(bucket_id, policy_id) := [entry |
	some stmt in tls_deny_statements(policy_id)
	some entry in as_list(object.get(stmt, "Resource", []))
	_covers(bucket_id, entry)
]

deny contains msg if {
	some bucket_id, _ in s3_buckets
	count(bucket_policies_for(bucket_id)) == 0
	msg := sprintf(
		"%s: no AWS::S3::BucketPolicy in this template names this bucket -- the TLS-deny requirement cannot be satisfied without one",
		[bucket_id],
	)
}

deny contains msg if {
	some bucket_id, _ in s3_buckets
	some policy_id in bucket_policies_for(bucket_id)
	count(tls_deny_statements(policy_id)) == 0
	msg := sprintf(
		"%s: no Deny statement conditioned on Bool[\"aws:SecureTransport\"] == \"false\" -- \"any request not made over TLS must be rejected\" is not satisfied",
		[policy_id],
	)
}

# Aggregated across the TLS-deny statements, never per statement: a policy
# that splits the bucket ARN and the object-ARN pattern into two separate
# SecureTransport Deny statements covers both just as well as one.
deny contains msg if {
	some bucket_id, _ in s3_buckets
	some policy_id in bucket_policies_for(bucket_id)
	count(tls_deny_statements(policy_id)) > 0
	n := count(covering_entries(bucket_id, policy_id))
	n < 2
	msg := sprintf(
		"%s: the TLS-deny statements' combined Resource coverage names %s only %d time(s) (need 2 -- once for the bucket ARN, once for the object-ARN pattern); a Deny naming only the bucket ARN leaves every object-level request over plain HTTP allowed",
		[policy_id, bucket_id, n],
	)
}

# --- KMSMasterKeyID names a KMS key declared in this template -------------

sse_defaults(bucket) := [d |
	some cfg in as_list(object.get(bucket, ["Properties", "BucketEncryption", "ServerSideEncryptionConfiguration"], []))
	d := object.get(cfg, "ServerSideEncryptionByDefault", null)
	is_object(d)
]

_names_a_declared_key(d) if {
	some id in referenced_ids(object.get(d, "KMSMasterKeyID", null))
	kms_keys[id]
}

deny contains msg if {
	some bucket_id, bucket in s3_buckets
	some d in sse_defaults(bucket)
	object.get(d, "SSEAlgorithm", null) == "aws:kms"
	not _names_a_declared_key(d)
	msg := sprintf(
		"%s: SSEAlgorithm is aws:kms but KMSMasterKeyID does not name an AWS::KMS::Key declared in this template -- an imported/hardcoded key ARN literal is not verifiably 'a key we control' from a static artifact",
		[bucket_id],
	)
}

# The one fact this template cannot settle: a literal ARN Resource entry
# against a bucket whose own name is generated at deploy time. Non-gating --
# the coverage rule above already denies the entry for naming nothing here.
not_verifiable contains msg if {
	some bucket_id, bucket in s3_buckets
	not is_string(object.get(bucket, ["Properties", "BucketName"], null))
	some policy_id in bucket_policies_for(bucket_id)
	some stmt in tls_deny_statements(policy_id)
	some entry in as_list(object.get(stmt, "Resource", []))
	is_string(entry)
	msg := sprintf(
		"%s: a TLS-deny Resource entry is the literal %q while %s's BucketName is generated at deploy time -- whether that ARN is this bucket's cannot be settled from this template",
		[policy_id, entry, bucket_id],
	)
}
