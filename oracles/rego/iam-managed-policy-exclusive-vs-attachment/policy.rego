# Hand-authored (Batch A scenario authoring, 2026-08-20; REWRITTEN during a
# second, adversarial-verifier-driven repair pass, 2026-08-21 -- three
# independent bugs found and fixed, each documented at its own site below;
# REWRITTEN AGAIN during a third pass, 2026-08-22, REVERSING one of the
# second pass's own decisions -- see "BUG 5" below; REWRITTEN AGAIN during
# a fourth pass, also 2026-08-22, fixing the POLICY-side mirror of the
# second pass's own role-side for_each fix -- see "BUG 6" below; REWRITTEN
# AGAIN in REPAIR PASS 7, also 2026-08-22, which moved role IDENTITY off
# `values.name` and onto the plan ADDRESS -- see "BUG 8" -- and tightened
# the AmazonS3ReadOnlyAccess coverage rule from "at least one role" to
# per-role -- see "BUG 9"; REWRITTEN AGAIN in REPAIR PASS 8, 2026-08-23,
# adding PATH D -- see "BUG 10"; and AGAIN in REPAIR PASS 9, also
# 2026-08-23, which added PATH E for the cartesian roles-x-policies idiom
# -- see "BUG 11" -- reworded the two coverage deny messages so they stay
# true when the plan itself does not state which role an attachment
# instance covers, and added the PER-ROLE trust-principal rules -- see
# "BUG 12") -- NOT a generator stub. emit_oracles() never overwrites this file once it exists
# (specs/SCHEMA.md §8.2 rule 7).
#
# THIS FILE'S RULES ARE UNCHANGED BY REPAIR PASS 10 (2026-08-23) -- only
# its cross-references are. That pass moved the awscdk arm's tier-1 off
# cfn-guard and onto OPA/Rego (`oracle.awscdk_tier1_engine: rego`,
# specs/SCHEMA.md §4.5), because cfn-guard 3.2.0 cannot express the
# policy->role logical-id join that THIS file has always resolved for
# real, so the awscdk side could only ever approximate it with a proxy
# that was unsound in both directions. The sibling awscdk bundle is now
# ../../rego-cfn/iam-managed-policy-exclusive-vs-attachment/policy.rego;
# oracles/cfn-guard/iam-managed-policy-exclusive-vs-attachment/policy.guard
# is DELETED. Every "sibling cfn-guard oracle" reference below that
# described the CURRENT state was repointed in the same edit; where the
# phrase survives it is deliberately historical (it names what the awscdk
# arm did at the time the bug being described was found).
#
# Scenario:   iam-managed-policy-exclusive-vs-attachment
#             (specs/iam-managed-policy-exclusive-vs-attachment.yaml)
# Intent doc: oracles/iam-managed-policy-exclusive-vs-attachment/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.iam_managed_policy_exclusive_vs_attachment.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Encodes customer-metrics-policy-attached-to-both-roles-tf's tf_jsonpath
# spec AND (as of this rewrite) s3-readonly-policy-attached-tf's identity
# fact too (specs/iam-managed-policy-exclusive-vs-attachment.yaml -- see
# that assert's own note for why the tier-0 form was retired in favor of
# folding it in here): the team-defined CloudWatch-metrics policy created
# in this configuration must be attached to BOTH IAM roles this scenario's
# ticket asks for (the policy-attached-to-one-role-only catch), AND the
# AWS-managed AmazonS3ReadOnlyAccess policy must be attached to BOTH of
# them too (the s3-readonly-missing-on-one-role catch -- this was "at
# least one" until REPAIR PASS 7, see BUG 9 below), via EITHER of the two
# attachment shapes the blueprint calls acceptable (see next paragraph).
#
# BUG 1 FIXED, THEN REVERSED (REPAIR PASS 4 -- see BUG 5 below for the
# reversal's own full evidence; this note is kept, historically accurate,
# for the record): SHAPE-2 TOLERANCE. The ORIGINAL version of this file
# recognized ONLY `aws_iam_role_policy_attachment` (additive) as a valid
# attachment mechanism and unconditionally denied
# `aws_iam_role_policy_attachments_exclusive` (role-scoped exclusive,
# declared as such by its own name) -- CONTRADICTING blueprint
# docs/design/batch-a-greenfield-blueprints.md §2(b) verbatim: "...also
# acceptable, and arguably the most deliberate answer, so **the oracle
# accepts it**". The spec's own header comment had recorded this as a
# deliberate SCOPE-NARROWING deviation, justified by tier-0's flat-grammar
# limits -- but tier-1 (this file) is NOT tier-0: Rego has real
# type-conditional branching, so the justification did not actually reach
# this file, only the *tier-0* asserts. THIS PASS fixed it by adding a
# second attachment family (`exclusive_blocks` below) alongside the
# additive one, unioned before the coverage check. THAT FIX WAS ITSELF
# WRONG (see BUG 5): blueprint §2(b)'s "also acceptable" clause was never
# checked against the SAME blueprint section's own prompt sentence, which
# this resource type violates by design. `exclusive_blocks` and its
# supporting rules are RETAINED below (BUG 5 still needs to detect this
# resource type to REJECT it, not to cover it), but the union into
# `metrics_covered_role_names`/`s3_covered_role_names` this note used to
# describe no longer exists.
#
# BUG 2 FIXED (this rewrite): FOR_EACH / GRAPH-EDGE BLINDNESS. The
# ORIGINAL version resolved "which role does this attachment cover" via
# `expressions.role.references`, matched against each `aws_iam_role`
# resource's own ADDRESS. This is undefined for an entirely ordinary
# `for_each`-over-roles idiom: DEMONSTRATED (2026-08-21) with a real
# `terraform plan` (provider 6.58.0) for
#   resource "aws_iam_role" "this" { for_each = local.roles ... }
#   resource "aws_iam_role_policy_attachment" "metrics" {
#     for_each = aws_iam_role.this
#     role     = each.value.name
#     policy_arn = aws_iam_policy.team_metrics.arn
#   }
# -- `.configuration...aws_iam_role_policy_attachment.metrics.expressions.
# role.references` resolves `["each.value.name", "each.value"]`, NEVER
# `aws_iam_role.this`, so the old `attachment_role_address` rule was
# undefined for every instance and `attached_role_addresses` was empty --
# `deny` fired for BOTH roles despite a fully correct, idiomatically-DRY
# solution. FIXED by abandoning resource-ADDRESS matching for the role
# side entirely and matching on the role's own AWS IDENTITY (its `name`
# value) instead, read from `.planned_values` (always concretely resolved
# by plan time for this ticket's roles, regardless of count/for_each
# indirection on either the role or the attachment resource -- verified
# directly: `aws_iam_role_policy_attachment.metrics["batch_runner"].
# values.role` resolves the literal string `"batch-runner"` even though
# the attachment's own `.configuration...expressions.role.references`
# never names the role resource at all). This is the SAME
# planned_values-over-expressions pattern
# oracles/rego/s3-lambda-log-retention/policy.rego's own header comment
# already documents fixing for a `local`/`for_each`-indirected principal --
# applied here to the role-attachment edge instead of the principal.
# `policy_arn`/`policy_arns`' CUSTOMER-POLICY edge (as opposed to the role
# edge) is still resolved from `.configuration...expressions...references`
# (unaffected by this bug -- a for_each'd ATTACHMENT resource's
# `policy_arn`/`policy_arns` expression is written ONCE per resource BLOCK,
# not per instance, so it is not for_each-indirected the way `role` is in
# the demonstrating example above; SCHEMA.md §4.2.1's plan-time-unknown
# class still applies to it exactly as before).
#
# BUG 3 FIXED (this rewrite): AWSCDK-SIDE PARITY. Not a bug in this file,
# but the sibling awscdk oracle
# (then oracles/cfn-guard/iam-managed-policy-exclusive-vs-attachment/
# policy.guard, since REPAIR PASS 10 ../../rego-cfn/iam-managed-policy-
# exclusive-vs-attachment/policy.rego) had the SAME "which policy, not
# just any policy" blind spot fixed here for the TF arms' S3-identity
# check -- see `entry_is_s3_readonly` / `s3_readonly_covered_role_ids` in
# that file for the awscdk-side half of this same class of fix (it was
# `s3_readonly_attached_to_a_role`, later `s3_readonly_attached_to_both_
# roles`, while that arm was still graded by cfn-guard).
#
# WHY GROUP-BY-ROLE INSTEAD OF A FLAT PATH: tier-0's flat JSONPath+op
# grammar (`contains`/`exists`/`set_eq`) cannot express "for EACH of the
# two role resources, independently, an attachment referencing the
# customer policy exists" -- `contains`/`exists` are satisfied by ANY ONE
# matching node, and `set_eq` collapses duplicate resolved values into a
# set, so "attached once" and "attached to both" resolve identically.
# Rego's set comprehension below groups attachment resources by which
# role they cover -- keyed on that role's plan ADDRESS as of BUG 8, never
# on its physical name -- which is exactly this per-element ("for each
# role") quantification.
#
# Deliberately per-fact deny rules (metrics-coverage, S3-identity), not
# the toy/s3-lambda two-rule (comprehension + fail-closed) convention:
# both outer iterations here are over `iam_role_addresses` -- the
# KNOWN-COMPLETE set of role identities this scenario's own tier-0 asserts
# already require to exist -- so "no customer policy was created at all"
# and "a customer policy exists but covers only one role" both surface
# identically as a non-empty `missing` set from the SAME rule; no separate
# fail-closed rule is needed for the zero-attachments case.
#
# Verified against real `terraform show -json` plan output, both this
# rewrite's own new fixtures and the pre-existing ones (2026-08-21): this
# scenario's own reference solution/solve.sh (shape 1, both roles --
# PASS, deny empty); a hand-written `for_each`-over-roles variant of the
# same shape (PASS, deny empty -- proves BUG 2's fix); the
# policy-attached-to-one-role-only broken fixture, both in its existing
# plain form AND a `for_each` variant (FAIL, metrics-coverage deny
# non-empty in both); a hand-written `aws_iam_role_policy_attachments_
# exclusive`-shaped solution, both policies listed per role (PASS, deny
# empty -- proves BUG 1's fix, matching blueprint §2(b)).
#
# BUG 4 FOUND AND FIXED, REPAIR PASS 3 (2026-08-21, adversarial-verifier
# finding): `role = aws_iam_role.<x>.id` instead of `.name`. `.id` on
# `aws_iam_role` IS the role name (AWS's own IAM API returns the role name
# as the resource's `id`) but it is a PROVIDER-COMPUTED attribute, not a
# config-supplied literal, so Terraform omits it from
# `.planned_values...values.role` ENTIRELY at plan time -- DEMONSTRATED
# against a real `terraform plan` (provider 6.58.0): taking this
# scenario's own reference solve.sh verbatim and substituting `.name` ->
# `.id` on all four `role = ` lines, `aws_iam_role_policy_attachment.
# batch_runner_metrics.values` resolves `null` (every attribute
# unknown-at-plan-time, including `policy_arn` itself since it too
# references a resource attribute) and
# `aws_iam_role_policy_attachment.batch_runner_s3_read.values` resolves
# `{"policy_arn": "arn:...:policy/AmazonS3ReadOnlyAccess"}` with NO
# `role` key at all (a literal `policy_arn` stays known; `role` alone is
# stripped as unknown) -- the OLD `metrics_covered_via_attachment`/
# `s3_covered_via_attachment` (`name := r.values.role`) resolved to
# nothing for either role, both `deny` rules fired, and this fully
# correct, provider-docs-legitimate spelling ("the resource's `id` IS its
# name") scored reward 0.0. THE FIX: a second resolution path (as
# originally written, `attachment_instance_role_name(r)`; BUG 8 in REPAIR
# PASS 7 replaced that rule with `attachment_role_edges_by_reference`,
# which resolves the same edge to the role's ADDRESS instead of its name,
# on the same trigger and by the same route)
# resolves the SAME identity from the other direction when
# `values.role`/`values.role_name` isn't a plan-time-known string -- via
# the REFERENCED `aws_iam_role` resource's own `name` attribute instead
# (always a config-supplied literal for this ticket's roles, hence always
# plan-time-known regardless of which of the role's OWN attributes the
# attachment happened to reference it by), joined through the attachment
# block's `expressions.role`/`role_name` `.references` list -- which DOES
# name the role's address directly for this non-for_each `.id` spelling
# (unlike BUG 2's `each.value.name` idiom, which has no address reference
# at all: `references` there resolves to `["each.value.name",
# "each.value"]`, never `aws_iam_role.<x>`). The two fixes are therefore
# genuinely complementary -- different failure shapes, different resolution
# paths -- not a case of one subsuming the other; BUG 2's own fix/tests are
# unchanged by this one. Verified against real plan JSON, 2026-08-21, in
# both directions: the reference solution unchanged (still resolves via
# `values.role`, PASS, deny empty); the SAME reference solution with all
# four `role =`/`role_name =` lines rewritten to `.id` (PASS, deny empty --
# proves this fix); the policy-attached-to-one-role-only broken fixture,
# ALSO rewritten to the `.id` spelling (FAIL, metrics-coverage deny
# non-empty -- proves this fix does not blunt the catch it must still
# make: a missing attachment resource has no block to resolve a fallback
# address from at all, regardless of spelling). `.id` is documented here,
# not silently accepted-without-note, per this repo's own convention of
# recording every accepted alternative spelling at its own fix site.
#
# BUG 5 FOUND AND FIXED, REPAIR PASS 4 (2026-08-22, adversarial-verifier
# finding): SHAPE-2 TOLERANCE (BUG 1 above) WAS ITSELF WRONG. BUG 1's fix
# unioned `aws_iam_role_policy_attachments_exclusive` into the covering
# sets, reading blueprint §2(b)'s "also acceptable, and arguably the most
# deliberate answer, so the oracle accepts it" clause literally -- without
# checking that acceptance against the SAME blueprint section's own prompt
# sentence, reproduced verbatim in this scenario's own
# `instruction.shared_body`: "Other teams attach their own policies to
# these roles out of band; that must keep working."
# `aws_iam_role_policy_attachments_exclusive` takes exclusive ownership of
# THE ROLE's entire managed-policy set and REMOVES, on the next apply, any
# attachment not listed in its own `policy_arns` -- verified verbatim
# against the provider's own docs, website/docs/r/
# iam_role_policy_attachments_exclusive.html.markdown: "This resource
# takes exclusive ownership over managed IAM policies attached to a role.
# This includes removal of managed IAM policies which are not explicitly
# configured." An out-of-band policy some other team attaches to either
# role is exactly what this resource would remove on the next apply --
# REPRODUCED DIRECTLY, 2026-08-22 (real host sandbox, terraform 1.15.8,
# hashicorp/aws 6.58.0, opa 1.19.0): this scenario's own
# `solution/reference-alt-exclusive/solve.sh` (both roles, both policies,
# via this resource type) scored tier0_pass=1, tier1_status=PASS,
# reward=1.0 under the PRE-BUG-5 policy -- confirming the finding this
# pass fixes.
#
# THE FIX: the union into `metrics_covered_role_names`/
# `s3_covered_role_names` is REMOVED -- `exclusive_blocks` and its
# supporting rules below now exist ONLY to detect the resource type for
# an explicit, accurately-worded deny (`deny` for
# `count(exclusive_blocks) > 0`, below), mirroring how the pre-existing
# account-wide `aws_iam_policy_attachment` rejection works, not to grant
# coverage. `metrics_covered_via_exclusive`/`s3_covered_via_exclusive` and
# their own supporting helpers (`exclusive_block_role_ref_address`,
# `exclusive_instance_role_name`) are DELETED (dead code once the union is
# gone -- BUG 4's `.id`-fallback logic they depended on stays fully intact
# for shape 1, the still-accepted additive resource). The scenario's own
# primary defense against this resource type is a NEW, symmetric tier-0
# assert (`no-role-scoped-exclusive-attachment`, specs/
# iam-managed-policy-exclusive-vs-attachment.yaml); this file's deny rule
# is defense in depth, not the only line of defense, exactly mirroring how
# `aws_iam_policy_attachment` is already covered twice (tier-0
# `no-account-exclusive-policy-attachment` AND -- prior to this same
# resource type ever needing a tier-1 rule of its own, since tier-0 alone
# sufficed for it -- no separate tier-1 check was ever needed there
# either; this file adds one for shape 2 anyway, for messaging accuracy
# under an agent that somehow bypassed tier-0's own check).
# Re-verified against real `terraform show -json` plan output, 2026-08-22:
# the SAME `reference-alt-exclusive` fixture that scored 1.0 above now
# scores tier1_status=FAIL, `deny` non-empty, message naming the specific
# resource type and the out-of-band reason (see the `deny` rule itself,
# below) -- FIXED, and reproduced.
#
# BUG 6 FOUND AND FIXED, REPAIR PASS 5 (2026-08-22, adversarial-verifier
# finding, on the fix REPAIR PASS 2's BUG 2 shipped): FOR_EACH-OVER-
# POLICIES / GRAPH-EDGE BLINDNESS -- the POLICY-side mirror of BUG 2's
# ROLE-side fix, which that pass fixed on one side of the attachment edge
# and left unfixed on the other. `attachment_block_targets_customer_
# policy` resolved the attachment->policy edge ONLY via
# `expressions.policy_arn.references` naming a `customer_policies`
# address directly -- undefined for an ordinary `for_each`-over-a-map-of-
# policy-ARNs idiom (`for_each = local.shared_policy_arns; policy_arn =
# each.value`) or a for_each-over-{role,policy}-pairs idiom (`policy_arn =
# each.value.policy_arn`), both DEMONSTRATED (2026-08-22, real `terraform
# plan`, provider 6.58.0) to plan clean with 4 correct, additive
# attachments (both roles x both policies) yet score tier1 FAIL / reward
# 0.0, with `deny`'s own message FALSELY claiming the policy was "not
# attached" to either role. See `attachment_instance_targets_customer_
# policy`'s own comment, below, for the fix (a plan-time-unknown fallback,
# SCHEMA.md §4.2.1) and its full verification in both directions.
# SCOPE CORRECTION (REPAIR PASS 9, 2026-08-23): BUG 6 fixed only the
# POLICY half of the {role,policy}-pairs idiom's edge. The ROLE half of
# that same idiom -- resolving WHICH role each pair instance covers when
# the role's physical name is provider-computed -- stayed broken until
# PATH E (BUG 11, below). Read this note as "the policy edge", not "that
# idiom".
#
# BUG 7 FOUND AND FIXED, REPAIR PASS 6 (2026-08-22, adversarial-verifier
# finding): TWO-ROLES-EXIST WAS UNBACKED. `oracle.intent`'s own opening
# sentence (specs/iam-managed-policy-exclusive-vs-attachment.yaml) says
# "Two IAM roles exist: one whose trust policy permits
# ecs-tasks.amazonaws.com to assume it, and one whose trust policy permits
# lambda.amazonaws.com" -- but neither this file nor any tier-0 assert
# constrained how many `aws_iam_role` resources the plan creates.
# `role-trusts-ecs-tasks-service` / `role-trusts-lambda-service` (tier 0)
# are both `contains` over the flattened union of ALL roles' trust-policy
# principals, so a SINGLE role whose `assume_role_policy` lists
# `Principal.Service = ["ecs-tasks.amazonaws.com",
# "lambda.amazonaws.com"]` satisfies both independently. REPRODUCED
# DIRECTLY, 2026-08-22 (real host sandbox, terraform 1.15.8 + hashicorp/aws
# 6.58.0, opa 1.19.0): one `aws_iam_role "shared" { name = "batch-shared" }`
# with that composite trust policy, plus one `aws_iam_policy` and two
# additive `aws_iam_role_policy_attachment` resources (S3-readonly and
# team-metrics, both on the single role) -- under the PRE-BUG-7 policy,
# `deny` was empty, reward 1.0, despite the plan containing exactly ONE
# IAM role, not two. Also an undocumented deviation from blueprint §2(c),
# whose tier-0 plan explicitly listed a `two-roles-exist` assert.
#
# THE FIX: a new deny rule below, firing when the role count is not 2
# (`count(iam_role_names) != 2` as written in this pass; re-keyed to
# `count(iam_role_addresses) != 2` by BUG 8 in REPAIR PASS 7, which is
# what made the "no specific role name is graded" claim below actually
# TRUE of this file rather than only of the sibling cfn-guard oracle).
# No valid solution to this ticket has a role count other than 2
# (re-verified against every reference/reference-alt fixture after this
# change -- all still PASS, deny empty). Deliberately a bare COUNT check,
# not a name-based `set_eq` on `{"batch-runner", "report-writer"}`: no
# specific role name is graded anywhere else in this scenario, and nothing
# in the ticket requires those exact strings -- only two roles with two
# distinct trust principals -- so asserting the literal names would reject
# a legitimate renaming a count check does not. Re-verified against the
# single-shared-role negative above (2026-08-22): `deny` now fires,
# `"this scenario's ticket asks for two IAM roles ... found 1"`.
#
# BUG 10 FOUND AND FIXED, REPAIR PASS 8 (2026-08-23, seventh
# adversarial-verifier pass): the hcl_raw-only REMAINDER of BUG 8's
# arm-parity break. BUG 8's reference fallback reduced every
# `.references` entry to its resource-BLOCK address so it could be looked
# up in a block-keyed map, then required either a single-instance role
# block (PATH B) or a matching `["key"]` suffix on the ATTACHMENT address
# (PATH C). Neither holds for `for_each = local.roles` roles attached by
# PLAIN, non-iterated attachment blocks writing `role =
# aws_iam_role.this["batch_runner"].name` -- the commonest hand-written
# spelling -- so that solution scored 1.0 with `name =` and 0.0 with
# `name_prefix =`, one attribute apart, while the same authoring decision
# scored 1.0 on BOTH awscdk and terraconstructs. Fixed by PATH D; full
# evidence at the PATH A-D note below.
#
# BUG 8 / BUG 9 (REPAIR PASS 7, 2026-08-22) are documented at their own
# fix sites below: `iam_role_addresses` (role identity moved off
# `values.name` onto the plan ADDRESS -- the arm-parity break this bare
# count check silently depended on), and the AmazonS3ReadOnlyAccess deny
# rule (tightened from "at least one role" to per-role).

