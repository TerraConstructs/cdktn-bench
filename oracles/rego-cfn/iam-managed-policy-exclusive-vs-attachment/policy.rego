# Hand-authored (REPAIR PASS 10, 2026-08-23) -- NOT a generator stub, and
# never overwritten by emit_oracles() once it exists (specs/SCHEMA.md
# §8.2 rule 7).
#
# Scenario:   iam-managed-policy-exclusive-vs-attachment
#             (specs/iam-managed-policy-exclusive-vs-attachment.yaml)
# Intent doc: oracles/iam-managed-policy-exclusive-vs-attachment/intent.md
# Arm:        awscdk, tier "1" (`oracle.awscdk_tier1_engine: rego`,
#             specs/SCHEMA.md §4.5).
#
# `input` at evaluation time is the awscdk arm's SYNTHESIZED CLOUDFORMATION
# TEMPLATE (cdk.out/ScenarioStack.template.json), NOT the `terraform show
# -json` plan JSON that the sibling oracles/rego/iam-managed-policy-
# exclusive-vs-attachment/policy.rego sees. Resources live under
# `input.Resources[<LogicalId>]` with `.Type`/`.Properties`, and every
# cross-resource reference is a `{"Ref": <LogicalId>}` / `{"Fn::GetAtt":
# [<LogicalId>, <attr>]}` object. The generated tests/static_tiers.sh runs
#   opa eval -f raw -I -d policy.rego \
#     'data.cdktn_bench.iam_managed_policy_exclusive_vs_attachment.deny' \
#     < cdk.out/ScenarioStack.template.json
# and fails tier-1 iff `deny` is non-empty -- the same line, the same rule
# name and the same package name every other arm's tier-1 uses.
#
# =====================================================================
# WHY THIS FILE EXISTS AT ALL (it replaces oracles/cfn-guard/iam-managed-
# policy-exclusive-vs-attachment/policy.guard, which is DELETED)
# =====================================================================
# REPAIR PASS 10 (2026-08-23, ninth adversarial-verifier pass). The two
# findings it closes are ONE root cause, recorded by the verifier as two:
#
#   [major] ARM PARITY BREAK ON THE POLICY->ROLE EDGE. cfn-guard 3.2.0 has
#   no cross-collection identity join -- there is no way to state "this
#   AWS::IAM::ManagedPolicy's `Roles` entry references the logical id of
#   THAT AWS::IAM::Role". Every previous repair pass on the awscdk side
#   therefore reached for a PROXY, and each proxy was unsound in BOTH
#   directions, in a scenario whose entire output is a cross-arm
#   comparison:
#     - REPAIR PASS 3's proxy (`%roles { some Properties.
#       ManagedPolicyArns[*] { 'Ref' EXISTS } }` OR'ed at rule level with
#       a policy-side cardinality check) rejected the correct MIXED shape
#       -- the ManagedPolicy naming ONE role through its `roles:` prop
#       while the other role uses `addManagedPolicy()` -- which the
#       byte-identical terraconstructs TypeScript scored 1.0 (defect 16).
#     - REPAIR PASS 9's replacement proxy (`count(roles whose own
#       ManagedPolicyArns carries no Ref at all) == count(every in-template
#       ManagedPolicy's Roles entries)`) fixed that direction by giving up
#       identity entirely: a pure COUNT equality. Its own header comment
#       excused the resulting hole as reachable only by "a contrived
#       template". IT IS NOT CONTRIVED, and this pass PROVED it: attach the
#       team policy to batch-runner from BOTH sides at once (`roles:
#       [batchRunner]` on the policy AND `batchRunner.addManagedPolicy(p)`
#       on the role -- belt-and-braces, an ordinary thing to write) and to
#       report-writer not at all, and the counts balance at 1 == 1.
#       RUN 2026-08-23 against the real bundle it was graded by, cfn-guard
#       3.2.0: `cfn-guard validate` EXIT 0 -- reward 1.0 for a template in
#       which report-writer never receives the team-defined metrics policy
#       the ticket asks for on both roles, while byte-equivalent
#       terraconstructs TypeScript scored 0.0. That template is shipped as
#       `solution/broken/metrics-policy-on-one-role-from-both-sides/` on
#       both arms. The same proxy also credited a role for a `Ref` to ANY
#       Ref-addressable resource in the template, not specifically to the
#       team-defined ManagedPolicy.
#   The TF-shaped arms never had either hole: oracles/rego/.../policy.rego
#   resolves the attachment->policy and attachment->role edges for real.
#   DECISIONS.md Amendment 29 §4 makes equal-strictness cross-arm grading
#   BINDING, and specs/SCHEMA.md §4.5 ("When to select `rego`") names this
#   exact situation as the reason the engine selector exists. So the
#   awscdk tier-1 is now graded by the engine the other two arms use, and
#   `metrics_covered_role_ids` below performs the real logical-id join.
#
#   [major] ORACLE HONESTY / "AT LEAST ONE" WHERE THE PROMPT SAYS BOTH.
#   Already fixed on both sides in REPAIR PASS 7 (policy.guard's rule was
#   renamed `s3_readonly_attached_to_both_roles` and converted to the
#   per-role `%roles { ... }` block form; policy.rego moved to a per-role
#   set difference). This port PRESERVES the per-role quantification --
#   `s3_readonly_covered_role_ids` is differenced against the full role
#   set, exactly like the TF side -- and re-proves it against the
#   `solution/broken/s3-readonly-missing-on-one-role/` fixture rather than
#   inheriting the previous pass's claim (see the verification matrix at
#   the bottom of this header).
#
# =====================================================================
# BINDING RULINGS THIS FILE OBEYS
# =====================================================================
# RULING 1 (identity): no rule here reads `Properties.RoleName`, and none
#   should. Role identity on this arm is existence + type + properties,
#   keyed on the TEMPLATE LOGICAL ID -- the CFN-side twin of the plan
#   ADDRESS the TF-shaped oracle keys on (its BUG 8). A solution that
#   omits `roleName:` and lets CDK compute the physical name is graded
#   IDENTICALLY to one that sets it; that is re-proved, not asserted, by a
#   SHIPPED fixture -- `solution/reference-alt-cdk-no-role-name/`, whose
#   two siblings `reference-alt-tcons-no-role-name/` and
#   `reference-alt-hcl-no-role-name/` are the same authoring decision on
#   the other two arms (1.0 / 1.0 / 1.0, run 2026-08-23). The team-defined
#   policy's own physical name is likewise never read.
# RULING 2 (cardinality): every requirement the ticket states for BOTH
#   roles is enforced PER ROLE, by set difference over role logical ids --
#   never "at least one". That covers the S3-readonly attachment, the
#   team-metrics attachment, and the trust-principal pairing.
# RULING 3 (deny honesty): each message below states only what the graded
#   template actually contradicts. The two coverage messages name the
#   logical ids that are genuinely uncovered (a set difference computed
#   from the template itself), never a bare "not attached" that the
#   artifact could refute.
#
# =====================================================================
# DOCUMENTED, DELIBERATE SCOPE LIMITS (honest gaps, not oversights)
# =====================================================================
# (a) The policy->role edge is resolved through `{"Ref": <LogicalId>}` and
#     `{"Fn::GetAtt": [<LogicalId>, ...]}` ONLY -- never through a literal
#     role NAME string in a ManagedPolicy's `Roles` list. CloudFormation
#     does accept role names there, but every aws-cdk-lib spelling of this
#     ticket (`role.addManagedPolicy(p)`, `new iam.ManagedPolicy(..., {
#     roles: [...] })`, and any mixture) emits a `Ref` -- verified against
#     real `cdk synth` output, aws-cdk-lib 2.263.0, for all three shapes.
#     Reading a name here would mean keying identity on a physical name,
#     which RULING 1 forbids; the unreachable-from-L2 literal-name shape
#     is a recorded gap instead.
# (b) Same narrowing the TF-shaped oracle already records: a single shared
#     INLINE policy (`iam.Policy(..., { roles: [both] })`, an
#     AWS::IAM::Policy resource) is NOT accepted as "the same team-defined
#     managed policy". The ticket asks for a managed policy and
#     `oracle.intent` says so; this file grades AWS::IAM::ManagedPolicy.
# (c) No rule grades the metrics policy's ACTIONS (`cloudwatch:
#     PutMetricData`). Neither does the TF-shaped oracle, deliberately --
#     adding it on one arm only would be exactly the strictness asymmetry
#     this pass exists to remove.
# (d) Role coverage is unioned over EVERY in-template ManagedPolicy, not
#     required of one single policy, mirroring the TF-shaped oracle's own
#     union over every customer `aws_iam_policy` -- so a solution creating
#     a separate team policy per role is accepted on every arm. Full
#     reasoning at `metrics_covered_role_ids` below; it is a shared,
#     deliberate limit, and tightening it on one arm alone is what would
#     be the defect.
#
# =====================================================================
# VERIFICATION MATRIX -- every row RUN, 2026-08-23, real toolchain, not
# inherited from a previous pass's claims. `deny` rows are `opa eval`
# 1.19.0 against real `cdk synth` output (aws-cdk-lib 2.263.0 / aws-cdk
# 2.1135.0); `reward` rows are the full generated tests/static_tiers.sh
# via gates/oracle_falsifiability.py's own sandbox.
# =====================================================================
#   solution/solve.sh (role-side addManagedPolicy, Fn::Join S3 render)
#       -> deny == []                                    PASS  reward 1.0
#   solution/reference-alt-cdk-roles (policy-side `roles: [a, b]`)
#       -> deny == []                                    PASS  reward 1.0
#   solution/reference-alt-cdk-policy-arn (bare-literal S3 ARN render)
#       -> deny == []                                    PASS  reward 1.0
#   solution/reference-alt-cdk-mixed-attachment (the team policy attached
#   to both roles declared from BOTH sides -- one role each side; its
#   cross-arm control is terraconstructs' own
#   reference-alt-tcons-mixed-attachment, which also scores 1.0)
#       -> deny == []                                    PASS  reward 1.0
#   solution/reference-alt-cdk-no-role-name (NEW this pass: solve.sh with
#   BOTH `roleName:` lines deleted -- RULING 1. Its two siblings,
#   reference-alt-hcl-no-role-name and reference-alt-tcons-no-role-name,
#   are the SAME authoring decision on the other two arms and were run in
#   the same session: 1.0 and 1.0)
#       -> deny == []                                    PASS  reward 1.0
#   solution/broken/policy-attached-to-one-role-only
#       -> deny names ReportWriterRole4EB64C04           FAIL  reward 0.0
#   solution/broken/metrics-policy-on-one-role-from-both-sides (NEW this
#   pass -- THE negative that proves cfn-guard's count-equality proxy was
#   unsound in the ACCEPTING direction, and so the reason this arm's
#   tier-1 moved engines. The team policy reaches batch-runner from BOTH
#   sides at once and report-writer not at all, which balances REPAIR
#   PASS 9's rule at 1 == 1. RUN AGAINST THE OLD BUNDLE, 2026-08-23,
#   cfn-guard 3.2.0: `cfn-guard validate` EXIT 0 -- reward 1.0 for a
#   template in which report-writer has no team-metrics access. Its
#   terraconstructs cross-arm control, byte-equivalent TypeScript, scored
#   0.0 the whole time.)
#       -> deny names ReportWriterRole4EB64C04           FAIL  reward 0.0
#   solution/broken/s3-readonly-missing-on-one-role
#       -> deny names ReportWriterRole4EB64C04           FAIL  reward 0.0
#   solution/broken/trust-principals-not-split-across-both-roles
#       -> deny names BatchRunnerRole002E307A            FAIL  reward 0.0
#   solution/broken/single-role-for-both-workloads (NEW this pass -- the
#   covering negative for the role-count rule, which REPAIR PASS 6
#   hand-built and never shipped)
#       -> deny names SharedRoleD1D02F7E + "found 1"     FAIL  reward 0.0
#   solution/broken/no-team-metrics-policy (NEW this pass -- the covering
#   negative for the fail-closed existence rule, which no fixture on any
#   arm had ever exercised)
#       -> deny: no AWS::IAM::ManagedPolicy in template  FAIL  reward 0.0
#   solution/broken/both-roles-trust-ecs-tasks-only (NEW this pass)
#       -> deny: no role trusts lambda.amazonaws.com     FAIL  reward 0.0
#   solution/broken/both-roles-trust-lambda-only (NEW this pass)
#       -> deny: no role trusts ecs-tasks.amazonaws.com  FAIL  reward 0.0
# Every deny rule in this file therefore has at least one shipped
# `solution/broken/` fixture that fires it. An unfalsified rule is
# untested: do not add a rule here without one.
# =====================================================================
#
# Tier-"1" structural_asserts this policy encodes (from the spec):
#   - customer-metrics-policy-attached-to-both-roles-cfn
#     cfn_jsonpath: $.Resources[?(@.Type=='AWS::IAM::ManagedPolicy')].Properties.PolicyDocument
#     op=exists
#     (the cfn_jsonpath documents only the weak "the policy resource
#     exists" half that a flat path CAN express -- the real per-role
#     logical-id join is `metrics_covered_role_ids` below, plus the
#     S3-readonly, role-count and trust-principal facts folded into this
#     same bundle, exactly as the sibling TF-shaped policy.rego folds
#     them into its own.)

