#
# Hand-authored (ROUND 10, 2026-08-23) -- NOT a generator scaffold.
# emit_oracles() never overwrites this file once it exists
# (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   s3-notification-authoritative-singleton (specs/s3-notification-authoritative-singleton.yaml)
# Intent doc: oracles/s3-notification-authoritative-singleton/intent.md
#
# ENGINE. This is the awscdk arm's tier-1 bundle under
# `oracle.awscdk_tier1_engine: rego` (specs/SCHEMA.md §4.5). The generated
# tests/static_tiers.sh runs
#   opa eval -f raw -I -d policy.rego \
#     'data.cdktn_bench.s3_notification_authoritative_singleton.deny' \
#     < cdk.out/ScenarioStack.template.json
# and fails tier-1 iff that set is non-empty -- the SAME command line, the
# same package name and the same `deny` contract the hcl_raw and
# terraconstructs arms already ran. It REPLACES
# oracles/cfn-guard/s3-notification-authoritative-singleton/policy.guard,
# which was deleted at round 10 (an orphaned bundle no generated tests/
# copies is a policy that looks like grading and is not).
#
# `input` HERE IS A CLOUDFORMATION TEMPLATE, not plan JSON. Resources live
# at `input.Resources[<LogicalId>]` with `.Type`/`.Properties`, and every
# cross-resource reference is an intrinsic object -- {"Ref": <LogicalId>},
# {"Fn::GetAtt": [<LogicalId>, "Arn"]}, {"Fn::Join": [...]},
# {"Fn::Sub": "...${<LogicalId>.Arn}..."} -- naming a LOGICAL ID. The
# TF-shaped sibling (oracles/rego/s3-notification-authoritative-singleton/
# policy.rego) reads `input.planned_values`/`.configuration` keyed on plan
# ADDRESS. Structurally unrelated documents; deliberately separate files
# (SCHEMA.md §4.5, oracles/rego-cfn/README.md). They never load into one
# OPA instance.
#
# WHY THE ENGINE CHANGED (ROADMAP.md M8; DECISIONS.md Amendment 29 §4).
# The graded question here is a CROSS-RESOURCE JOIN: "does THIS Lambda
# permission's SourceArn resolve to an AWS::S3::Bucket declared in THIS
# template?". Rounds 7-9 pushed cfn-guard 3.2.0 as far as it goes -- four
# rules plus five `let` bindings, using variable indirection
# (`Resources.%source_arn_getatt_targets.Type == "AWS::S3::Bucket"`) to
# approximate it. Three things that construction could not do, and this
# file does:
#
#   1. It could not JOIN PER PERMISSION. The `let` bindings collect
#      SourceArn targets across ALL s3-principal'd permissions into one
#      flat set, so with two permissions -- one correctly scoped to the
#      bucket, one pointing at the topic -- the type-check rules see a set
#      containing a bucket and pass. Amendment 29 §4 RULING 2 (cardinality)
#      requires the requirement to be enforced PER RESOURCE. Here the join
#      is quantified per permission logical id (`some lid, _ in
#      s3_invoke_permissions`), so N permissions are N independent checks.
#      PROVEN at round 10 against a synthesized two-permission template:
#      cfn-guard PASS, this policy DENY (see the ROUND-10 verification list
#      at the bottom of this header). Not overclaimed: this one was a
#      tier-1 RULE break, not a reward-level arm-parity break, because
#      tier-0's `lambda-permission-principal-is-s3` uses `op: eq` (exactly
#      one resolved node) and so already rejected any two-permission
#      artifact identically on awscdk and hcl_raw. RULING 2 governs the
#      rule; a future change to that tier-0 assert would have exposed it.
#   2. It could not follow `Fn::Sub`. cfn-guard cannot parse `${Logical.Arn}`
#      out of a Sub template string, so rounds 7-9 accepted ANY Fn::Sub
#      SourceArn as long as it was an intrinsic rather than a literal --
#      recorded as a standing cross-arm strictness residual in the spec's
#      own cfn_guard_hints and in the retired policy.guard's header. Rego
#      has `regex.find_n`, so `sub_tokens` parses those tokens and
#      type-checks what they name. THE RESIDUAL IS CLOSED, not re-recorded:
#      `Fn::Sub: "arn:aws:s3:::some-totally-unrelated-bucket"` now FAILS
#      here exactly as its `references`-less TF spelling fails there.
#   3. It could not recurse. Each accepted shape needed its own `let` +
#      rule pair (GetAtt, Ref, Join-of-Ref, Join-of-GetAtt), so any nesting
#      nobody enumerated -- an Fn::Join inside an Fn::If, a GetAtt inside an
#      Fn::Sub's variable map -- fell through the enumeration. `expr_names`
#      walks the whole SourceArn expression to arbitrary depth.
#
# WHAT THIS FILE GRADES, and what it must NOT grade:
#   * Graded: existence + Type + properties, joined on LOGICAL ID.
#   * NEVER graded: any physical name (Amendment 29 §4 RULING 1). No
#     `BucketName`, no `FunctionName`, no logical id spelled out as a
#     constant. The reference solution's `MediaBucketBCBB02BA` appears
#     nowhere below; an agent may name its constructs anything, and a
#     solution that sets `bucketName` scores identically to one that does
#     not, on every arm.
#   * The one shape rejected symmetrically on all three arms is a SourceArn
#     that references nothing -- a literal ARN string -- including when
#     that literal happens to spell the physical name the same solution
#     gave its own bucket. On the TF-shaped arms such a literal has no
#     `.references` entry; here it names no logical id. Same strictness,
#     which is the property this scenario exists to measure.
#
# THE SNS RULE (ROUND 11, 2026-08-23) -- and the retraction of the claim
# that used to stand here. This header previously read "NO SNS RULE LIVES
# HERE, and that is declared rather than assumed", on the argument that
# `s3n.SnsDestination.bind()` unconditionally calls
# `topic.addToResourcePolicy(...)`, so a hand-authored `CfnTopicPolicy` is
# "redundant, never a replacement" and the defect has no ordinary-use path
# on this arm.
#
# An adversarial verifier DISPROVED the conclusion by execution. Bind the
# topic through a destination that authors no policy of its own -- a
# handful of lines implementing `IBucketNotificationDestination`, the same
# construction this arm's own Lambda-side broken fixtures have used since
# round 7 -- and hand-author an `AWS::SNS::TopicPolicy` granting
# `sns:Publish` to `s3.amazonaws.com` with NO `aws:SourceArn` condition at
# all. That artifact is functionally the exact defect
# `sns-topic-policy-not-scoped-to-bucket` names (any bucket in any account
# may publish to the audit topic), and it scored REWARD 1.0: all seven
# tier-0 asserts passed, `sns-topic-policy-exists-cfn` included, and tier-1
# emitted no deny, because there was no rule to emit one. Meanwhile the
# hcl_raw twin of the same defect scores 0.0. The spec was declaring
# `predicted_tier_caught.awscdk: "1"` for that catch and for
# `inline-sns-topic-policy-not-scoped-to-bucket` the whole time, which was
# false, and `generator/check_tier1_coverage.py` was counting both rows
# toward this arm's tier-1 coverage floor.
#
# So the rule lives here now: `sns-topic-policy-allows-s3-publish-cfn`, the
# CFN mirror of the TF arms' `sns-topic-policy-allows-s3-publish-tf`,
# with the same two clauses graded the same way this file already grades
# the Lambda permission -- per resource (RULING 2), joined on LOGICAL ID
# and the target's Type, never on a physical name (RULING 1). The template
# is static, so both clauses resolve exactly: `Condition.ArnLike."aws:SourceArn"`
# is an `Fn::GetAtt` on the bucket in every artifact the idiomatic API
# produces, and `Topics` is a `Ref` to the topic.
#
# What is still NOT graded here, and why that is not an asymmetry: the TF
# arms' `inline_policy_topics` branch (a `policy` argument set directly on
# `aws_sns_topic`) has no CloudFormation counterpart at all --
# `AWS::SNS::Topic` has no `Policy` property, verified against the CFN
# Template Reference -- so the inline SHAPE cannot be expressed on this arm.
# The inline catch's `applies_to` therefore still excludes awscdk; what
# changed is that its `predicted_tier_caught.awscdk` ("the tier that WOULD
# catch it here", the repo convention for an applies_to-dropped catch) is
# now TRUE, because the equivalent defect expressed in the one shape CFN
# does have is caught, at tier 1, by the rules below.
#
# SCOPE NOTE (unchanged from the retired policy.guard, and consistent with
# this scenario's own tier-0 asserts): notification wiring is read from
# `Custom::S3BucketNotifications`, the resource `bucket.addEventNotification`
# actually synthesizes. A solution hand-rolling `CfnBucket` with a native
# `NotificationConfiguration` property instead already fails tier-0's
# object-created-notification-targets-a-lambda /
# object-removed-notification-targets-a-topic asserts, which read the same
# custom-resource path -- so it never reaches this policy.
#
# ROUND-10 VERIFICATION (executed against real `cdk synth` output, not
# reasoned about):
#   PASS  reference solution/solve.sh (SourceArn = Fn::GetAtt bucket.Arn)
#   PASS  const-hoisted `const arn = bucket.bucketArn` (identical template)
#   PASS  Fn::Sub "arn:${AWS::Partition}:s3:::${MediaBucket}"
#   PASS  Fn::Join composing the bucket ARN from a Ref
#   DENY  broken/lambda-permission-not-scoped-to-bucket (SourceArn absent)
#   DENY  broken/lambda-permission-scoped-to-a-different-bucket (literal ARN)
#   DENY  broken/lambda-permission-scoped-via-an-interpolated-literal (Fn::Sub literal
#         -- the shape cfn-guard passed; the round-10 fixture that falsifies
#         clause 2 above)
#   DENY  broken/second-lambda-permission-scoped-to-the-topic (two permissions,
#         one correct, one pointing at the audit topic -- the shape cfn-guard
#         passed; the round-10 fixture that falsifies clause 1 above)
#   DENY  broken/lambda-permission-scoped-to-the-topic-arn-behind-a-local
#         (the audit topic's ARN reached through a const hoist -- the awscdk
#         half of the round-10 cross-arm pair whose hcl_raw twin scored 1.0
#         until `policy.rego`'s `slot_provenance_conflict` closed it)
#   DENY  broken/no-lambda-permission-at-all (the fail-closed rule, which no
#         fixture on any arm had exercised before round 10)
#   DENY  broken/audit-topic-wired-only-to-lifecycle-expiration
#   DENY  a control template whose SourceArn is Fn::GetAtt on the Lambda's
#         own Arn, and one whose SourceArn is an Fn::Join composing the
#         audit topic's ARN
#