package cdktn_bench.iam_managed_policy_exclusive_vs_attachment

import rego.v1

configured_resources := input.configuration.root_module.resources

planned_resources := input.planned_values.root_module.resources

s3_readonly_arn := "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"

# ---------------------------------------------------------------------
# BUG 8 FOUND AND FIXED, REPAIR PASS 7 (2026-08-22, adversarial-verifier
# finding -- ARM-PARITY BREAK): role IDENTITY is now the plan ADDRESS of
# each planned `aws_iam_role` instance, never its physical `values.name`.
#
# What was wrong: this set used to be built from `r.values.name`
# exclusively. A solution that does not set a physical role name -- which
# is the DEFAULT shape on the terraconstructs arm (terraconstructs 0.2.13
# lib/aws/iam/role.js:220-221 emits `name: props.roleName, namePrefix:
# !props.roleName ? namePrefix : undefined`, so omitting `roleName` yields
# a provider-computed name) and an ordinary `name_prefix` spelling on
# hcl_raw -- has `.planned_values...aws_iam_role.values.name == null`,
# which collapsed this set to empty and fired BOTH the role-count deny and
# the S3-coverage deny with messages the graded plan flatly contradicted.
# REPRODUCED, 2026-08-22, three arms, ONE authoring decision (this
# scenario's own solve.sh with the two `roleName:` lines deleted, real
# toolchain): awscdk reward 1.0 (cfn-guard's `two_roles_exist` is a bare
# resource count with no name dependency), terraconstructs reward 0.0,
# hcl_raw (`name` -> `name_prefix`) reward 0.0 -- with `deny` claiming
# "found 0" roles and "no role has ... AmazonS3ReadOnlyAccess attached"
# for a plan containing exactly two `aws_iam_role` resources and two
# attachments whose `values.policy_arn` IS that literal ARN.
#
# THE FIX (binding operator ruling, 2026-08-22): physical resource NAMES
# are never load-bearing in this oracle. Role identity is graded by
# EXISTENCE + TYPE + PROPERTIES keyed on the plan ADDRESS, the same
# strictness the cfn-guard arm already used (`two_roles_exist {
# %roles_count == 2 }`, a pure resource count). A role's `values.name`
# survives only as a JOIN KEY for resolving which role an attachment
# instance covers when that name happens to be plan-time-known -- never as
# a graded value, and never as the identity itself. Every deny message
# below now names plan ADDRESSES, which are always present in the
# artifact being graded.
#
# The KNOWN-COMPLETE set of role identities this scenario creates: one
# entry per planned `aws_iam_role` INSTANCE address (instance-qualified,
# so a `for_each`/`count` role block still contributes one identity per
# instance -- deliberately NOT collapsed with base_address()).
iam_role_addresses := {r.address |
	some r in planned_resources
	r.type == "aws_iam_role"
}

