# Hand-authored -- NOT a generator stub. oracles/emit.py never overwrites
# this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   singleton-child-resource-clobber
# Intent doc: oracles/singleton-child-resource-clobber/intent.md
# TF half:    ../../rego/singleton-child-resource-clobber/policy.rego
# `input` is the awscdk arm's synthesized CloudFormation template, not the
# plan JSON the TF half sees (specs/SCHEMA.md §4.5); the generated
# tests/static_tiers.sh evaluates this package's `deny` against that
# template and fails tier 1 on a non-empty set.
#
# Encodes no-storage-rule-is-left-un-enabled: no rule in the bucket's
# storage-rule document may be left un-enabled. On CloudFormation the rules
# are a property of the one AWS::S3::Bucket, so there is one place a rule
# can be spelled and no cross-resource join to make. Same strictness as the
# retired cfn-guard policy, which also denied a missing Status: absent is a
# shape this policy does not understand and must not pass silently.
# not_verifiable has no case -- Status is always a template literal.

package cdktn_bench.singleton_child_resource_clobber

import rego.v1

resources := object.get(input, "Resources", {})

buckets[id] := r if {
	some id, r in resources
	r.Type == "AWS::S3::Bucket"
}

deny contains msg if {
	some id, bucket in buckets
	some rule in object.get(bucket, ["Properties", "LifecycleConfiguration", "Rules"], [])
	status := object.get(rule, "Status", "<absent>")
	status != "Enabled"
	msg := sprintf(
		"%s declares a storage rule (Id %q) with Status %q -- every rule in this bucket's storage-rule document must be \"Enabled\", or the behaviour it describes never happens",
		[id, object.get(rule, "Id", "<unnamed>"), status],
	)
}