package cdktn_bench.s3_notification_authoritative_singleton

import rego.v1

resources := object.get(input, "Resources", {})

s3_bucket_logical_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::S3::Bucket"
}

# Keyed on LOGICAL ID so every rule below can quantify per resource
# (RULING 2) rather than over a flattened set of properties.
s3_invoke_permissions[lid] := r if {
	some lid, r in resources
	r.Type == "AWS::Lambda::Permission"
	object.get(r, ["Properties", "Principal"], null) == "s3.amazonaws.com"
}

# --- Which logical ids does an intrinsic expression NAME? ------------------
#
# The CFN-side equivalent of the TF arms' `.references` list, except that
# `terraform show -json` hands that list over pre-computed and here it has
# to be read out of the intrinsics. `expr_names` walks an arbitrary
# expression to any depth and returns the set of names it references;
# `node_names` decodes ONE node. A literal string, a number, or an absent
# property yields the empty set -- which is what makes "hardcoded ARN" and
# "no SourceArn at all" fail the same rule, the same way they do on the
# TF-shaped arms.
#
# Pseudo-parameters (AWS::Partition, AWS::Region, ...) come back as names
# too. They are not resources, so they simply never satisfy a Type check --
# no special-casing needed, and none that could be gamed.

# `${Logical}` / `${Logical.Attr}` tokens inside an Fn::Sub template string.
# `${!Literal}` is Fn::Sub's own escape for a literal `${...}` and names
# nothing.
sub_tokens(s) := {name |
	some m in regex.find_n(`\$\{[^}]*\}`, s, -1)
	inner := trim_suffix(trim_prefix(m, "${"), "}")
	not startswith(inner, "!")
	name := split(inner, ".")[0]
}