# Every planned resource, keyed by its (unique) instance address -- lets
# the coverage sets below look an attachment instance back up from an edge
# without a second nested walk.
planned_by_address := {r.address: r |
	some r in planned_resources
}

customer_policies := [r |
	some r in configured_resources
	r.type == "aws_iam_policy"
]

# True when `refs` (an expressions.<attr>.references list) names `addr`,
# either as the bare resource address ("aws_iam_policy.team_metrics") or
# an attribute-qualified form ("aws_iam_policy.team_metrics.arn") -- both
# shapes occur in real `terraform show -json` output, see this file's own
# header comment.
references_resource(refs, addr) if {
	some ref in refs
	ref == addr
}

references_resource(refs, addr) if {
	some ref in refs
	startswith(ref, sprintf("%s.", [addr]))
}

# A for_each/count resource's `.configuration...address` is the BASE
# resource-block address (no `["key"]`/`[N]` instance suffix -- one
# `expressions` entry is shared by every instance); a `.planned_values...
# address` is always the fully INSTANCE-qualified address. This strips a
# planned instance address back down to its configuration-block address
# for that join. Safe because this scenario's prompt requires
# hand-written HCL with no modules (SCHEMA.md's `hcl_raw` `language_line`
# for this spec) -- no module-path segment can itself contain `[`.
base_address(addr) := split(addr, "[")[0]