package cdktn_bench.iam_managed_policy_exclusive_vs_attachment

import rego.v1

# ---------------------------------------------------------------------
# Template shape helpers.
#
# `object.get(..., default)` everywhere a property may be legitimately
# absent: a template with no Resources at all, a Role with no
# ManagedPolicyArns, a ManagedPolicy with no Roles list. An undefined
# lookup would make the enclosing deny rule silently not fire, which is
# the fail-OPEN direction -- never acceptable in an oracle.
# ---------------------------------------------------------------------
resources := object.get(input, "Resources", {})

iam_role_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::IAM::Role"
}

managed_policy_ids := {lid |
	some lid, r in resources
	r.Type == "AWS::IAM::ManagedPolicy"
}

# Every entry of a role's own ManagedPolicyArns list. CloudFormation's ONE
# managed-policy attachment surface for a role, and inherently additive
# (CFN never removes an attachment it did not itself add) -- which is why
# this arm has no analog of the TF arms' exclusive-ownership catches.
role_managed_policy_arns(rid) := object.get(
	object.get(resources[rid], "Properties", {}),
	"ManagedPolicyArns",
	[],
)

# Every entry of an in-template ManagedPolicy's own Roles list (the
# policy-side attachment shape, aws-cdk-lib's `ManagedPolicyProps.roles`).
managed_policy_role_entries(pid) := object.get(
	object.get(resources[pid], "Properties", {}),
	"Roles",
	[],
)