# In the two-element Fn::Sub form, `${X}` where X is a key of the variable
# map is a local substitution, NOT a logical id. (The map's VALUES are
# ordinary expressions and get walked on their own by `expr_names`, so a
# {"Ref": <bucket>} in there is still counted.)
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

# --- lambda-permission-scoped-to-bucket-cfn (tier-1 structural_assert) -----
#
# The CFN-side mirror of policy.rego's `references_bucket`: for EVERY
# s3.amazonaws.com-principal'd permission, independently, SourceArn must
# resolve to an AWS::S3::Bucket declared in this same template.

source_arn(lid) := object.get(resources[lid], ["Properties", "SourceArn"], null)

# What the SourceArn actually names, annotated with each target's Type, so
# the deny message can quote the artifact instead of asserting a diagnosis
# about it (Amendment 29 §6 RULING 3: a deny message must state something
# the graded artifact really contradicts).
source_arn_targets(lid) := {name: kind |
	some name in expr_names(source_arn(lid))
	kind := object.get(resources, [name, "Type"], "<not a resource in this template>")
}

# ===========================================================================
# ROUND 13 (2026-08-23) -- SAME-TYPE / WRONG-INSTANCE, closed here too so the
# closure is not one-sided.
# ===========================================================================
#
# The TF-shaped arms' policy.rego gained instance discrimination in this same
# pass (it became possible there once the agent's own `.tf` could be parsed
# and a `local.` symbol resolved to a referent). This template already NAMES
# its referent in an `Fn::GetAtt`/`Ref`, so this arm needed no new tooling at
# all -- but it had exactly the same hole, and leaving it open would have
# turned a closed gap into a NEW one-sided cross-arm strictness difference,
# which is the failure class this scenario's whole history is about
# (DECISIONS.md Amendment 29 §4: equal-strictness cross-arm grading is
# binding).
#
# THE HOLE. `scoped_to_a_bucket` and `attached_to_a_topic` were TYPE tests:
# "does SourceArn name an AWS::S3::Bucket in this template", "does Topics
# name an AWS::SNS::Topic". Neither can tell two buckets apart. A permission
# scoped to a decoy bucket the notification does not wire -- so S3 can never
# invoke the function -- passed. So did a topic policy attached to a decoy
# topic, leaving the topic that actually receives the notifications with no
# resource policy at all. Executed on both TF arms and confirmed by
# inspection here; no fixture on any arm exercised it.
#
# THE JOIN. `Custom::S3BucketNotifications` is the L2's own notification
# resource and it names both anchors directly:
#   Properties.BucketName                                     -> the bucket
#   Properties.NotificationConfiguration.TopicConfigurations[*].TopicArn
#                                                             -> the topic
# Keyed on LOGICAL ID -- the CFN analogue of the plan address the TF policy
# uses -- never on a physical name and never on a label this scenario picked
# (Amendment 29 §6 RULING 1).
#
# *** ROUND 14 (2026-08-24) -- RETRACTION AND FIX. This block used to end:
# "DEGRADATION, DECLARED (mirrors policy.rego's): when the notification does
# not name exactly one instance of the relevant type there is nothing to join
# against, and the rule falls back to the type-only test, recording the
# degradation in `not_verifiable` -- never silent. Every artifact that
# reaches that fallback is already denied at tier 0."
#
# THE LAST SENTENCE WAS FALSE, on this arm as on the TF arms. It was proven
# false BY EXECUTION on the hcl_raw twin of this rule -- three artifacts that
# reached the fallback each printed `tier0_pass=1` and scored REWARD 1.0
# while being genuinely broken -- and the tier-0 asserts on THIS arm are the
# same shape (a resource-count check and an event-string whitelist), so
# neither of them looks at what `BucketName` names either. The fallback is
# reachable here whenever `Custom::S3BucketNotifications.Properties.BucketName`
# is a literal bucket name rather than a `Ref`.
#
# AND `not_verifiable` WAS NEVER GATING: the generated static_tiers.sh states,
# in the script itself, that it "does NOT deny the plan and does NOT affect
# tier1_status/reward". Logging the degradation WAS the silent pass.
#
# WHAT REPLACES IT: two POSITIVE routes to the bucket anchor and a DENY when
# neither establishes one, mirroring policy.rego's round-14 shape. Nothing is
# gated on `count(anchors) != 1` any more. ***

