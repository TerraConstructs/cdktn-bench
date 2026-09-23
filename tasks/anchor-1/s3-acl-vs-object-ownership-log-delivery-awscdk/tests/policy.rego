# awscdk tier-1 for s3-acl-vs-object-ownership-log-delivery. `input` is the
# synthesized CloudFormation template; resources live under
# input.Resources[<LogicalId>].
#
# Intent: no ownership control anywhere may leave S3 access control lists
# enabled -- neither ObjectWriter (the seed's value) nor BucketOwnerPreferred,
# which only changes ownership for objects uploaded with the
# bucket-owner-full-control canned ACL. BucketOwnerEnforced is the only
# compliant value. CloudFormation carries it in exactly one place,
# AWS::S3::Bucket.Properties.OwnershipControls, so there is no second resource
# shape as on Terraform. The other tier-1 assert, the log-delivery grant, does
# not apply to this arm: that document is literal JSON here, graded at tier 0.
#
# not_verifiable: nothing -- every value read is a literal, and the rules below
# fail closed on an unreadable one instead.
#
# No strictness difference from the retired cfn-guard bundle, whose iterated
# block likewise failed on ownership controls with nothing readable inside.
# solution/broken/acls-left-enabled-on-the-destination-bucket and
# solution/broken/seed-unchanged fire this policy on both engines.

package cdktn_bench.s3_acl_vs_object_ownership_log_delivery

import rego.v1

resources := object.get(input, "Resources", {})

bucket_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::S3::Bucket"
}

# Only buckets that declare the property at all: a bucket with no
# OwnershipControls emits no rule collection, and its absence is graded at tier
# 0 rather than here.
ownership_controls(lid) := oc if {
	oc := object.get(object.get(resources[lid], "Properties", {}), "OwnershipControls", null)
	is_object(oc)
}

acls_enabled_settings := {"ObjectWriter", "BucketOwnerPreferred"}

deny contains msg if {
	some lid in bucket_ids
	some rule in object.get(ownership_controls(lid), "Rules", [])
	setting := object.get(rule, "ObjectOwnership", "")
	setting in acls_enabled_settings
	msg := sprintf(
		"AWS::S3::Bucket %q sets OwnershipControls ObjectOwnership = %q, which leaves S3 access control lists ENABLED on that bucket; the only setting that disables them is BucketOwnerEnforced",
		[lid, setting],
	)
}

# Shape drift, denied rather than skipped -- a bucket that declares ownership
# controls but nothing readable inside them cannot be shown to disable access
# control lists, and reporting it compliant is the vacuous-satisfaction failure
# this tier exists to rule out.
deny contains msg if {
	some lid in bucket_ids
	oc := ownership_controls(lid)
	not is_array(object.get(oc, "Rules", null))
	msg := sprintf(
		"AWS::S3::Bucket %q declares OwnershipControls with no readable Rules list, so it cannot be shown to disable access control lists",
		[lid],
	)
}

deny contains msg if {
	some lid in bucket_ids
	some rule in object.get(ownership_controls(lid), "Rules", [])
	not is_string(object.get(rule, "ObjectOwnership", null))
	msg := sprintf(
		"AWS::S3::Bucket %q has an OwnershipControls rule whose ObjectOwnership is absent or not a readable string, so it cannot be shown to disable access control lists",
		[lid],
	)
}

not_verifiable contains msg if {
	false
	msg := ""
}