# ---------------------------------------------------------------------
# BUG 4's role-identity fallback (REPAIR PASS 3), re-keyed onto ADDRESSES
# by BUG 8 (REPAIR PASS 7): the map from a role resource BLOCK address
# (`aws_iam_role.batch_runner`) to the set of planned INSTANCE addresses
# that block produced (exactly one for an ordinary block; one per key for
# a `for_each`/`count` block), plus a helper to strip a `.references`
# entry down to its bare resource address whether the entry itself was
# already bare ("aws_iam_role.batch_runner") or attribute-qualified
# ("aws_iam_role.batch_runner.id"/".name"/".arn") -- all three shapes
# occur in real `terraform show -json` output. Safe under the same
# no-modules assumption base_address(...) above already documents (no
# module-path segment can itself contain ".").
# ---------------------------------------------------------------------
role_addresses_by_block[block_addr] := addrs if {
	some r in planned_resources
	r.type == "aws_iam_role"
	block_addr := base_address(r.address)
	addrs := {r2.address |
		some r2 in planned_resources
		r2.type == "aws_iam_role"
		base_address(r2.address) == block_addr
	}
}

resource_address_prefix(ref) := concat(".", array.slice(split(ref, "."), 0, 2))

# The `["key"]`/`[N]` instance suffix of a planned address, or undefined
# when the address has none (an ordinary, un-iterated resource).
instance_index_suffix(addr) := sprintf("[%s", [split(addr, "[")[1]])

# ---------------------------------------------------------------------
# Shape 1: aws_iam_role_policy_attachment (additive -- the reference
# shape).
# ---------------------------------------------------------------------
attachment_blocks := [r |
	some r in configured_resources
	r.type == "aws_iam_role_policy_attachment"
]

attachment_blocks_by_address := {block.address: block |
	some block in attachment_blocks
}

attachment_block_targets_customer_policy(block) if {
	some p in customer_policies
	references_resource(object.get(block.expressions.policy_arn, "references", []), p.address)
}

# BUG 6's plan-time-unknown fallback (below) needs to know, per PLANNED
# INSTANCE, whether `policy_arn` itself resolved to a known string --
# `is_object` guards against `r.values` being JSON `null` outright (every
# attribute unknown, BUG 4's `.id`-role case), and an ordinary missing-key
# lookup safely fails closed (not an error) when `policy_arn` alone was
# stripped as unknown.
attachment_instance_policy_arn_known(r) if {
	is_object(r.values)
	is_string(r.values.policy_arn)
}

# The set of aws_iam_role BLOCK addresses an attachment block names, from
# either of the two places a `.configuration` entry can name one:
#
#   * `expressions.role.references` -- `role = aws_iam_role.x.name` /
#     `.id` / `aws_iam_role.this[each.key].name`. (BUG 4's original
#     fallback used only this one.)
#   * `for_each_expression.references` -- `for_each = aws_iam_role.this`,
#     the idiom whose `role = each.value.name` expression names only the
#     iteration variable and never the role resource (BUG 2's shape).
#     Added by BUG 8 (REPAIR PASS 7): BUG 2 could resolve that idiom
#     through `values.role` alone, because the role's `name` was a config
#     literal; once the role's physical name is provider-computed
#     (`name_prefix`, or terraconstructs' `roleName`-omitted default)
#     `values.role` is unknown and the for_each expression is the ONLY
#     remaining place the plan states which roles those instances belong
#     to. Verified against a real `terraform plan` (1.15.8 / aws 6.58.0)
#     for `for_each = local.roles` roles with `name_prefix` +
#     `for_each = aws_iam_role.this` attachments: `.configuration...
#     aws_iam_role_policy_attachment.s3_read.for_each_expression.
#     references == ["aws_iam_role.this"]`.
#
# Empty (contributing no edge, never a wrong one) when neither names a
# role resource.
attachment_block_referenced_role_blocks(block) := addrs if {
	addrs := {addr |
		some refs in [
			object.get(block, ["expressions", "role", "references"], []),
			object.get(block, ["for_each_expression", "references"], []),
		]
		some ref in refs
		startswith(ref, "aws_iam_role.")
		addr := resource_address_prefix(ref)
	}
}