bucket_notifications[lid] := r if {
	some lid, r in resources
	r.Type == "Custom::S3BucketNotifications"
}

# ROUTE 1 -- BucketName NAMES a bucket in this template (`Ref`, `Fn::GetAtt`,
# `Fn::Sub`, ...). This is what the CDK L2 always emits.
notification_bucket_ids := route1 | route2 if {
	route1 := {name |
		some lid, _ in bucket_notifications
		some name in expr_names(object.get(resources[lid], ["Properties", "BucketName"], null))
		object.get(resources, [name, "Type"], "") == "AWS::S3::Bucket"
	}

	# ROUTE 2 -- BucketName is a plain literal bucket NAME (which is what the
	# property actually takes) that is the `BucketName` of EXACTLY ONE
	# AWS::S3::Bucket in this same template. A positive identification of one
	# instance, not a widening: `count == 1` is required, and a name matching
	# no bucket in the template matches nothing. The CFN analogue of
	# policy.rego's plan-value route, and it exists for the same reason --
	# refusing an ordinary correct spelling would be a false FAIL.
	route2 := {name |
		some lid, _ in bucket_notifications
		literal := object.get(resources[lid], ["Properties", "BucketName"], null)
		is_string(literal)
		matches := buckets_named(literal)
		count(matches) == 1
		some name in matches
	}
}

buckets_named(bucket_name) := {lid |
	some lid, r in resources
	r.Type == "AWS::S3::Bucket"
	object.get(r, ["Properties", "BucketName"], null) == bucket_name
}

# No ROUTE 2 for the topic half, and the asymmetry is deliberate: a
# `TopicArn` is an ARN, and the ARN of a topic declared in this same template
# is only knowable through an intrinsic, so a literal there identifies
# nothing in the template to join against. Mirrors policy.rego's own
# plan-time-unknown reasoning.
notification_topic_ids := {name |
	some lid, _ in bucket_notifications
	some tc in object.get(
		resources[lid],
		["Properties", "NotificationConfiguration", "TopicConfigurations"],
		[],
	)
	some name in expr_names(object.get(tc, "TopicArn", null))
	object.get(resources, [name, "Type"], "") == "AWS::SNS::Topic"
}

# ONE clause. The `count(anchors) != 1` escape hatch is DELETED, not
# narrowed -- see the retraction above.
names_the_wired_instance(name, anchors) if name in anchors

# --- the anchors are GATING on this arm too -------------------------------

deny contains msg if {
	some lid, _ in bucket_notifications
	count(notification_bucket_ids) != 1
	msg := sprintf(
		"%s: this template's own notification resource does not identify exactly one AWS::S3::Bucket in this template, so WHICH bucket the Lambda permission and the topic policy must be scoped to cannot be established -- and this oracle refuses to fall back to grading them by resource TYPE alone, which cannot tell two buckets apart. `BucketName` is %v; the AWS::S3::Bucket logical ids it identifies are %v (expected exactly 1). Name the bucket with a Ref/Fn::GetAtt, or give a literal BucketName that is the BucketName of exactly one bucket in this template.",
		[lid, object.get(resources[lid], ["Properties", "BucketName"], null), sort([n | some n in notification_bucket_ids])],
	)
}

deny contains msg if {
	some lid, _ in bucket_notifications
	count(notification_topic_ids) != 1
	msg := sprintf(
		"%s: this template's own notification resource does not identify exactly one AWS::SNS::Topic in this template, so WHICH topic the AWS::SNS::TopicPolicy must be attached to cannot be established -- and this oracle refuses to fall back to grading the attachment by resource TYPE alone, which cannot tell two topics apart. Its TopicConfigurations are %v; the AWS::SNS::Topic logical ids they identify are %v (expected exactly 1). A pasted literal topic ARN names nothing in this template -- use a Ref/Fn::GetAtt to the topic.",
		[
			lid,
			object.get(resources[lid], ["Properties", "NotificationConfiguration", "TopicConfigurations"], []),
			sort([n | some n in notification_topic_ids]),
		],
	)
}

scoped_to_a_bucket(lid) if {
	some name, kind in source_arn_targets(lid)
	kind == "AWS::S3::Bucket"
	name != ""

	# ROUND 13: ... and it must be the bucket the notification actually
	# wires, not merely SOME bucket in this template. See the block above.
	names_the_wired_instance(name, notification_bucket_ids)
}