# THE JOIN cfn-guard could not express (specs/SCHEMA.md §4.5). True iff
# `node` is a CloudFormation reference naming logical id `lid`:
#   {"Ref": "TeamMetricsPolicy87DD074C"}                  -- what
#     `role.addManagedPolicy(p)` emits for a customer ManagedPolicy;
#     AWS::IAM::ManagedPolicy's Ref intrinsic returns the policy ARN, and
#     AWS::IAM::Role's returns the role NAME, which is what a
#     ManagedPolicy's `Roles` list wants -- so `Ref` is the correct and
#     the CDK-emitted spelling on BOTH sides of this edge (verified
#     against real `cdk synth` output for all three attachment shapes).
#   {"Fn::GetAtt": ["TeamMetricsPolicy87DD074C", "PolicyArn"]} and its
#     dotted string form -- accepted because an escape-hatch/L1 solution
#     may legitimately write it; strictly a widening, and it still names
#     a logical id, so it never weakens identity.
# A bare string entry (an imported/AWS-managed ARN) is not a reference to
# anything in this template and correctly matches nothing here.
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

# THE JOIN, per role: the set of AWS::IAM::Role logical ids that some
# in-template AWS::IAM::ManagedPolicy is attached to, as the UNION of the
# two attachment shapes aws-cdk-lib offers. Both are first-class and
# neither is preferred (oracle.intent says so), and because the union is
# taken over BOTH shapes at once, a MIXED solution -- the policy naming
# one role through `roles:` while the other role uses
# `addManagedPolicy()` -- is covered by construction, with no rule-level
# disjunction to fall between (the exact break REPAIR PASS 9's defect 16
# recorded on cfn-guard, and the reason its replacement had to abandon
# identity for a count).
#
# STRICTNESS IS PINNED TO THE TF-SHAPED ORACLE, DELIBERATELY: the union
# runs over EVERY in-template ManagedPolicy, exactly as oracles/rego/
# iam-managed-policy-exclusive-vs-attachment/policy.rego's
# `metrics_covered_via_attachment` unions over every customer-authored
# `aws_iam_policy` in the plan (`attachment_block_targets_customer_policy`
# is satisfied by ANY `some p in customer_policies`). A solution that
# creates a SEPARATE team policy per role is therefore accepted on every
# arm alike. Requiring one single policy to cover both roles here -- which
# the logical-id join could easily express -- would make this arm stricter
# than the other two, which is the very asymmetry Amendment 29 §4 forbids
# and this pass exists to remove. Recorded as a shared, deliberate limit
# rather than closed on one arm.
metrics_covered_role_ids := role_side_covered | policy_side_covered