# ---------------------------------------------------------------------
# BUG 10's helper (REPAIR PASS 8, 2026-08-23): the set of planned role
# INSTANCE addresses an attachment block names DIRECTLY.
#
# `attachment_block_referenced_role_blocks` above deliberately strips a
# reference down to its resource-BLOCK address, because that is the key
# `role_addresses_by_block` is built on. But a `.references` entry for a
# for_each'd role is INSTANCE-qualified -- a real `terraform show -json`
# (1.15.8 / aws 6.58.0) for `role = aws_iam_role.this["batch_runner"].name`
# carries, verbatim:
#
#   ["aws_iam_role.this[\"batch_runner\"].name",
#    "aws_iam_role.this[\"batch_runner\"]",
#    "aws_iam_role.this"]
#
# -- so the plan states, unambiguously and by itself, exactly which role
# INSTANCE that attachment covers. This rule reads that statement at face
# value: any entry that IS (or is an attribute of) a planned
# `aws_iam_role` instance address contributes that address. Membership is
# tested with `references_resource` (exact match, or the entry being that
# address plus a `.<attr>` suffix) rather than by string-slicing, so a
# map key containing a "." cannot mis-parse.
#
# Cannot over-credit: the reference names ONE planned role instance, so a
# for_each role block whose attachments each name a single key still gets
# exactly one edge per attachment (unlike a base-address widening, which
# would credit one attachment to every instance of the block and silence
# the policy-attached-to-one-role-only catch). Empty -- contributing no
# edge, never a wrong one -- when no entry names a planned role instance,
# which is the case for the `for_each = aws_iam_role.this` idiom (whose
# only entry is the BASE address) that PATH C already handles.
attachment_block_referenced_role_instances(block) := addrs if {
	refs := array.concat(
		object.get(block, ["expressions", "role", "references"], []),
		object.get(block, ["for_each_expression", "references"], []),
	)
	addrs := {addr |
		some addr in iam_role_addresses
		references_resource(refs, addr)
	}
}

# ---------------------------------------------------------------------
# ATTACHMENT -> ROLE EDGES (BUG 8's address-keyed rewrite, REPAIR PASS 7).
#
# One edge per (planned attachment instance address, planned role instance
# address) pair. The RESULT identity is always a plan ADDRESS -- a role's
# physical `name` is used only as a JOIN KEY on the path where it happens
# to be plan-time-known, never as the graded identity (see BUG 8's note at
# `iam_role_addresses` above, and the binding operator ruling it cites).
#
# PATH A (name join, the ordinary case): the instance's own `values.role`
# resolved to a plan-time-known string -- covers the reference solution's
# `role = aws_iam_role.batch_runner.name` spelling, every `for_each`
# idiom (`role = each.value.name`, whose `.configuration` expression never
# names the role resource at all -- BUG 2), and any literal spelling.
# Joined against the planned role whose own `values.name` equals it.
#
# PATH B (reference join, single-instance role block): `values.role` did
# not resolve to a planned role by name -- either it is unknown at plan
# time (the role's physical name is provider-computed: `name_prefix`, or
# terraconstructs' own `roleName`-omitted default -- BUG 8) or `r.values`
# is `null` outright (every attribute unknown, BUG 4's `.id` case) -- so
# resolve the edge from the attachment BLOCK's own
# `expressions.role.references` instead, which names the role resource's
# BLOCK address. Used only when that block produced exactly one planned
# instance, so the edge is unambiguous.
#
# PATH C (reference join, indexed role block): same as B for a
# `for_each`/`count` role block, disambiguated by requiring the attachment
# instance's own `["key"]`/`[N]` suffix to match the role instance's --
# without this, B's one-instance guard would leave a correct
# for_each-roles + provider-computed-name solution with no edges at all.
# DEMONSTRATED, 2026-08-22, real `terraform plan` (1.15.8 / aws 6.58.0):
# `for_each = local.roles` roles carrying `name_prefix` (no literal
# `name`), attached by `for_each = aws_iam_role.this` /
# `role = each.value.name` -- a fully correct, additive, idiomatically-DRY
# solution -- had NO resolvable name join (every `values.role` unknown)
# and no per-instance reference either; with PATH C plus the
# `for_each_expression` half of `attachment_block_referenced_role_blocks`
# it now resolves both roles by matching instance keys, `deny` empty,
# reward 1.0.
#
# PATH D (reference join, instance-qualified reference) -- BUG 10 FOUND
# AND FIXED, REPAIR PASS 8 (2026-08-23, adversarial-verifier finding --
# ARM-PARITY BREAK, the residue B and C did not cover). B keys on the
# attachment block's reference resolving to a role BLOCK that produced
# exactly ONE instance; C keys on the attachment instance carrying its
# own `["key"]`/`[N]` suffix. Neither fires for the most obvious
# hand-written HCL spelling of a for_each'd role set: two roles from
# `for_each = local.roles`, attached by four ORDINARY (non-iterated)
# attachment blocks, each spelling `role =
# aws_iam_role.this["batch_runner"].name`. There, the role block has TWO
# instances (B's guard fails) and the attachment address has no index
# suffix at all (`instance_index_suffix` is undefined, C fails) -- yet the
# plan names the covered role instance outright in
# `expressions.role.references`. REPRODUCED, 2026-08-23, real toolchain
# (terraform 1.15.8 / hashicorp-aws 6.58.0 / opa 1.19.0), that exact
# config, one attribute changed between the two runs: with `name =
# replace(each.key, "_", "-")` reward 1.0 (PATH A resolved); with
# `name_prefix = "${replace(each.key, "_", "-")}-"` reward 0.0, BOTH deny
# messages naming both role addresses as uncovered while the graded plan
# contained `aws_iam_role_policy_attachment.runner_s3` /`.writer_s3` with
# `policy_arn = "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"` and
# `.runner_metrics`/`.writer_metrics` pointing at the customer policy. The
# same authoring decision (DRY loop over a role map, no physical role
# name) scored 1.0 on BOTH awscdk and terraconstructs, so this was an
# hcl_raw-only penalty for omitting a physical name -- exactly what the
# operator ruling of 2026-08-22 forbids.
#
# THE FIX: read the instance-qualified reference the plan already carries
# (see `attachment_block_referenced_role_instances` above) and emit the
# edge directly -- no `role_addresses_by_block` lookup, no instance-suffix
# matching. Unambiguous by construction: the reference names exactly one
# planned role instance.
#
# B, C and D are all gated on A having produced nothing for that instance,
# so a resolvable name join is never widened by a block-level reference
# (which, for a `for_each` role block, would otherwise credit ONE
# attachment to EVERY instance of that block and silence the
# policy-attached-to-one-role-only catch). D cannot widen that way either:
# it only ever emits the single instance the reference itself names --
# re-verified 2026-08-23 against for_each roles + `name_prefix` with the
# team-metrics attachment written for ONE key only, where `deny` still
# fires and names exactly `aws_iam_role.this["report_writer"]`.
# ---------------------------------------------------------------------
attachment_role_edges_by_name contains edge if {
	some r in planned_resources
	r.type == "aws_iam_role_policy_attachment"
	is_object(r.values)
	is_string(r.values.role)
	some role in planned_resources
	role.type == "aws_iam_role"
	role.values.name == r.values.role
	edge := {"instance": r.address, "role_address": role.address}
}

attachment_instance_has_name_edge(r) if {
	some e in attachment_role_edges_by_name
	e.instance == r.address
}