deny contains msg if {
	some lid, _ in s3_invoke_permissions
	not scoped_to_a_bucket(lid)
	msg := sprintf(
		"%s: Principal is s3.amazonaws.com, but nothing ties this grant to the bucket this template's own notification resource wires (%v). Its SourceArn names the following template resources (logical id -> Type): %v -- none of them is that bucket. An absent SourceArn and a hardcoded literal ARN string both name nothing at all (no Ref, Fn::GetAtt, Fn::Join or Fn::Sub token in the value resolves to a logical id); a SourceArn pointing at some other resource names that resource instead -- including another AWS::S3::Bucket in this same template, which is scoped to a bucket that sends no events.",
		[lid, sort([n | some n in notification_bucket_ids]), source_arn_targets(lid)],
	)
}

# Fail-closed companion: a bucket exists but no s3.amazonaws.com-principal'd
# permission exists anywhere in the template at all (mirrors policy.rego's
# own fail-closed rule and toy-ssm-parameter's convention).
deny contains msg if {
	count(s3_bucket_logical_ids) > 0
	count(s3_invoke_permissions) == 0
	msg := "an AWS::S3::Bucket exists, but no AWS::Lambda::Permission with Principal s3.amazonaws.com exists anywhere in this template -- S3 cannot invoke the Lambda function without one"
}

# --- audit-topic-events-cover-a-real-delete (tier-1 structural_assert) -----
#
# Mirrors policy.rego's `fires_for_a_real_delete` exactly: same two accepted
# literals, same union-over-all-wired-topic-events shape, same "only fires
# when a topic notification is wired at all" gating. A topic wired ONLY to
# `s3:LifecycleExpiration:*` (or only to `:DeleteMarkerCreated`, which never
# fires on this unversioned bucket) satisfies tier-0's six-literal `op: in`
# whitelist -- `op: in` can bound which events are allowed but cannot
# require that any particular one is present -- while never firing for an
# ordinary user-initiated delete. Reachable on this arm through ordinary
# use: `s3.EventType.LIFECYCLE_EXPIRATION` is a first-class member of
# aws-cdk-lib's own `EventType` enum, one argument away from
# `EventType.OBJECT_REMOVED` at the same idiomatic call site.
#
# An entirely-missing topic notification is a DIFFERENT, already-caught
# failure (tier-0 sns-topic-exists /
# object-removed-notification-targets-a-topic), so this rule stays silent
# for it rather than issuing a second, vaguer denial.

topic_notification_events := {ev |
	some _, r in resources
	r.Type == "Custom::S3BucketNotifications"
	some tc in object.get(r, ["Properties", "NotificationConfiguration", "TopicConfigurations"], [])
	some ev in object.get(tc, "Events", [])
}

fires_for_a_real_delete if {
	some ev in topic_notification_events
	ev in {"s3:ObjectRemoved:*", "s3:ObjectRemoved:Delete"}
}

deny contains msg if {
	count(topic_notification_events) > 0
	not fires_for_a_real_delete
	msg := sprintf(
		"the topic target's wired notification events are %v -- none of them is s3:ObjectRemoved:* or s3:ObjectRemoved:Delete. This bucket does not enable versioning (so s3:ObjectRemoved:DeleteMarkerCreated alone never fires) and s3:LifecycleExpiration:* fires only for deletes S3's own Lifecycle engine performs, never for a user-initiated one (AWS's own S3 User Guide) -- 'when any object is deleted' is not satisfied by this wiring alone",
		[topic_notification_events],
	)
}

# --- sns-topic-policy-allows-s3-publish-cfn (tier-1 structural_assert) ----
#
# The CFN-side mirror of policy.rego's topic-policy rules, quantified PER
# TOPIC POLICY (RULING 2) exactly as the Lambda rule above is quantified per
# permission.
#
# *** ROUND-16 RETRACTION, of the paragraph that used to stand here and of
# the design it defended. It read: "`expr_names` already walks an arbitrary
# expression to any depth, so both clauses reuse it verbatim: a policy
# document is just an expression, and the bucket reference inside
# `Condition.ArnLike.\"aws:SourceArn\"` is found wherever an author put it --
# no fixed JSON path is assumed, which is the CFN analogue of the TF side's
# deliberate choice to scope by provenance rather than by position."
#
# "Found wherever an author put it" is precisely the defect. A bucket
# reference in a `Sid`, in a `Resource`, in a comment-shaped property, all
# satisfy a walk that assumes no path -- and none of them scopes anything.
# On the TF arms the identical shape was EXECUTED into a REWARD-1.0 launder
# of a checked-in 0.0 fixture by ONE line
# (`Sid = "AllowS3Publish${aws_s3_bucket.media.id}"`); an `Fn::Sub`-ed `Sid`
# does the same here. A fixed path is not a limitation to be apologised for
# when the graded question IS a question about a position. Both arms now
# read `Statement[*].Condition.<op>["aws:SourceArn"]`, and the rules below
# are the CFN half. ***
#
# NOW GRADED, where the retracted text said it deliberately was not: the
# statement's `Effect`, `Principal` and `Action` -- but ONLY to decide WHICH
# statements have to be scoped, never as an independent requirement. That is
# the same use the TF-shaped arms make of them (`_grants_s3_publish` there,
# `_grants_s3_publish` here, written to the same shape on purpose), so this
# does not break parity on a new axis; it is the parity fix. Every predicate
# errs TOWARDS "this statement grants", because that direction can only ADD
# a statement that must be scoped and so cannot hide a grant.
#
# Fail-closed "a topic exists but no policy does" is still tier-0's
# `sns-topic-policy-exists-cfn`; what this file adds at round 16 is the
# stronger per-WIRED-TOPIC coverage (`_wired_topic_has_policy`), which
# tier-0 cannot state because it needs the notification's own topic anchor.
sns_topic_policies[lid] := r if {
	some lid, r in resources
	r.Type == "AWS::SNS::TopicPolicy"
}