role_side_covered := {rid |
	some rid in iam_role_ids
	some entry in role_managed_policy_arns(rid)
	some pid in managed_policy_ids
	references_logical_id(entry, pid)
}

policy_side_covered := {rid |
	some rid in iam_role_ids
	some pid in managed_policy_ids
	some entry in managed_policy_role_entries(pid)
	references_logical_id(entry, rid)
}

# ---------------------------------------------------------------------
# AmazonS3ReadOnlyAccess identity, per role.
#
# aws-cdk-lib renders this ONE import in two equally idiomatic ways, and
# `oracle.intent` states explicitly that neither is preferred:
#   fromAwsManagedPolicyName("AmazonS3ReadOnlyAccess") ->
#     {"Fn::Join": ["", ["arn:", {"Ref": "AWS::Partition"},
#                        ":iam::aws:policy/AmazonS3ReadOnlyAccess"]]}
#   fromManagedPolicyArn(..., "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess")
#     -> that bare literal string
# Both were verified against real `cdk synth` output (2.263.0). Rather
# than enumerate renders -- the mistake REPAIR PASS 4 had to repair once
# already, when a third spelling appeared -- this walks the entry and
# accepts it iff ANY string leaf ends with the ARN's own resource
# suffix. That covers the two renders above, an `Fn::Sub`-templated
# partition, and the bare literal, with one rule; the suffix is anchored
# at the END of the leaf, so a different AWS-managed policy (e.g.
# AmazonEC2FullAccess, or an AmazonS3ReadOnlyAccessSomethingElse) can
# never satisfy it. It is the CFN-side twin of the TF oracle's tolerance
# for a `data.aws_partition`-templated ARN.
# ---------------------------------------------------------------------
s3_readonly_arn_suffix := ":iam::aws:policy/AmazonS3ReadOnlyAccess"