attachment_role_edges_by_reference contains edge if {
	some r in planned_resources
	r.type == "aws_iam_role_policy_attachment"
	not attachment_instance_has_name_edge(r)
	block := attachment_blocks_by_address[base_address(r.address)]
	some block_addr in attachment_block_referenced_role_blocks(block)
	role_addrs := role_addresses_by_block[block_addr]
	count(role_addrs) == 1
	some role_address in role_addrs
	edge := {"instance": r.address, "role_address": role_address}
}

attachment_role_edges_by_reference contains edge if {
	some r in planned_resources
	r.type == "aws_iam_role_policy_attachment"
	not attachment_instance_has_name_edge(r)
	block := attachment_blocks_by_address[base_address(r.address)]
	some block_addr in attachment_block_referenced_role_blocks(block)
	role_address := concat("", [block_addr, instance_index_suffix(r.address)])
	role_address in role_addresses_by_block[block_addr]
	edge := {"instance": r.address, "role_address": role_address}
}

attachment_role_edges_by_reference contains edge if {
	some r in planned_resources
	r.type == "aws_iam_role_policy_attachment"
	not attachment_instance_has_name_edge(r)
	block := attachment_blocks_by_address[base_address(r.address)]
	some role_address in attachment_block_referenced_role_instances(block)
	edge := {"instance": r.address, "role_address": role_address}
}

attachment_role_edges := attachment_role_edges_by_name | attachment_role_edges_by_reference

# ---------------------------------------------------------------------
# PATH E (CARDINALITY-MATCHED BLOCK COVERAGE) -- BUG 11 FOUND AND FIXED,
# REPAIR PASS 9 (2026-08-23, adversarial-verifier finding -- ARM-PARITY
# BREAK, the residue B, C and D still did not cover).
#
# THE SHAPE: the fully-DRY "cartesian product of roles x policies" idiom.
# One `for_each`ed role block, one `for_each`ed attachment block whose
# keyspace is the SETPRODUCT of role keys and policy keys, and a
# DYNAMICALLY indexed role reference:
#
#   resource "aws_iam_role" "this" { for_each = local.roles
#                                    name_prefix = ... }
#   locals { pairs = { for pair in setproduct(keys(local.roles),
#                                             keys(local.policy_arns)) :
#            "${pair[0]}:${pair[1]}" => { role_key = pair[0]
#                                         policy_key = pair[1] } } }
#   resource "aws_iam_role_policy_attachment" "this" {
#     for_each   = local.pairs
#     role       = aws_iam_role.this[each.value.role_key].name
#     policy_arn = local.policy_arns[each.value.policy_key]
#   }
#
# Every one of PATHS A-D misses it, and the reason is the same in each
# case -- the plan simply does not state, per instance, which role that
# instance covers:
#   * A: the role's physical name is provider-computed (`name_prefix`),
#     so every `values.role` is unknown -- no name join exists.
#   * B: the role block produced TWO instances, so B's one-instance guard
#     (which exists to stop a block-level reference from crediting one
#     attachment to every instance of the block) fails.
#   * C: the attachment instance's own index suffix is the PAIR key
#     (`["batch_runner:s3_read"]`), which is not a key of the role block
#     at all -- the two keyspaces deliberately differ in this idiom.
#   * D: `.configuration...aws_iam_role_policy_attachment.this.
#     expressions.role.references` collapses a dynamically indexed
#     reference to `["aws_iam_role.this", "each.value.role_key",
#     "each.value"]` -- the BASE block address only, never an instance.
#
# REPRODUCED, 2026-08-23, real toolchain (terraform 1.15.8 /
# hashicorp-aws 6.58.0 / opa 1.19.0), that exact config, ONE attribute
# changed between two runs: `name = replace(each.key, "_", "-")` scored
# reward 1.0 (PATH A resolved); `name_prefix = "${replace(each.key, "_",
# "-")}-"` scored reward 0.0, with BOTH deny messages naming both role
# addresses as uncovered while the graded plan contained
# `aws_iam_role_policy_attachment.this["batch_runner:s3_read"]` and
# `.this["report_writer:s3_read"]` each with `values.policy_arn ==
# "arn:aws:iam::aws:policy/AmazonS3ReadOnlyAccess"` plus
# `.this["batch_runner:metrics"]` / `.this["report_writer:metrics"]`
# (values `{}` -- `policy_arn` plan-time-unknown, i.e. the customer
# policy). The SAME authoring decision (loop over a role map, no physical
# role name) scored 1.0 on BOTH awscdk and terraconstructs, so this was
# once again an hcl_raw-only penalty for omitting a physical name --
# exactly what binding operator ruling 1 (2026-08-22) forbids.
#
# THE FIX, and why it cannot over-credit: when an attachment BLOCK has no
# per-instance edge from A-D at all, and its `.references` name a role
# BLOCK that produced N > 1 instances, group that attachment block's own
# planned instances by RESOLVED POLICY IDENTITY. If exactly N of them
# carry a given policy identity, that block attaches that policy once per
# role instance -- the only assignment of N indistinguishable attachment
# instances onto N role instances an `aws_iam_role_policy_attachment`
# plan admits, since AWS keys an attachment on (role, policy) and two
# instances of one block cannot share a key. Credit all N role instances
# for THAT policy identity only; a policy identity carried by fewer than
# N instances credits nobody, which is precisely how the
# one-role-only negatives keep failing (1 metrics instance vs 2 role
# instances -- see the `metrics-on-one-role-only-cartesian` broken
# fixture, whose deny still fires).
#
# DELIBERATE, DOCUMENTED IDEALIZATION (this one is now TF-arm-only: the
# awscdk side's own cardinality idealizations went away with cfn-guard in
# REPAIR PASS 10, whose Rego bundle resolves that arm's edge by logical id
# and counts nothing): a contrived block that attached the SAME policy identity to
# the SAME role instance N times would also reach a group size of N. That
# shape is not a plan any ordinary solution to this ticket produces, and
# it would collide on (role, policy) at apply time; it is accepted here
# rather than adding a resolution the plan JSON cannot actually support.
# ---------------------------------------------------------------------
attachment_block_has_any_edge(block) if {
	some e in attachment_role_edges
	base_address(e.instance) == block.address
}

# The planned instances of one attachment block that carry the customer
# policy / the AWS-managed S3-readonly ARN respectively.
attachment_block_customer_instances(block) := {r.address |
	some r in planned_resources
	r.type == "aws_iam_role_policy_attachment"
	base_address(r.address) == block.address
	attachment_instance_targets_customer_policy(r)
}

attachment_block_s3_instances(block) := {r.address |
	some r in planned_resources
	r.type == "aws_iam_role_policy_attachment"
	base_address(r.address) == block.address
	r.values.policy_arn == s3_readonly_arn
}

metrics_covered_via_cartesian contains role_address if {
	some block in attachment_blocks
	not attachment_block_has_any_edge(block)
	some role_block in attachment_block_referenced_role_blocks(block)
	role_addrs := role_addresses_by_block[role_block]
	count(role_addrs) > 1
	count(attachment_block_customer_instances(block)) == count(role_addrs)
	some role_address in role_addrs
}

s3_covered_via_cartesian contains role_address if {
	some block in attachment_blocks
	not attachment_block_has_any_edge(block)
	some role_block in attachment_block_referenced_role_blocks(block)
	role_addrs := role_addresses_by_block[role_block]
	count(role_addrs) > 1
	count(attachment_block_s3_instances(block)) == count(role_addrs)
	some role_address in role_addrs
}