# --- ROUND 16: POSITIONAL, PER GRANTING STATEMENT ------------------------
#
# *** THE CROSS-ARM HALF OF THE ROUND-16 LAUNDER. `policy_document_targets`
# ran `expr_names` over the WHOLE `Properties.PolicyDocument` and
# `policy_document_names_a_bucket` accepted if ANY name it found was the
# wired bucket -- the identical no-position acceptance the TF-shaped arms'
# `policy_document_names_the_bucket` had, in CloudFormation spelling. On the
# TF side that shape was EXECUTED into a reward-1.0 launder of a checked-in
# 0.0 fixture by ONE cosmetic line (a bucket reference interpolated into a
# statement's `Sid`); an `Fn::Sub`-ed `Sid` does exactly the same thing
# here. The old header called the position-free walk a deliberate choice --
# "the CFN analogue of the TF side's ... scope by provenance rather than by
# position". Both halves of that choice are RETRACTED, on both arms, in the
# same round: the graded question is a question about a POSITION.
#
# The graded question is now, per STATEMENT of the PolicyDocument:
#
#   for every statement that grants the S3 service principal sns:Publish,
#   does that statement carry a condition on `aws:SourceArn` whose value
#   names the AWS::S3::Bucket this template's own notification wires?
#
# "For every granting statement", so a correctly-scoped statement beside an
# unconditioned one does not launder the unconditioned one.
#
# `expr_names` is still what reads a VALUE (Ref/Fn::GetAtt/Fn::Sub/Fn::Join
# to any depth); what changed is WHICH values it is pointed at. A CFN
# PolicyDocument is real JSON, so unlike the TF `jsonencode(...)` case there
# is nothing to re-parse -- the position was here all along and the rule
# simply was not reading it.

_policy_document(lid) := object.get(resources[lid], ["Properties", "PolicyDocument"], null)

# IAM accepts Statement as one object or a list of them.
_cfn_statements(d) := ss if {
	l := object.get(d, "Statement", [])
	is_array(l)
	ss := {st | some st in l; is_object(st)}
} else := ss if {
	st := object.get(d, "Statement", null)
	is_object(st)
	ss := {st}
} else := set()

_as_list(v) := v if {
	is_array(v)
} else := [v] if {
	is_string(v)
} else := []

_lower(v) := lower(v) if {
	is_string(v)
} else := ""

# Written to err TOWARDS "this statement grants", because a "yes" only ever
# ADDS a statement that must be scoped -- the conservative direction is the
# one that cannot hide a grant. `walk` over `Principal` reaches the leaf
# whatever intrinsic wraps it.
_grants_s3_publish(st) if {
	# `!= "deny"`, not `== "allow"`: an `Effect` this rule cannot read (an
	# intrinsic, a non-string) must count as GRANTING.
	_lower(object.get(st, "Effect", "Allow")) != "deny"
	_principal_covers_s3(st)
	_action_covers_publish(st)
}

_principal_covers_s3(st) if {
	walk(object.get(st, "Principal", null), [_, leaf])
	is_string(leaf)
	_lower(leaf) in {"s3.amazonaws.com", "*"}
}

# *** WRITTEN AS AN EXPLICIT `== null`, NOT `not object.get(...)`, AND THAT
# IS NOT A STYLE CHOICE. `object.get` returns its DEFAULT when the key is
# missing, and `null` is TRUTHY in Rego -- so `not object.get(st, "X", null)`
# is FALSE whether the key is absent or present, and the clause is DEAD CODE.
# Executed: `not object.get({"Action": "..."}, "Principal", null)` is
# undefined, i.e. the guard never fires. This is the SAME defect class as the
# dead `not parse_traversal(x)` guards round 16 fixes in the shared library:
# a guard that reads like a check and is always false. Both spellings below
# were written the dead way first and are corrected here before shipping. ***
_principal_covers_s3(st) if object.get(st, "Principal", null) == null

_action_covers_publish(st) if {
	some a in _as_list(object.get(st, "Action", []))
	_lower(a) in {"sns:publish", "sns:*", "*"}
}

_action_covers_publish(st) if object.get(st, "Action", null) == null

# *** ROUND 17 -- "ERRS TOWARDS 'THIS STATEMENT GRANTS'" NOW COVERS THE
# UNREADABLE CASE ON THIS ARM TOO. `walk` reaches a literal leaf whatever
# intrinsic wraps it, which is why the header above says the direction is
# safe -- but an intrinsic that does not RESOLVE to a literal here
# (`{"Service": {"Ref": "PrincipalParam"}}`, an `Fn::If` between two
# parameters) has no literal leaf to reach, and the statement was DROPPED
# from grading entirely. Beside one correctly-scoped statement that is a
# reward-1.0 launder: an unconditioned `sns:Publish` grant simply vanishes.
# The TF arms' `_principal_covers_s3`/`_action_covers_publish` are rewritten
# the same round to err towards "grants" for an unreadable value, and
# leaving this arm on the old reading would be the cross-arm strictness
# asymmetry in the other direction. A statement carrying an intrinsic under
# `Principal`/`Action` is now GRADED (and must therefore be scoped) rather
# than silently exempted. ***
_principal_covers_s3(st) if _holds_an_unresolved_intrinsic(object.get(st, "Principal", null))