entry_is_s3_readonly(entry) if {
	walk(entry, [_, leaf])
	is_string(leaf)
	endswith(leaf, s3_readonly_arn_suffix)
}

s3_readonly_covered_role_ids := {rid |
	some rid in iam_role_ids
	some entry in role_managed_policy_arns(rid)
	entry_is_s3_readonly(entry)
}

# ---------------------------------------------------------------------
# Trust principals, per role.
#
# Byte-for-byte the same semantics as the sibling TF-shaped oracle's
# `ecs_trusting_role_addresses` / `lambda_trusting_role_addresses` /
# `roles_trusting_both_addresses` (which this file's rules mirror onto
# logical ids), deliberately: no arm may grade this fact more strictly
# than another. Both JSON renders of a trust principal are accepted --
# a bare string ("Service": "lambda.amazonaws.com", what
# `iam.ServicePrincipal` synthesizes) and a list. The document itself is
# an OBJECT on this arm (CDK emits structured JSON) but CloudFormation
# also accepts a JSON STRING there, so both are unmarshalled.
# ---------------------------------------------------------------------
trust_document(rid) := doc if {
	raw := object.get(object.get(resources[rid], "Properties", {}), "AssumeRolePolicyDocument", {})
	is_object(raw)
	doc := raw
}

trust_document(rid) := doc if {
	raw := object.get(object.get(resources[rid], "Properties", {}), "AssumeRolePolicyDocument", {})
	is_string(raw)
	doc := json.unmarshal(raw)
}

trust_statement_services(stmt) := services if {
	is_string(stmt.Principal.Service)
	services := {stmt.Principal.Service}
}

trust_statement_services(stmt) := services if {
	is_array(stmt.Principal.Service)
	services := {s | some s in stmt.Principal.Service}
}

role_trust_services[rid] := services if {
	some rid in iam_role_ids
	doc := trust_document(rid)
	services := {s |
		some stmt in object.get(doc, "Statement", [])
		some s in trust_statement_services(stmt)
	}
}

ecs_trusting_role_ids := {rid |
	some rid, services in role_trust_services
	"ecs-tasks.amazonaws.com" in services
}

lambda_trusting_role_ids := {rid |
	some rid, services in role_trust_services
	"lambda.amazonaws.com" in services
}

roles_trusting_both_ids := ecs_trusting_role_ids & lambda_trusting_role_ids

# =====================================================================
# deny rules
# =====================================================================

deny contains msg if {
	count(ecs_trusting_role_ids) == 0
	msg := "this scenario's ticket asks for an IAM role assumed by ECS tasks, but no AWS::IAM::Role in this template has an AssumeRolePolicyDocument naming the ecs-tasks.amazonaws.com service principal"
}

