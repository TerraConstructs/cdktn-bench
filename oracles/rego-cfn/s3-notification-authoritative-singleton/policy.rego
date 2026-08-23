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

scoped_to_a_bucket(lid) if {
	some name, kind in source_arn_targets(lid)
	kind == "AWS::S3::Bucket"
	name != ""
}

deny contains msg if {
	some lid, _ in s3_invoke_permissions
	not scoped_to_a_bucket(lid)
	msg := sprintf(
		"%s: Principal is s3.amazonaws.com, but nothing ties this grant to a bucket this template creates. Its SourceArn names the following template resources (logical id -> Type): %v -- none of them is an AWS::S3::Bucket. An absent SourceArn and a hardcoded literal ARN string both name nothing at all (no Ref, Fn::GetAtt, Fn::Join or Fn::Sub token in the value resolves to a logical id); a SourceArn pointing at some other resource names that resource instead.",
		[lid, source_arn_targets(lid)],
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
# The CFN-side mirror of policy.rego's `references_bucket_in_policy` +
# `references_this_topic`, quantified PER TOPIC POLICY (RULING 2) exactly
# as the Lambda rule above is quantified per permission. `expr_names`
# already walks an arbitrary expression to any depth, so both clauses reuse
# it verbatim: a policy document is just an expression, and the bucket
# reference inside `Condition.ArnLike."aws:SourceArn"` is found wherever an
# author put it -- no fixed JSON path is assumed, which is the CFN analogue
# of the TF side's deliberate choice to scope by provenance rather than by
# position (see policy.rego's ROUND-9 block).
#
# NOT graded here, on purpose: the statement's Action/Effect/Principal.
# Tier-0 does not read them either, and the TF-shaped arms' rule does not,
# so grading them here would re-break parity on a new axis. The graded
# question is the same one on all three arms -- does this topic policy tie
# the grant to the bucket THIS artifact creates, and is it attached to the
# topic THIS artifact creates.

# No fail-closed "a topic exists but no policy does" companion is needed on
# this arm (unlike policy.rego, where the equivalent tier-0 assert had to be
# narrowed away because a single jsonpath op cannot OR the two TF resource
# shapes): tier-0's `sns-topic-policy-exists-cfn` already grades exactly
# that, before this policy ever runs.
sns_topic_policies[lid] := r if {
	some lid, r in resources
	r.Type == "AWS::SNS::TopicPolicy"
}

policy_document_targets(lid) := {name: kind |
	some name in expr_names(object.get(resources[lid], ["Properties", "PolicyDocument"], null))
	kind := object.get(resources, [name, "Type"], "<not a resource in this template>")
}

topics_targets(lid) := {name: kind |
	some name in expr_names(object.get(resources[lid], ["Properties", "Topics"], null))
	kind := object.get(resources, [name, "Type"], "<not a resource in this template>")
}

policy_document_names_a_bucket(lid) if {
	some _, kind in policy_document_targets(lid)
	kind == "AWS::S3::Bucket"
}

attached_to_a_topic(lid) if {
	some _, kind in topics_targets(lid)
	kind == "AWS::SNS::Topic"
}

deny contains msg if {
	some lid, _ in sns_topic_policies
	not policy_document_names_a_bucket(lid)
	msg := sprintf(
		"%s: nothing in this AWS::SNS::TopicPolicy's PolicyDocument scopes sns:Publish to a bucket this template creates. Its document names the following template resources (logical id -> Type): %v -- none of them is an AWS::S3::Bucket. An omitted aws:SourceArn condition names nothing at all, and so does one hardcoded to a literal ARN string (no Ref, Fn::GetAtt, Fn::Join or Fn::Sub token in the document resolves to a bucket's logical id); without it, any S3 bucket in any account can publish to this topic.",
		[lid, policy_document_targets(lid)],
	)
}

deny contains msg if {
	some lid, _ in sns_topic_policies
	not attached_to_a_topic(lid)
	msg := sprintf(
		"%s: `Topics` does not attach this AWS::SNS::TopicPolicy to an AWS::SNS::Topic this template creates. It names the following template resources (logical id -> Type): %v -- none of them is an AWS::SNS::Topic. A pasted literal topic ARN, or an empty Topics list, names nothing at all, which leaves the topic that actually receives the notifications with no resource policy and S3 silently dropping every publish.",
		[lid, topics_targets(lid)],
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