_action_covers_publish(st) if _holds_an_unresolved_intrinsic(object.get(st, "Action", null))

_holds_an_unresolved_intrinsic(v) if {
	walk(v, [_, node])
	is_object(node)
	some k, _ in node
	startswith(k, "Fn::")
}

_holds_an_unresolved_intrinsic(v) if {
	walk(v, [_, node])
	is_object(node)
	object.get(node, "Ref", null) != null
}

# The `aws:SourceArn` condition VALUES of one statement. Operators whose
# name contains "Not" are excluded: `ArnNotLike aws:SourceArn = <this
# bucket>` scopes the grant to every bucket EXCEPT this one, and counting it
# as scoping evidence would be an inversion an adversarial solution could
# write on purpose.
# *** ROUND 17 -- ONE ENTRY PER (operator, condition key) POSITION, CARRYING
# THAT POSITION'S WHOLE VALUE LIST. This used to flatten every value of every
# position into ONE name->Type map and accept on `some` name in it. But IAM
# OR-s the values inside ONE condition position and AND-s distinct positions,
# so
#     "aws:SourceArn": [{"Fn::GetAtt": ["MediaBucket","Arn"]}, "arn:aws:s3:::*"]
# was graded IDENTICALLY to its correctly-scoped twin -- both `deny []`,
# executed -- on a policy that lets any S3 bucket in any account publish. The
# TF arms carried the same defect in the same shape and it is fixed there in
# the same round; keeping the two mirrors in step is the point of having a
# mirror at all.
_statement_source_arn_positions(st) := {[op, k, vals] |
	some op, keys in object.get(st, "Condition", {})
	is_object(keys)
	is_string(op)
	_operator_restricts(op)
	some k, v in keys
	_lower(k) == "aws:sourcearn"
	vals := _cfn_value_list(v)
}

# A condition value is either ONE value (a literal string or an intrinsic
# object) or a LIST of them. An intrinsic is an OBJECT, never an array, so
# `is_array` separates the two cases exactly.
_cfn_value_list(v) := v if {
	is_array(v)
} else := [v]

# THREE FAMILIES OF OPERATOR ARE EXCLUDED -- the TF arms' mirror, same
# reasoning: none of them RESTRICTS the grant to this bucket, and excluding
# one leaves the statement unscoped, which is the loud direction.
#   * "...Not..."     -- scopes the grant to every bucket EXCEPT this one.
#   * "...IfExists"   -- satisfied VACUOUSLY when the request carries no
#                        aws:SourceArn at all.
#   * "ForAllValues:" -- also satisfied vacuously on an absent/empty key.
#                        (`ForAnyValue:` is NOT excluded: it requires a
#                        present value to match.)
_operator_restricts(op) if {
	not contains(op, "Not")
	not contains(op, "IfExists")
	not startswith(op, "ForAllValues:")
}

# The logical ids one VALUE names that are actually RESOURCES of this
# template. Pseudo-parameters (AWS::Partition, AWS::Region, ...) come back
# from `expr_names` too and are dropped here rather than failing the `every`
# below -- `Fn::Sub "arn:${AWS::Partition}:s3:::${MediaBucket}"` is an
# ordinary correct spelling.
_value_resource_names(val) := {n |
	some n in expr_names(val)
	object.get(resources, [n, "Type"], "") != ""
}

# ONE VALUE is scoped iff it names at least one resource and EVERY resource
# it names is the AWS::S3::Bucket this template's own notification wires. A
# literal ARN string, a wildcard, and an omitted value all name no resource
# at all and so fail here rather than being skipped.
_cfn_value_is_scoped(val) if {
	names := _value_resource_names(val)
	count(names) > 0
	every n in names {
		object.get(resources, [n, "Type"], "") == "AWS::S3::Bucket"
		names_the_wired_instance(n, notification_bucket_ids)
	}
}

# ONE POSITION is scoped iff it carries at least one value and EVERY value in
# it is scoped -- `every`, because the values inside one condition position
# are OR-ed.
_cfn_position_is_scoped(pos) if {
	count(pos[2]) > 0
	every val in pos[2] {
		_cfn_value_is_scoped(val)
	}
}

# `some` ACROSS positions -- distinct (operator, condition key) positions are
# AND-ed, so an extra one can only narrow the grant.
_statement_is_scoped(st) if {
	some pos in _statement_source_arn_positions(st)
	_cfn_position_is_scoped(pos)
}

# What each position resolved to, per VALUE, for the deny message (RULING 3).
_statement_source_arn_report(st) := sort([entry |
	some pos in _statement_source_arn_positions(st)
	entry := sprintf("%v %v = value(s) %v", [
		pos[0], pos[1],
		[{n: object.get(resources, [n, "Type"], "<not a resource in this template>") | some n in _value_resource_names(val)} | some val in pos[2]],
	])
])