# BUG 6 FOUND AND FIXED, REPAIR PASS 5 (2026-08-22, adversarial-verifier
# finding): FOR_EACH-OVER-POLICIES / GRAPH-EDGE BLINDNESS, the policy-side
# mirror of BUG 2's role-side fix. `attachment_block_targets_customer_
# policy(block)` above resolves the attachment->policy edge ONLY via
# `block.expressions.policy_arn.references` naming a `customer_policies`
# address directly -- undefined for a `for_each`-over-a-map-of-policy-ARNs
# idiom, e.g. `for_each = local.shared_policy_arns; policy_arn =
# each.value` (references == ["each.value"], never
# "aws_iam_policy.team_metrics"), or a for_each-over-{role,policy}-pairs
# idiom (`policy_arn = each.value.policy_arn`). (SCOPE CORRECTION, REPAIR
# PASS 9: this fix covers the POLICY side of that idiom's edge only; its
# ROLE side needed PATH E -- BUG 11.) DEMONSTRATED (2026-08-22):
# a real `terraform plan` (provider 6.58.0) for either idiom, additive and
# otherwise fully correct (4 attachments, both roles x both policies),
# scored tier1 FAIL / reward 0.0 -- `covering_attachment_block_addrs` was
# empty for both idioms' team-metrics instances, and `deny`'s message
# claimed the policy was "not attached" when it plainly was.
#
# THE FIX: per PLANNED INSTANCE (not just per configured BLOCK), a second
# resolution path -- when `count(customer_policies) == 1` (this scenario
# always creates exactly one team-defined policy in a working solution,
# so there is no ambiguity about WHICH policy an unresolved reference
# could be) and the instance's own `values.policy_arn` did NOT resolve to
# a plan-time-known string, attribute that instance to the customer
# policy anyway (SCHEMA.md §4.2.1's plan-time-unknown class: the ONLY
# thing in this scenario's world that makes `policy_arn` unknown at plan
# time is a reference to the not-yet-created customer policy's own `.arn`
# -- the AWS-managed S3-readonly ARN is always a plan-time-known literal,
# so it can never be mistaken for this case, verified directly against
# real plan JSON for both idioms above: the `s3_read_only`-keyed instance
# always resolves a known string, the `team_metrics`-keyed instance never
# does). Verified in BOTH directions, 2026-08-22: both for_each-over-
# policies idioms now score tier1 PASS (reward 1.0, deny empty); the
# policy-attached-to-one-role-only catch, re-run in the SAME for_each-
# over-policies spelling (one role's for_each map never includes the
# team-metrics key at all), still FAILS as required -- that role's
# instances are either absent (no block to resolve at all) or, when
# present, cover only the plan-time-known S3 ARN, so
# `attachment_instance_targets_customer_policy` is false for every one of
# them and `deny`'s missing-role message still fires, accurately.
attachment_instance_targets_customer_policy(r) if {
	block := attachment_blocks_by_address[base_address(r.address)]
	attachment_block_targets_customer_policy(block)
}

attachment_instance_targets_customer_policy(r) if {
	count(customer_policies) == 1
	not attachment_instance_policy_arn_known(r)
}

metrics_covered_via_attachment := {e.role_address |
	some e in attachment_role_edges
	attachment_instance_targets_customer_policy(planned_by_address[e.instance])
}

s3_covered_via_attachment := {e.role_address |
	some e in attachment_role_edges
	planned_by_address[e.instance].values.policy_arn == s3_readonly_arn
}

# ---------------------------------------------------------------------
# Shape 2: aws_iam_role_policy_attachments_exclusive (role-scoped
# exclusive, declared as such by its own name). REJECTED, not covered --
# REPAIR PASS 4, 2026-08-22 (see this file's own header comment, BUG 5,
# and BUG 1's note directly above it for the full before/after; a prior
# pass had this UNIONED into the coverage sets below, which this pass
# removed). This resource type takes exclusive ownership of the ROLE's
# entire managed-policy set and removes any attachment its own
# `policy_arns` does not list -- exactly what this scenario's one
# load-bearing prompt sentence ("Other teams attach their own policies to
# these roles out of band; that must keep working.") forbids. Detected
# here ONLY to deny it outright (see the `deny` rule below); NOT the
# account-wide-exclusive `aws_iam_policy_attachment` (a different resource
# type entirely, still separately rejected by the spec's own tier-0
# `no-account-exclusive-policy-attachment` assert -- the
# account-exclusive-policy-attachment catch, unaffected by this file).
# ---------------------------------------------------------------------
exclusive_blocks := [r |
	some r in configured_resources
	r.type == "aws_iam_role_policy_attachments_exclusive"
]

# ---------------------------------------------------------------------
# Deny facts. Every set below is a set of plan ADDRESSES (BUG 8) -- the
# identity domain the sibling awscdk oracle has always used (the template
# LOGICAL ID -- `iam_role_ids` in ../../rego-cfn/iam-managed-policy-
# exclusive-vs-attachment/policy.rego, and before REPAIR PASS 10 the bare
# `count(%roles)` of the cfn-guard bundle it replaced), and the one the
# operator ruling of 2026-08-22 fixes for this scenario: existence +
# type + properties keyed on address, never a physical resource name.
# ---------------------------------------------------------------------
metrics_covered_role_addresses := metrics_covered_via_attachment | metrics_covered_via_cartesian

s3_covered_role_addresses := s3_covered_via_attachment | s3_covered_via_cartesian

# ---------------------------------------------------------------------
# TRUST PRINCIPALS, PER ROLE -- BUG 12 FOUND AND FIXED, REPAIR PASS 9
# (2026-08-23, adversarial-verifier finding -- ORACLE HONESTY / binding
# operator ruling 2, 2026-08-22).
#
# What was wrong: `oracle.intent`'s own opening sentence says "Two IAM
# roles exist: one whose trust policy permits ecs-tasks.amazonaws.com to
# assume it, and one whose trust policy permits lambda.amazonaws.com to
# assume it", and docs/design/batch-a-greenfield-blueprints.md 2(c)
# pre-registered the `two-roles-exist` row as "...the two
# assume_role_policy service principals ecs-tasks.amazonaws.com and
# lambda.amazonaws.com (`contains`, PER ROLE)". What was actually graded
# was two tier-0 `contains` asserts over the FLATTENED UNION of every
# role's trust principals plus BUG 7's bare role COUNT below -- which
# together rule out N != 2 but never pair a principal to a role.
# REPRODUCED, 2026-08-23, real toolchain (terraform 1.15.8 /
# hashicorp-aws 6.58.0 / opa 1.19.0): this scenario's own reference
# solve.sh with `Principal = { Service = "ecs-tasks.amazonaws.com" }`
# widened to `Principal = { Service = ["ecs-tasks.amazonaws.com",
# "lambda.amazonaws.com"] }` on the first role and
# `Principal = { Service = "lambda.amazonaws.com" }` replaced by
# `"states.amazonaws.com"` on the second (everything else untouched, both
# policies still on both roles) -- so `report-writer`, which the ticket
# says is assumed by Lambda, cannot be assumed by Lambda at all -- scored
# reward 1.0, `PASS [role-trusts-ecs-tasks-service]`,
# `PASS [role-trusts-lambda-service]`.
#
# THE FIX: three deny rules over role ADDRESSES (never names -- ruling 1).
# Some role must trust ecs-tasks; some role must trust lambda; and NO
# SINGLE role may carry both principals. Together those force the two
# principals onto two DISTINCT role addresses, which is the pre-registered
# fact; the third rule is what does the pairing work, since with the first
# two satisfied and no role carrying both, the ecs-trusting role and the
# lambda-trusting role are necessarily different resources.
#
# `values.assume_role_policy` is a static, agent-authored `jsonencode(...)`
# on every TF-shaped arm, so it is always plan-time-known (SCHEMA.md
# 4.2.1 does not bite here) -- confirmed against real plan JSON for every
# fixture in this scenario. Both JSON renders of a trust principal are
# accepted: a bare string (`Service = "lambda.amazonaws.com"`) and a list
# (`Service = ["a", "b"]`).
#
# Byte-for-byte the same semantics as the sibling awscdk oracle's three
# trust rules over `ecs_trusting_role_ids` / `lambda_trusting_role_ids` /
# `roles_trusting_both_ids` (../../rego-cfn/iam-managed-policy-exclusive-
# vs-attachment/policy.rego; they were `some_role_trusts_ecs_tasks` /
# `some_role_trusts_lambda` / `trust_principals_are_split_across_two_
# roles` in the cfn-guard bundle REPAIR PASS 10 replaced) -- deliberately,
# so no arm grades this fact more strictly than another. The tier-0
# `role-trusts-ecs-tasks-service` / `role-trusts-lambda-service` asserts
# are RETAINED, unchanged and honestly described as "at least one":
# tier-0's flat JSONPath+op grammar cannot express a per-role pairing.
# ---------------------------------------------------------------------
trust_statement_services(stmt) := services if {
	is_string(stmt.Principal.Service)
	services := {stmt.Principal.Service}
}