deny contains msg if {
	count(lambda_trusting_role_ids) == 0
	msg := "this scenario's ticket asks for an IAM role assumed by Lambda, but no AWS::IAM::Role in this template has an AssumeRolePolicyDocument naming the lambda.amazonaws.com service principal"
}

deny contains msg if {
	count(roles_trusting_both_ids) > 0
	msg := sprintf(
		"this scenario's ticket asks for TWO separate IAM roles, one assumed by ECS tasks and one assumed by Lambda, but the AssumeRolePolicyDocument of the role(s) with logical id %v names BOTH the ecs-tasks.amazonaws.com and the lambda.amazonaws.com service principal -- so the two trust principals are not split across two distinct roles",
		[sort(roles_trusting_both_ids)],
	)
}

# Role cardinality. A bare COUNT of AWS::IAM::Role resources -- never a
# `Properties.RoleName` match (RULING 1). Identical in kind to the TF
# oracle's `count(iam_role_addresses) != 2`, so omitting the physical
# name scores the same on every arm.
deny contains msg if {
	count(iam_role_ids) != 2
	msg := sprintf(
		"this scenario's ticket asks for two IAM roles (one trusted by ecs-tasks.amazonaws.com, one trusted by lambda.amazonaws.com) -- found %d AWS::IAM::Role resource(s) in the template",
		[count(iam_role_ids)],
	)
}

# Fail-closed companion (the CFN-side twin of the retired policy.guard
# rule `customer_policy_exists_when_roles_present`): the team-defined
# policy must be a real AWS::IAM::ManagedPolicy resource this template
# creates. Guarded on roles being present so an empty/failed template
# reports the role-count fact above rather than a confusing pile.
deny contains msg if {
	count(iam_role_ids) > 0
	count(managed_policy_ids) == 0
	msg := "this scenario's ticket asks for a single team-defined managed policy created in this configuration and attached to both roles, but the template creates no AWS::IAM::ManagedPolicy resource at all"
}

# policy-attached-to-one-role-only catch, PER ROLE (RULING 2), resolved by
# the real logical-id join (`metrics_covered_role_ids`) rather than by any
# count-equality proxy. The set difference is the CFN-side twin of the TF
# oracle's `iam_role_addresses - metrics_covered_role_addresses`, and it
# closes both holes REPAIR PASS 9's cfn-guard rule left open. (1) A role
# is credited only for a reference that names an actual in-template
# AWS::IAM::ManagedPolicy -- not, as `'Ref' EXISTS` did, for a `Ref` to
# anything at all. (2) Two references onto the SAME role credit that one
# role ONCE instead of balancing a count: the shipped
# `solution/broken/metrics-policy-on-one-role-from-both-sides/` fixture
# attaches the team policy to batch-runner from both sides at once and to
# report-writer not at all, which balanced the old proxy at 1 == 1 --
# `cfn-guard validate` EXIT 0, reward 1.0, verified 2026-08-23 against
# the real retired bundle -- and denies here, naming report-writer.
# The message names the uncovered logical ids, computed from the graded
# template itself, so it can never assert something the template
# contradicts (RULING 3).
deny contains msg if {
	count(managed_policy_ids) > 0
	missing := iam_role_ids - metrics_covered_role_ids
	count(missing) > 0
	msg := sprintf(
		"the template does not attach any team-defined AWS::IAM::ManagedPolicy it creates to the AWS::IAM::Role resource(s) with logical id %v -- no entry in their ManagedPolicyArns list references one, and no in-template ManagedPolicy's own Roles list references them",
		[sort(missing)],
	)
}

# s3-readonly-missing-on-one-role catch, PER ROLE (RULING 2). Set
# difference over role logical ids -- the CFN-side twin of the TF
# oracle's `iam_role_addresses - s3_covered_role_addresses`, and never
# the "at least one role" check both oracles used before REPAIR PASS 7.
deny contains msg if {
	missing := iam_role_ids - s3_readonly_covered_role_ids
	count(missing) > 0
	msg := sprintf(
		"this scenario's ticket says BOTH roles need the AWS managed policy AmazonS3ReadOnlyAccess, but no entry in the ManagedPolicyArns list of the AWS::IAM::Role resource(s) with logical id %v renders that ARN",
		[sort(missing)],
	)
}