_granting_statements(lid) := {st |
	some st in _cfn_statements(_policy_document(lid))
	_grants_s3_publish(st)
}

_unscoped_statements(lid) := {st |
	some st in _granting_statements(lid)
	not _statement_is_scoped(st)
}

topics_targets(lid) := {name: kind |
	some name in expr_names(object.get(resources[lid], ["Properties", "Topics"], null))
	kind := object.get(resources, [name, "Type"], "<not a resource in this template>")
}

topic_policy_topic_ids(lid) := {name |
	some name, kind in topics_targets(lid)
	kind == "AWS::SNS::Topic"
}

# --- ROUND 16: GRADE ONLY THE POLICIES ON THE NOTIFICATION PATH ----------
#
# The CFN mirror of the TF arms' `graded_topic_policies`, and it closes the
# same RULING-3 false FAIL for the same reason: a correct solution is
# entitled to declare an unrelated topic (an ops/alarms topic) with its own
# `AWS::SNS::TopicPolicy`, and denying that policy for "not scoping
# sns:Publish to the bucket this template's own notification resource
# wires" is an assertion the artifact refutes. On the TF arms that exact
# artifact was EXECUTED to a false TIER1=FAIL.
graded_topic_policies contains lid if {
	some lid, _ in sns_topic_policies
	some tid in topic_policy_topic_ids(lid)
	tid in notification_topic_ids
}

# The coverage that narrowing gives up, taken from the other direction --
# the CFN mirror of the TF arms' `_wired_topic_has_policy`. Every topic the
# notification wires must have SOME AWS::SNS::TopicPolicy attached to it.
# This is what still catches a policy attached to a DECOY topic, and it says
# something true of the artifact (a topic is uncovered) instead of accusing
# a policy of being misdirected.
#
# *** The per-policy `attached_to_a_topic` DENY is DELETED, not narrowed:
# narrowed to `graded_topic_policies` it would be vacuous by construction,
# denying for non-attachment exactly the policies selected for being
# attached. What each policy IS attached to is folded into the message
# below, so the diagnostic is not lost. ***
_wired_topic_has_policy(tid) if {
	some lid, _ in sns_topic_policies
	tid in topic_policy_topic_ids(lid)
}

deny contains msg if {
	some tid in notification_topic_ids
	not _wired_topic_has_policy(tid)
	msg := sprintf(
		"%s: this template's own AWS::S3::Bucket::NotificationConfiguration wires this AWS::SNS::Topic, but no AWS::SNS::TopicPolicy in this template lists it in `Topics` -- S3 cannot publish to a topic whose resource policy does not grant it sns:Publish, so this notification target is dead. The topics this template's notification wires are %v; what each AWS::SNS::TopicPolicy's `Topics` names (logical id -> Type) is %v. A pasted literal topic ARN, an empty Topics list, and an attachment to some OTHER topic in this same template all read this way.",
		[
			tid,
			sort([n | some n in notification_topic_ids]),
			{lid: topics_targets(lid) | some lid, _ in sns_topic_policies},
		],
	)
}

deny contains msg if {
	some lid in graded_topic_policies
	count(_granting_statements(lid)) == 0
	msg := sprintf(
		"%s: this AWS::SNS::TopicPolicy's PolicyDocument has NO statement granting the s3.amazonaws.com service principal sns:Publish at all, so S3 cannot publish to the topic this template's own notification resource wires. What its PolicyDocument holds is %v.",
		[lid, _policy_document(lid)],
	)
}

deny contains msg if {
	some lid in graded_topic_policies
	count(_granting_statements(lid)) > 0
	count(_unscoped_statements(lid)) > 0
	msg := sprintf(
		"%s: this AWS::SNS::TopicPolicy has %d statement(s) granting the s3.amazonaws.com service principal sns:Publish, and %d of them carry no aws:SourceArn condition EVERY value of which names the bucket this template's own notification resource wires (%v). Read POSITIONALLY and per VALUE -- a bucket reference elsewhere in the document, in a `Sid` or a `Resource`, is not a scoping condition, and neither is a condition position whose value LIST also holds a wildcard or another bucket, because IAM OR-s the values inside one condition position. The unscoped statement(s) are %v, and what each granting statement's aws:SourceArn condition positions name, value by value (logical id -> Type), is %v. An omitted condition names nothing at all, and so does one hardcoded to a literal ARN string (no Ref, Fn::GetAtt, Fn::Join or Fn::Sub token in it resolves to a bucket's logical id); without it, any S3 bucket in any account can publish to this topic.",
		[
			lid,
			count(_granting_statements(lid)),
			count(_unscoped_statements(lid)),
			sort([n | some n in notification_bucket_ids]),
			[st | some st in _unscoped_statements(lid)],
			[_statement_source_arn_report(st) | some st in _granting_statements(lid)],
		],
	)
}

# `not_verifiable` (optional, non-gating; specs/SCHEMA.md §4.2.1) is
# evaluated by the same generated static_tiers.sh block the TF arms use, so
# the rule name is available here too. It stays empty on this arm on
# purpose: `cdk synth` is fully static, so there is no plan-time-unknown
# gap of the kind that rule exists to record -- every fact this policy
# reads is present in the template verbatim. Leaving it empty writes no
# marker.
not_verifiable contains msg if {
	false
	msg := ""
}