trust_statement_services(stmt) := services if {
	is_array(stmt.Principal.Service)
	services := {s | some s in stmt.Principal.Service}
}

role_trust_services[addr] := services if {
	some r in planned_resources
	r.type == "aws_iam_role"
	addr := r.address
	doc := json.unmarshal(r.values.assume_role_policy)
	services := {s |
		some stmt in doc.Statement
		some s in trust_statement_services(stmt)
	}
}

ecs_trusting_role_addresses := {addr |
	some addr, services in role_trust_services
	"ecs-tasks.amazonaws.com" in services
}

lambda_trusting_role_addresses := {addr |
	some addr, services in role_trust_services
	"lambda.amazonaws.com" in services
}

roles_trusting_both_addresses := ecs_trusting_role_addresses & lambda_trusting_role_addresses

deny contains msg if {
	count(ecs_trusting_role_addresses) == 0
	msg := "this scenario's ticket asks for an IAM role assumed by ECS tasks, but no aws_iam_role in this plan has an assume_role_policy naming the ecs-tasks.amazonaws.com service principal"
}

deny contains msg if {
	count(lambda_trusting_role_addresses) == 0
	msg := "this scenario's ticket asks for an IAM role assumed by Lambda, but no aws_iam_role in this plan has an assume_role_policy naming the lambda.amazonaws.com service principal"
}

deny contains msg if {
	count(roles_trusting_both_addresses) > 0
	msg := sprintf(
		"this scenario's ticket asks for TWO separate IAM roles, one assumed by ECS tasks and one assumed by Lambda, but the assume_role_policy of the role(s) at plan address %v names BOTH the ecs-tasks.amazonaws.com and the lambda.amazonaws.com service principal -- so the two trust principals are not split across two distinct roles",
		[roles_trusting_both_addresses],
	)
}

# two-roles-exist catch (REPAIR PASS 6, BUG 7): oracle.intent's own
# opening sentence says two IAM roles exist -- see this file's own header
# comment, BUG 7, for the full evidence that nothing previously encoded
# this fact and why a bare count (not a name match) is the right check.
# BUG 8 (REPAIR PASS 7) re-keyed the counted set from `values.name` onto
# the plan address, so a role whose physical name is provider-computed
# still counts -- exactly what the sibling awscdk rule has always done
# (`count(iam_role_ids) != 2` in ../../rego-cfn/iam-managed-policy-
# exclusive-vs-attachment/policy.rego since REPAIR PASS 10; before that,
# `two_roles_exist { %roles_count == 2 }`, a bare resource count).
deny contains msg if {
	count(iam_role_addresses) != 2
	msg := sprintf(
		"this scenario's ticket asks for two IAM roles (one trusted by ecs-tasks.amazonaws.com, one trusted by lambda.amazonaws.com) -- found %d aws_iam_role resource(s) in the plan",
		[count(iam_role_addresses)],
	)
}

# role-scoped-exclusive-attachment catch (REPAIR PASS 4): defense in depth
# alongside the scenario's primary defense, the tier-0
# `no-role-scoped-exclusive-attachment` assert (specs/
# iam-managed-policy-exclusive-vs-attachment.yaml) -- an accurate,
# specific deny message in case tier-0 is ever bypassed or this policy is
# run standalone. Mirrors, at tier 1, the same rejection
# `aws_iam_policy_attachment` already gets (structurally, via
# no-account-exclusive-policy-attachment at tier 0 only, since that
# resource type needs no per-role identity resolution to reject -- its
# mere existence is disqualifying, same as here).
deny contains msg if {
	count(exclusive_blocks) > 0
	msg := "aws_iam_role_policy_attachments_exclusive takes exclusive ownership of a role's entire managed-policy set and removes any attachment not listed in its own policy_arns on the next apply -- this scenario's ticket requires that out-of-band attachments other teams make to these roles survive, so use the additive aws_iam_role_policy_attachment resource instead"
}

# policy-attached-to-one-role-only catch: the team-defined metrics policy
# must cover EVERY role this scenario creates, not just one -- see this
# file's header comment for why a per-role (not flat) check is required.
deny contains msg if {
	missing := iam_role_addresses - metrics_covered_role_addresses
	count(missing) > 0
	msg := sprintf(
		"the plan does not establish that the team-defined managed policy (the customer-authored aws_iam_policy resource created in this configuration) is attached to the IAM role(s) at plan address: %v -- no aws_iam_role_policy_attachment instance in this plan resolves onto them",
		[missing],
	)
}

# BUG 9 FOUND AND FIXED, REPAIR PASS 7 (2026-08-22, adversarial-verifier
# finding -- ORACLE HONESTY). The prompt says "Both roles need read access
# to our reporting data in S3 (the AWS managed policy
# AmazonS3ReadOnlyAccess)", and the pre-registered tier-0 plan
# (docs/design/batch-a-greenfield-blueprints.md §2(c), row
# `managed-policy-attached-to-both-roles`) encodes exactly that -- but
# this rule used to fire only when ZERO roles were covered
# (`count(s3_covered_role_names) == 0`), an "at least one role" check.
# REPRODUCED, 2026-08-22, both TF-shaped arms and awscdk: this scenario's
# own reference solution with the SECOND role's S3-readonly attachment
# deleted (hcl_raw: the `report_writer_s3_read` block; terraconstructs and
# awscdk: the `reportWriter.addManagedPolicy(s3ReadOnly)` line) -- a plain
# omission of a stated requirement -- scored reward 1.0 on every arm.
# THE FIX: the same per-role set difference the metrics rule above already
# uses, over role ADDRESSES (operator ruling 2, 2026-08-22: where the
# prompt says a requirement applies to BOTH roles, the oracle enforces it
# PER ROLE, not "at least one"). `oracle.intent` and the sibling awscdk
# rule (`s3_readonly_attached_to_both_roles`, converted to the per-role
# `%roles { ... }` block form in the same pass, and carried over as the
# `iam_role_ids - s3_readonly_covered_role_ids` set difference when REPAIR
# PASS 10 ported that arm to ../../rego-cfn/iam-managed-policy-exclusive-
# vs-attachment/policy.rego) were corrected with it, so no arm and no
# document still says "at least one".
deny contains msg if {
	missing := iam_role_addresses - s3_covered_role_addresses
	count(missing) > 0
	msg := sprintf(
		"the plan does not establish that the AWS managed policy AmazonS3ReadOnlyAccess is attached to the IAM role(s) at plan address: %v -- no aws_iam_role_policy_attachment instance whose policy_arn is that literal ARN resolves onto them",
		[missing],
	)
}
