# Hand-authored (Batch A, 2026-08-21) -- NOT a generator stub. emit_oracles()
# never overwrites this file once it exists (specs/SCHEMA.md §8.2 rule 7).
#
# ###########################################################################
# READ THIS FIRST -- ROUND 15 (2026-08-24). FOUR EXECUTED DEFECTS FIXED,
# THREE OF THEM SILENT PASSES ON GENUINELY BROKEN ARTIFACTS.
# ###########################################################################
#
# Round 14 was rejected by adversarial verification. Every item below was
# reproduced by execution in the real hcl_raw image, `--network none`, with
# the generated tests/static_tiers.sh verbatim. Search "ROUND 15" for the
# code; the operator-facing statement is in the spec's RESIDUALS block and
# docs/design/conftest-hcl-traversal-spike.md sect 0.0 residuals 2, 4, 8-10.
#
#  1. SAME-TYPE / WRONG-INSTANCE THROUGH A `for_each` KEY -- REWARD 1.0 on a
#     broken artifact. `hcl.instance_of` sliced the first TWO segments of a
#     referent path, so `aws_s3_bucket.b["...-decoy"].arn` and
#     `aws_s3_bucket.b["...-media"].arn` collapsed to the SAME instance. The
#     tokenizer parses the `["key"]` form deliberately, which is what made
#     the collapse silent rather than a refusal -- only the NUMERIC `[0]`
#     spelling ever failed to parse, and three operator-facing texts
#     generalised from that and called the whole family "loud, not silent".
#     FIX: the instance identity carries the key, and the plan-value anchor
#     route keys on each planned instance's own `.index`.
#  2. THE TOPIC ANCHOR WAS A UNION AND THE TEST ONLY ASKED FOR MEMBERSHIP --
#     REWARD 1.0. Adding ONE extra `topic` block laundered the checked-in
#     `sns-topic-policy-attached-to-a-decoy-topic-*` catch: attach the one
#     policy to the decoy, leave the wired audit topic with no resource
#     policy at all. FIX: grade PER WIRED TOPIC (`every`, not `some`), gate
#     each `topic` BLOCK separately, and apply the same quantifier to the
#     bucket half.
#  3. `configured_resources` WAS A BARE REFERENCE, so the WHOLE tier-1
#     policy failed OPEN whenever `.configuration.root_module.resources` was
#     absent -- which is what a `module` block does. FIX: `object.get` with
#     an `is_array` guard, plus two fail-closed denies that refuse modules
#     BY NAME.
#  4. A `count`/`for_each` ON THE GRADED `aws_lambda_permission` silently
#     DISABLED the rule that grades it (the config<->plan join was on
#     `.address`) and produced a deny the artifact contradicts -- REWARD 0.0
#     on a FULLY CORRECT solution. FIX: join on `[type, name]`, held as a
#     SET of pairs so a `for_each`-expanded permission cannot raise
#     `eval_conflict_error`.
#
# ###########################################################################
# ROUND 13 (2026-08-23) SUPERSEDES MOST OF THE HEADER THAT FOLLOWS.
# ###########################################################################
#
# This file carries a long round-by-round history (rounds 2-12). It is kept,
# because how an oracle was wrong five times in a row is more informative
# than any single fix. But rounds 8-12 all describe a mechanism that NO
# LONGER EXISTS in this file, and several of their conclusions are now known
# to be FALSE. Do not read the history as a description of the code.
#
# WHAT CHANGED IN KIND. Rounds 8-12 reasoned about a SYMBOL, because
# `terraform show -json` does not emit `locals` and the referent was out of
# reach. Round 13 reads the referent: the hcl_raw arm's generated
# tests/static_tiers.sh now parses the agent's own `.tf` files with
# `hcl2json` and merges them into this policy's `input` under one reserved
# key, `_hcl` (`oracle.hcl_traversal`, specs/SCHEMA.md §4.6). The full
# statement of what that buys, what it deletes, and what it does NOT do is
# in the "ROUND 13 -- RESOLUTION REPLACES THE HEURISTIC" block further down;
# the shared library's own header (tests/hcl_traversal.rego, canonical at
# oracles/rego/lib/hcl_traversal.rego) carries the three-valued contract.
#
# DELETED, not deprecated -- every mention of these below is history:
#   config_reaches_arn_of / relevant_arn_resources / indirection_symbols /
#   deepest_refs / extended_in / direct_reference / slot_planned_value /
#   slot_is_plan_time_unknown / bucket_denoting_indirections /
#   topic_denoting_indirections / topic_target_indirections /
#   topic_arn_slot_references / topic_target_slot_references /
#   slot_conflicting_symbols / source_arn_reason / topic_attach_reason
#
# CLAIMS RETRACTED. Wherever the history below says the remaining
# cross-arm strictness difference (a bucket ARN reached through ONE symbol
# while a different resource's ARN is laundered through a SECOND symbol into
# `source_arn`) is "IRREDUCIBLE from `terraform show -json`" and is recorded
# as a standing difference rather than a hole: that is FALSE as of round 13.
# It was irreducible from `plan.json`, and `plan.json` is no longer the only
# input. Executed, same planned artifact: round 12 deny set EMPTY (reward
# 1.0), round 13 DENY. Fixture:
# `lambda-permission-scoped-to-a-second-symbol-holding-the-lambda-arn`.
#
# AND A HOLE NONE OF ROUNDS 2-12 RECORDED AT ALL, on any arm:
# SAME-TYPE / WRONG-INSTANCE. Every acceptance test in this file was a TYPE
# test (`startswith(ref, "aws_s3_bucket.")`) that cannot tell two buckets
# apart, and so was the awscdk `oracles/rego-cfn/` policy's. A `source_arn`
# scoped to a bucket the notification does not wire -- S3 can never invoke
# the function -- scored 1.0 on every arm, laundered or written directly.
# Closed in this same pass on all three arms, with fixtures.
#
# WHAT IS RESIDUAL NOW is stated at the end of the ROUND 13 block, not here,
# so there is exactly one operator-facing list of it in this file.
#
# Scenario:   s3-notification-authoritative-singleton (specs/s3-notification-authoritative-singleton.yaml)
# Intent doc: oracles/s3-notification-authoritative-singleton/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.s3_notification_authoritative_singleton.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Encodes three tier-1 structural_asserts from the spec:
#   1. lambda-permission-scoped-to-bucket-tf -- s3-lambda-log-retention's
#      own rule, reused verbatim (same join-by-address pattern: `principal`
#      is read from `.planned_values` since it is always plan-time-known,
#      `source_arn`'s REFERENCES are read from `.configuration` since its
#      VALUE can be plan-time-unknown, SCHEMA.md §4.2.1).
#   2. sns-topic-policy-allows-s3-publish-tf -- the SNS-side mirror: EITHER
#      an `aws_sns_topic_policy` resource's `policy` (jsonencode'd) must
#      reference the created S3 bucket (the SourceArn condition) and its
#      `arn` must reference the created SNS topic (i.e. it actually
#      attaches to THIS topic, not some other one), OR (ROUND-2, see this
#      file's own correction note ahead of the SNS section) an
#      `aws_sns_topic` resource's own inline `policy` argument -- the
#      provider's other documented shape for the same wiring -- must
#      reference the created S3 bucket the same way. This rule now ALSO
#      carries the "does a policy-bearing shape exist at all" fail-closed
#      check for the TF-shaped arms (moved here from a tier-0 assert that
#      could not OR the two resource shapes together).
#   3. audit-topic-events-cover-a-real-delete (ROUND 6) -- the topic
#      target's wired events must include at least one of
#      `s3:ObjectRemoved:*` / `s3:ObjectRemoved:Delete`, the two forms
#      that actually fire for an ordinary user-initiated delete on this
#      unversioned bucket; a subset drawn only from
#      `s3:LifecycleExpiration:*`/`s3:ObjectRemoved:DeleteMarkerCreated`
#      passes the tier-0 whitelist but never fires for a real delete. See
#      that rule's own header comment ahead of its declaration below.
#
# Also implements, as real (not prose) code, the REUSABLE
# "cardinality of an authoritative child resource per parent" helper this
# scenario's own spec.yaml header comment describes -- built once here for
# a future scenario (§10/§8/the brownfield clobber sibling per the design
# blueprint) to copy and generalize. NOT wired into `deny` as an
# independent, separately-triggerable rule in THIS package: on this
# scenario's own one-bucket topology, every fixture that would violate the
# general per-parent form also violates the FLAT tier-0 count
# (exactly-one-notification-resource-per-bucket-tf, oracles/lib/structural.py
# -- graded before this policy ever runs), so a standalone deny rule here
# could never be OBSERVED failing at tier 1 for any real fixture --
# declaring one as a separate structural_assert would violate
# generator/check_tier1_coverage.py's floor for a brand-new spec (see the
# spec's own catches[] header comment). The helper is still exercised for
# real below (`authoritative_child_unique_per_parent` is called, its
# result folded into `not_verifiable` as a always-quiet self-check note,
# never into `deny`) so it is proven callable and correct against this
# scenario's own fixtures before the next scenario copies it.
#
# Verified against real `terraform show -json` plan output at authoring
# time: this scenario's own reference solution/solve.sh (PASS, deny
# empty), the two-notification-resources-for-one-bucket /
# only-one-of-the-two-events-wired broken fixtures (never reach a
# meaningfully different state here -- both are caught upstream at tier 0,
# see each catch's own description; this policy still evaluates against
# them without error, correctly finding nothing further wrong once the
# tier-0-catchable half is already violated), and the tier-1-only broken
# fixtures (lambda-permission-not-scoped-to-bucket,
# sns-topic-policy-not-scoped-to-bucket, inline-sns-topic-policy-not-
# scoped-to-bucket -- each FAILs exactly the rule named after it and no
# other) plus sns-publish-not-permitted (now caught HERE, at tier 1, by
# the fail-closed rule below -- see the ROUND-2 CORRECTION note ahead of
# the SNS section for why this moved from tier 0).
#
# ROUND-2 CORRECTION (2026-08-21, this authoring pass -- a verifier
# rejection, PROVEN by executing a reference-equivalent main.tf whose only
# change was the topic-policy shape): the provider's OWN canonical
# documented shape for wiring S3 -> SNS
# (https://github.com/hashicorp/terraform-provider-aws, website/docs/r/
# s3_bucket_notification.html.markdown's FIRST example, "Add notification
# configuration to SNS Topic") sets `policy = data.aws_iam_policy_document.
# <x>.json` DIRECTLY on `aws_sns_topic` -- no separate `aws_sns_topic_policy`
# resource at all (`policy` is a documented optional argument of
# `aws_sns_topic` itself, website/docs/r/sns_topic.html.markdown). This is a
# fully correct, functional, bucket-scoped solution and was NOT tolerated:
# the spec's old tier-0 `sns-topic-policy-exists` assert filtered on
# `.type=='aws_sns_topic_policy'` specifically, so the inline shape resolved
# to zero nodes and failed outright -- the exact "constraint that forces the
# oracle's expected shape" failure mode docs/adding-scenarios.md §1 item 3a
# names (the apigw-openapi cautionary example). jsonpath_ng.ext (this repo's
# pinned version) cannot parse an `||`-combined filter
# (`[?(@.type=='aws_sns_topic_policy' || @.type=='aws_sns_topic')]` --
# verified directly: `Parse error ... near token | (|)`), so the OR across
# resource shapes cannot be expressed as a tier-0 jsonpath op at all --
# hence: the tier-0 `sns-topic-policy-exists` assert now applies to awscdk
# ONLY (renamed `sns-topic-policy-exists-cfn` in the spec -- CloudFormation's
# `AWS::SNS::Topic` resource type has NO `Policy` property at all, verified
# against the CFN Template Reference, so this ambiguity is TF-only and the
# CFN-side existence check is unaffected and stays sound), and the TF-shaped
# arms' "does a policy-bearing shape exist AT ALL" fact moves entirely into
# this file's fail-closed rule below, ORing both shapes for real.
#
# ROUND-9 CORRECTION (2026-08-23) -- two verifier findings, both PROVEN by
# execution, both in the code round 8 touched. (a) Round 8 gave the
# `local.`/`var.` tolerance to `source_arn` but not to its exact sibling
# `aws_sns_topic_policy.arn`, so hoisting the topic ARN (referenced three
# times in this scenario's own hcl_raw reference solution) scored 0.0 on
# hcl_raw while the same authoring decision scored 1.0 on awscdk and could
# not arise on terraconstructs -- with a deny message that was factually
# false about the artifact it denied. (b) Round 8 applied that same
# tolerance to `policy_references_deep`, a FLAT union over an entire
# policy DOCUMENT, so any `local.` reference anywhere in it satisfied the
# "scoped to the bucket" test -- which silently defeated the
# `sns-topic-policy-not-scoped-to-bucket` catch (the checked-in broken
# fixture plus one ordinary `locals` hoist of the TOPIC's own ARN scored
# 1.0). Both are fixed below, and both now have checked-in broken fixtures
# (`sns-topic-policy-attached-to-a-different-topic`,
# `sns-topic-policy-unscoped-behind-a-local`) so the chosen behaviour is
# falsified by `make falsifiability` rather than assumed. The organising
# distinction is POSITION: a dedicated single-ARN argument SLOT
# (`arn_slot_denotes`) versus a whole policy DOCUMENT
# (`bucket_denoting_indirections`). See the two long blocks below.
#
# ROUND-10 CORRECTION (2026-08-23) -- the same finding family, one
# direction further, PROVEN by execution. Round 8's `local.`/`var.`
# tolerance in an ARN SLOT was justified partly by symmetry with the awscdk
# arm's `Fn::Sub` leniency. Round 10 ported that arm's tier-1 off cfn-guard
# onto Rego (`oracle.awscdk_tier1_engine: rego`), which parses Sub tokens,
# so the symmetry no longer holds -- and the residual it excused turned out
# to be live and cheap on THIS scenario rather than "strictly more work
# than writing the literal inline": the reference solution itself hoists
# `local.audit_topic_arn`, so `source_arn = local.audit_topic_arn` (one
# token off `local.media_bucket_arn`) scored reward 1.0 on hcl_raw while
# `sourceArn: auditTopic.topicArn` scored 0.0 on awscdk. FIXED below by
# extending round 9's own PROVENANCE technique to the slot itself
# (`slot_provenance_conflict`): an unresolvable symbol still stands in for
# an ARN in a dedicated ARN slot, but a symbol this configuration also uses
# in an `aws_sns_topic_policy.arn` slot can no longer denote the BUCKET in
# a `source_arn` slot. The mirror direction is deliberately NOT
# implemented -- see that helper's own "ONE-DIRECTIONAL ON PURPOSE" note
# for the artifact that proved the mirror would deny a correctly-attached
# topic policy, i.e. would state something false about what it denied.
# Falsified by the new
# `lambda-permission-scoped-to-the-topic-arn-behind-a-local` broken
# fixture, which is isolated at tier 1 (tier0_pass=1); the new
# `no-lambda-permission-at-all` fixture falsifies the fail-closed rule
# below, which no fixture on any arm had ever exercised. The `source_arn`
# deny message was rewritten to quote the provenance set it consults, so a
# denial states what is true of the artifact (Amendment 29 §6 RULING 3)
# instead of asserting "no local./var. indirection" about an artifact that
# plainly has one.
#
# ROUND-11 CORRECTION (2026-08-23) -- round 10's two claims above, both
# disproved by execution, both fixed in the code below. (a) The provenance
# narrowing read candidate topic symbols out of ONE slot,
# `aws_sns_topic_policy.arn`; writing that unrelated argument in its more
# idiomatic DIRECT form emptied the set and restored the 1.0-vs-0.0 break,
# and for the inline `aws_sns_topic.policy` shape the clause could never
# fire at all. `topic_arn_slot_references` now spans every plan slot that
# can hold only a topic ARN, the decisive one being
# `aws_s3_bucket_notification.topic[*].topic_arn`, which every solution
# that wires the topic has. (b) The surviving "more work than writing the
# literal inline" residual was not a residual: `.planned_values` resolves a
# laundered literal to its constant string and leaves a hoist of a
# provider-computed `.arn` absent, so `slot_is_plan_time_unknown` now
# decides it and the round-7 defect stops scoring 1.0 on hcl_raw. Three new
# hcl_raw fixtures falsify the three clauses
# (`...-direct-policy-attach`, `...-with-an-inline-topic-policy`,
# `lambda-permission-scoped-to-a-laundered-literal`).
#
# ROUND-12 REWRITE (2026-08-23) -- rounds 8-11 were all narrowings of a
# RESIDUAL acceptance ("the plan cannot resolve this slot and I found
# nothing that contradicts it"), and an adversarial verifier broke that
# frame in both directions at once: a wrong-TYPE resource ARN behind a
# local was still accepted on hcl_raw and rejected on awscdk (1.0 vs 0.0,
# in the bucket slot AND in the topic-policy attachment slot), while the
# ordinary DRY shape of hoisting both ARNs into ONE `locals` map was
# REJECTED on hcl_raw and accepted on awscdk (0.0 vs 1.0), because
# provenance was matched on the container prefix terraform emits alongside
# every traversal. The acceptance is now POSITIVE in every clause --
# `deepest_refs` (whole traversals, never prefixes), `config_reaches_arn_of`
# (the plan's own `relevant_attributes`, which resolves the locals hop),
# and CORROBORATION for the attachment slot -- and the one residual that
# genuinely cannot be decided from a terraform plan is recorded as a
# standing cross-arm strictness difference instead of being called closed.
# See the long ROUND-12 block ahead of `deepest_refs` for the executed
# proofs, and the four new fixtures (two per TF/awscdk pair) that falsify
# it.

package cdktn_bench.s3_notification_authoritative_singleton

import rego.v1

# The shared HCL traversal resolver (oracles/rego/lib/hcl_traversal.rego,
# copied into this task's tests/ beside this file and loaded with a second
# `-d`). READ ITS HEADER before this file's ROUND 13 section: it carries the
# three-valued contract, the arity gate, and the three executed defects that
# dictate its shape.
import data.cdktn_bench.hcl

# TOTAL (round 15). This was a BARE reference -- `input.configuration.
# root_module.resources` -- nine lines above `planned_resources`, whose own
# comment already explained why that is unsafe. Executed on the real merged
# oracle input from this scenario's reference solution: deleting
# `.configuration.root_module.resources` (or setting it to a string, or
# deleting `.configuration` outright) made EVERY rule downstream of it
# undefined, and an undefined `deny` rule does not deny -- `deny` came back
# length 0, i.e. the whole tier-1 policy failed OPEN.
#
# That is reachable from an agent artifact, not just from a corrupted
# document: everything inside a `module` block lands under
# `.configuration.root_module.module_calls` / `.planned_values.root_module.
# child_modules`, leaving `root_module.resources` ABSENT. Verified in the
# image with all resources moved into `./modules/wiring` and `source_arn =
# aws_s3_bucket.decoy.arn`: tier1_status=PASS, deny []. The only thing that
# stopped a 1.0 was a tier-0 error, and "already denied at tier 0" is
# exactly the mitigation this scenario retracted as unsound (see the ROUND
# 14 block below and docs/design/conftest-hcl-traversal-spike.md sect 5.3).
#
# `object.get` turns the fail-open into an empty list, and the two
# `_module_*` denies just below turn an empty list into a LOUD refusal that
# names modules the way `module.x.out` is already named by the resolver.
# The `is_array` guard is not belt-and-braces. `object.get` with a `[]`
# default only covers ABSENT; a key present with a NON-LIST value sails
# through, and `count("nope")` is 4, so the "empty but the plan has
# resources" deny below would not fire either. Executed: setting
# `.configuration.root_module.resources` to a string scored deny length 0 --
# fail-open -- until this clause was added. Anything that is not a list
# becomes the empty list, which the deny below then reports out loud.
configured_resources := rs if {
	raw := object.get(input, ["configuration", "root_module", "resources"], [])
	is_array(raw)
	rs := raw
} else := []

# --- MODULES ARE REFUSED BY NAME, not silently ungraded -------------------
#
# This oracle reads `root_module` only. A resource declared inside a
# `module` block is invisible to every rule in this file, and invisibility
# in a fail-closed design must never be spelled "no deny". These two rules
# are the fail-closed floor under `configured_resources`.
_child_modules_present if {
	some _ in object.get(input, ["planned_values", "root_module", "child_modules"], [])
}

_child_modules_present if {
	some _ in object.get(input, ["configuration", "root_module", "module_calls"], {})
}

deny contains msg if {
	_child_modules_present
	msg := sprintf(
		"this configuration declares resources inside `module` block(s) (%v), and this oracle reads the ROOT module only -- so the wiring inside them is not graded at all. That is refused rather than passed: an ungraded resource is indistinguishable from a correct one. Declare the bucket, the notification, the lambda permission and the topic policy in the root module. (The same boundary is why the symbol resolver refuses `module.x.out` by name; see tests/hcl_traversal.rego.)",
		[sort([name | some name, _ in object.get(input, ["configuration", "root_module", "module_calls"], {})])],
	)
}

deny contains msg if {
	count(configured_resources) == 0
	count(planned_resources) > 0
	not _child_modules_present
	msg := sprintf(
		"this plan's `.planned_values.root_module.resources` lists %d resource(s) (%v) but its `.configuration.root_module.resources` is absent or empty, so no rule in this oracle that reads the CONFIGURATION -- every reference/slot rule it has -- can see anything to grade. The oracle refuses to report a pass it did not establish.",
		[
			count(planned_resources),
			sort([r.address | some r in planned_resources]),
		],
	)
}

# TOTAL (round 14). `input.planned_values.root_module.resources` is always
# present in a real `terraform show -json`, but reading it as a bare
# reference makes EVERY rule downstream of it UNDEFINED if it ever is not --
# and an undefined `deny` rule does not deny. `object.get` with a default
# turns that from a silent pass into an empty resource list, which the
# fail-closed rules below then report out loud.
planned_resources := rs if {
	raw := object.get(input, ["planned_values", "root_module", "resources"], [])
	is_array(raw)
	rs := raw
} else := []

s3_buckets := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket"
]

sns_topics := [r |
	some r in configured_resources
	r.type == "aws_sns_topic"
]

# --- Lambda permission scoping (s3-lambda-log-retention's own rule, reused
# verbatim -- principal is always plan-time-known so it is read from
# .planned_values and joined back to the .configuration resource for the
# source_arn graph-edge check; see the ROUND 15 note below for why that join
# is on [type, name] and not on .address) ---------------------------------

# ROUND 15 -- THE CONFIG<->PLAN JOIN IS ON `[type, name]`, NOT ON `.address`.
#
# *** Executed false FAIL this replaces. `principal_by_addr` keyed on the
# PLANNED address and `s3_invoke_permissions` looked that key up with the
# CONFIGURATION address. Those two strings differ the moment the permission
# carries a `count`/`for_each` meta-argument: the plan says
# `aws_lambda_permission.allow_s3_invoke[0]`, the configuration says
# `aws_lambda_permission.allow_s3_invoke`. The join never matched,
# `s3_invoke_permissions` came back EMPTY, the source_arn scoping rule was
# silently disabled, and the fail-closed fallback fired with a message the
# artifact flatly contradicts -- "no aws_lambda_permission resource granting
# principal s3.amazonaws.com exists anywhere in the plan" about a plan whose
# `.planned_values` contains exactly that (Amendment 29 sect 6 RULING 3).
# A fully correct solution with `count = 1` added scored REWARD 0.0. ***
#
# A SET of `[type, name]` pairs, not an object keyed by them, for the reason
# the shared library's header gives at length: a `for_each`-expanded
# permission has N planned instances sharing one `[type, name]`, and an
# object rule binding one key to two different principals raises
# `eval_conflict_error`, which aborts evaluation and scores a correct
# solution 0.0 with no message at all. A set cannot conflict -- it just
# holds the pair once.
s3_invoke_principal_keys := {[r.type, r.name] |
	some r in planned_resources
	r.type == "aws_lambda_permission"
	object.get(r, ["values", "principal"], null) == "s3.amazonaws.com"
}

permission_configs := [r |
	some r in configured_resources
	r.type == "aws_lambda_permission"
]

s3_invoke_permissions := [r |
	some r in permission_configs
	[r.type, r.name] in s3_invoke_principal_keys
]

# ROUND-8 ARM-PARITY FIX (2026-08-23) -- `object.get` with an ARRAY path +
# default, so a permission that sets no `source_arn` argument at all
# resolves to `[]` here instead of leaving this function (and, before this
# change, potentially the deny message that quotes it) undefined.
source_arn_references(rp) := object.get(rp, ["expressions", "source_arn", "references"], [])

# --- Reference-shape helpers, shared by both halves ------------------------
#
# ROUND 13 (2026-08-23): `direct_reference(refs, addr_prefix)` -- the plain
# "does this reference list name a resource of the given type AT ALL" test
# every round 8-12 acceptance rested on -- is DELETED, not deprecated. Two
# reasons, both of which the round-13 section below documents in full:
#   * it answered a question about a LIST when the graded question is about
#     ONE slot, so it silently accepted a slot holding zero or several
#     references (an arity hole that was an executed silent PASS), and
#   * it could only ever say "SOME bucket", never WHICH bucket, so
#     same-type/wrong-instance was invisible to it on every arm.
# Both are now handled by `hcl.slot` + `slot_names_arn_of`, which read one
# slot, gate its arity, resolve its single reference to a referent, and
# compare that referent's INSTANCE to the one this configuration's own
# notification resource wires.

# NOTE (ROUND 12, 2026-08-23): the `unresolvable_indirection(refs)`
# predicate the round-8..11 commentary below names -- a bare "does this
# reference list contain any `^(local|var)\.` entry" test -- was DELETED
# here and replaced by `indirection_symbols` further down, which returns
# the symbols THEMSELVES and, decisively, normalizes a slot's `.references`
# list through `deepest_refs` first. `terraform show -json` emits the
# container prefix of a traversal alongside the traversal
# (`["local.arns.media_bucket", "local.arns"]`), and matching on that
# shared prefix was the round-12 false negative. The reason such a hop is
# unresolvable at all is unchanged and still load-bearing:
# `.configuration.root_module` carries exactly `["resources","variables"]`,
# so locals are not emitted there and `local.x` is a dead end for a
# reference-graph check -- which is why round 12 resolves it from the
# plan's `relevant_attributes` instead.

# ROUND-8 ARM-PARITY FIX (2026-08-23), NARROWED AT ROUND 9 (2026-08-23).
#
# ROUND 8: an adversarial verifier PROVED by execution that the graph-edge
# test below used to reject a CORRECT solution: hoisting the bucket ARN
# into a Terraform `locals` block --
#
#     locals { media_bucket_arn = aws_s3_bucket.media.arn }
#     ... source_arn = local.media_bucket_arn
#
# -- a plain DRY move (the ARN is referenced twice in this scenario: the
# invoke permission and the topic policy's `aws:SourceArn` condition, and
# this file's own `rego_hints` already anticipate the same hoist for
# `principal`) scored reward 0.0 on hcl_raw, while the byte-for-byte
# equivalent decision on awscdk (`const mediaBucketArn = bucket.bucketArn`)
# scored 1.0, because the TS const disappears at synth time and the
# template still carries the `Fn::GetAtt`.
#
# Resolution chosen then, and kept: LOOSEN toward parity. Rejecting a
# correct artifact is a false NEGATIVE that would bias every hcl_raw row of
# a scenario whose entire output is a cross-arm comparison.
#
# ROUND-10 CORRECTION to round 8's own justification (2026-08-23). Round 8
# ALSO argued that "the awscdk arm is ALREADY lenient on exactly this axis
# -- `policy.guard` accepts any `Fn::Sub`-composed SourceArn without
# inspecting the Sub template string -- so each arm is lenient exactly on
# the indirection its own static analyzer cannot resolve". That second
# justification is now FALSE and is superseded, not preserved: round 10
# ported the awscdk tier-1 off cfn-guard onto Rego
# (`oracle.awscdk_tier1_engine: rego`, oracles/rego-cfn/<id>/policy.rego),
# and Rego DOES parse `${Logical.Arn}` out of a Sub template string, so
# that arm now resolves every indirection its artifact can express. The
# leniency below therefore stands on the FIRST justification alone -- which
# is the load-bearing one and is unaffected: `terraform show -json` emits
# no locals at all, and rejecting the hop demonstrably fails correct
# solutions. It is now a ONE-SIDED residual, and this file says so instead
# of balancing it against a residual that has been closed.
#
# ROUND 9 -- what changed, and why. Round 8 implemented that leniency as a
# single `bucket_reference(refs)` helper and then applied it to
# `policy_references_deep(tp)`, the union of EVERY reference found anywhere
# in a whole topic-policy DOCUMENT. An adversarial verifier PROVED by
# execution that this defeated one of this scenario's own declared catches:
# taking the checked-in `sns-topic-policy-not-scoped-to-bucket` broken
# fixture (a policy granting `s3.amazonaws.com` `sns:Publish` with NO
# `aws:SourceArn` condition at all) and adding one ordinary edit --
# `locals { audit_topic_arn = aws_sns_topic.audit.arn }`, used for the
# statement's own `Resource` -- made that fixture score reward 1.0. A
# `local.` reference to the TOPIC's ARN was satisfying a test meant to ask
# whether the BUCKET is named. The same pass proved the mirror-image
# defect: `references_this_topic` had been left on the strict spelling, so
# hoisting the topic ARN (referenced three times here) scored 0.0 while the
# same authoring decision was unreachable on terraconstructs and ungraded
# on awscdk.
#
# The distinction round 9 draws is POSITION, not spelling:
#
#   * A DEDICATED SINGLE-ARN ARGUMENT SLOT -- an argument whose entire
#     value IS the ARN under test: `aws_lambda_permission.source_arn`,
#     `aws_sns_topic_policy.arn`. Here there is no position ambiguity:
#     whatever `.references` holds is exactly what the argument was set to,
#     so "an indirection whose target this artifact cannot show" is the
#     whole and only fact available, and waving it through costs exactly
#     one shape (below). `arn_slot_denotes` is that test, and it is used
#     for BOTH slots -- which is the round-9 fix to the topic-attachment
#     half.
#   * A POLICY DOCUMENT -- `aws_sns_topic_policy.policy` /
#     `aws_sns_topic.policy`, a `jsonencode(...)` whose `.references` is
#     one FLAT list for the whole document (verified directly against this
#     scenario's own reference plan: `["aws_sns_topic.audit.arn",
#     "aws_sns_topic.audit", "local.media_bucket_arn"]`, with no path
#     information at all). A bare `local.`/`var.` entry here says nothing
#     about which JSON position it occupies. That half gets a narrower
#     rule instead -- see `bucket_denoting_indirections` in the SNS
#     section below.
#
# HISTORICAL: RESIDUAL LENIENCY of `arn_slot_denotes`, as rounds 8-10
# recorded it -- KEPT FOR THE RECORD, NO LONGER TRUE AS OF ROUND 11 (see
# the ROUND-11 CORRECTION block further down, which closes it and gives the
# executed proof that the justification below was false). It read: an
# ARN slot that reads `local.x`/`var.x` is accepted
# WITHOUT proving what `x` holds, so an unrelated ARN laundered through a
# local (`locals { x = "arn:aws:s3:::someone-elses-bucket" }`) passes that
# slot. That shape is strictly more work than writing the literal inline,
# which IS still rejected. NARROWED AT ROUND 10 (next block): the sentence
# above is true only of a symbol this configuration uses in ONE ARN slot
# and nowhere else -- a symbol it also uses as an `aws_sns_topic_policy.arn`
# is now rejected in a `source_arn` slot, because round 10 proved that
# variant was neither more work nor unreachable here.
#
# RETRACTED AT ROUND 12: this block used to end "Everything these rules are
# actually for still fails on every arm: an omitted argument, an inline
# literal/wildcard ARN, and a reference to a resource of the wrong type
# (the Lambda's own ARN, the audit topic in the bucket slot, a different
# topic in the attachment slot)." The last clause was FALSE on the
# TF-shaped arms whenever the wrong-type reference was reached through a
# `local.`: an adversarial verifier scored `media_bucket_arn =
# aws_lambda_function.ingest.arn` at reward 1.0 on hcl_raw with an EMPTY
# deny set (0.0 on the awscdk twin), and `arn = local.ingest_fn_arn` on the
# topic policy likewise. It is TRUE as of round 12 -- see the ROUND-12
# block below for how, and for the one residual round 12 records instead of
# claiming closed.
#
# ROUND-10 ARM-PARITY FIX (2026-08-23), narrowing that residual where the
# artifact itself says enough to narrow it. An adversarial verifier PROVED
# by execution that the residual above was not merely theoretical here, and
# not "strictly more work than writing the literal inline" either: THIS
# scenario's own reference solution hoists the AUDIT TOPIC's ARN into
# `local.audit_topic_arn` (it is referenced three times), so an ordinary
# copy/paste slip --
#
#     source_arn = local.audit_topic_arn      # meant local.media_bucket_arn
#
# -- is one token away from the correct spelling, costs no extra work at
# all, and scored reward 1.0 on hcl_raw. The byte-for-byte equivalent
# authoring decision on awscdk (`sourceArn: auditTopic.topicArn`, or the
# const-hoisted spelling of it) scored 0.0, because a TS const vanishes at
# synth time and the template still carries the `Ref` to the topic. Same
# defect, 1.0 vs 0.0, in the scenario whose entire output is a cross-arm
# comparison -- the round-7/8/9 finding family, one direction further.
#
# FIX, using round 9's own technique rather than a new one: PROVENANCE. A
# `local.`/`var.` symbol denotes at most ONE ARN, and this artifact does
# say which one whenever the configuration also uses that same symbol in a
# different dedicated ARN slot. So the unresolvable-indirection clause now
# holds only for a symbol with no CONFLICTING provenance: a symbol sitting
# in an `aws_sns_topic_policy.arn` slot (a topic-ARN slot) can no longer
# stand in for the bucket ARN in a `source_arn` slot, and vice versa. What
# stays accepted is exactly what round 8 proved must be accepted: a hoist
# whose symbol is used consistently for one ARN -- which is every correct
# solution, including this scenario's own reference (its
# `local.media_bucket_arn` never appears in a topic-ARN slot, and its
# `local.audit_topic_arn` never appears in a source_arn slot).
#
# WHAT ROUND 10 CLAIMED REMAINED RESIDUAL -- QUOTED HERE BECAUSE IT IS THE
# CLAIM ROUND 11 RETRACTS, not because it is true: "a symbol used in ONE
# slot only and nowhere else -- `locals { x = "arn:aws:s3:::someone-elses-
# bucket" }` used solely as `source_arn` -- still passes, because nothing
# in the plan document contradicts it. That shape genuinely is more work
# than writing the literal inline". Both sentences were wrong: the plan
# document DOES contradict it (`.planned_values` resolves that slot to the
# constant string), and the shape was not more work -- it scored reward 1.0
# on hcl_raw against 0.0 for the shipped awscdk twin. See the ROUND-11
# CORRECTION immediately below.
#
# What IS one-sided, and stays true: rounds 8-9 balanced the TF-side
# leniency against the awscdk arm's `Fn::Sub` leniency, and round 10's
# engine port CLOSED that one (oracles/rego-cfn/<id>/policy.rego parses Sub
# tokens). awscdk resolves every indirection its artifact can express; the
# TF-shaped arms cannot resolve a local at all from `.configuration`, and
# after round 11 they decide it from `.planned_values` instead of waving it
# through.
#
# ROUND-11 CORRECTION (2026-08-23) -- THE PARAGRAPH ABOVE WAS FACTUALLY
# WRONG, and the residual it justified is now CLOSED. It claimed a
# single-slot `locals { x = "arn:aws:s3:::someone-elses-bucket" }` "still
# passes, because nothing in the plan document contradicts it". An
# adversarial verifier disproved that by dumping the two plans: the
# laundered literal resolves
# `.planned_values...aws_lambda_permission.values.source_arn` to
# `"arn:aws:s3:::some-totally-unrelated-bucket"` -- fully plan-time-KNOWN --
# while this scenario's own reference solution, whose `local.media_bucket_arn`
# hoists the bucket's provider-computed `.arn`, has NO `source_arn` key
# under `values` at all. The plan therefore does contradict it, and the
# consequence was a live reward-level arm-parity break: the round-7 defect
# (an invoke permission scoped to a hardcoded, unrelated bucket ARN) scored
# 1.0 on hcl_raw laundered through a local, and 0.0 on the awscdk twin
# `lambda-permission-scoped-to-a-different-bucket`.
#
# The `.configuration` half of the file's reasoning stands -- locals really
# are not emitted there (`.configuration.root_module` carries exactly
# `["resources","variables"]`), which is why the REFERENCE list alone
# cannot resolve the hop. The conclusion drawn from it did not: the plan's
# OTHER half, `.planned_values`, carries the RESOLVED VALUE of the very
# same slot. So the indirection clause is now gated on that value:
#
#   * plan resolves the slot to a CONSTANT STRING -> the symbol is a
#     laundered literal, exactly the inline literal spelled one hop away,
#     and is REJECTED exactly as the inline literal always was.
#   * plan cannot resolve the slot (`values.<attr>` absent or null) -> the
#     symbol reaches something the provider computes at apply time, i.e.
#     the DRY hoist of a resource attribute round 8 proved must be
#     accepted. Still accepted -- including this scenario's own reference
#     solution, whose `source_arn` and `aws_sns_topic_policy.arn` both
#     resolve to unknown on every run of the falsifiability gate.
#
# Note what this does NOT do: it never reads a physical NAME out of
# `planned_values` and never compares one (RULING 1). The only fact it
# takes from there is whether the slot is plan-time-known at all, plus --
# for the deny message only -- the literal the plan itself resolved, quoted
# back so the message states something the artifact really contains
# (RULING 3).
#
# WHAT REMAINS RESIDUAL after round 11, stated exactly: a `var.` whose
# value is supplied at plan time from a resource attribute is unknown and
# accepted (correct); a `var.` with a hardcoded default IS resolved by the
# plan and now rejected. The remaining gap is an indirection that resolves
# to unknown for some reason OTHER than referencing this configuration's
# bucket -- e.g. `local.x = aws_sns_topic.audit.arn`.
#
# CORRECTED AT ROUND 12: round 11 finished that sentence with "That one is
# not covered by the value test at all, and is covered instead by the
# PROVENANCE test below, widened at round 11 to every dedicated topic-ARN
# slot in the plan" -- which was true ONLY for a symbol holding a TOPIC
# ARN, the one case the provenance test knows about. `local.x =
# aws_lambda_function.ingest.arn` and `local.x = aws_iam_role.ingest.arn`
# were covered by nothing at all and scored reward 1.0 on hcl_raw against
# 0.0 on the awscdk twin. The whole gap is closed positively at round 12
# (`config_reaches_arn_of`, plus corroboration in the attachment slot); the
# provenance test is kept, unchanged in purpose, as the one clause that can
# distinguish two symbols this configuration uses for two different ARNs.
# ===================== ROUND-12 REWRITE (2026-08-23) ======================
#
# An adversarial verifier PROVED, by execution on both arms, that the
# round-11 shape of this file was broken in BOTH directions at once. Both
# defects had one root cause: the acceptance of a `local.`/`var.` hop was
# RESIDUAL ("the plan cannot resolve this slot, and I found nothing that
# contradicts it") instead of POSITIVE ("the plan itself shows this
# configuration reaches an ARN of the required type"), and the one positive
# test it did have compared reference STRINGS BY PREFIX instead of
# comparing whole traversals.
#
# (1) FALSE ACCEPT / parity break, PROVEN: this scenario's own hcl_raw
#     reference solution with ONE token changed in its own locals block --
#     `media_bucket_arn = aws_lambda_function.ingest.arn` instead of
#     `= aws_s3_bucket.media.arn` -- scored reward 1.0 on hcl_raw (deny set
#     EMPTY), while the byte-equivalent awscdk twin (`const mediaBucketArn =
#     fn.functionArn; sourceArn: mediaBucketArn`) scored 0.0. Same for the
#     ATTACHMENT slot: `arn = local.ingest_fn_arn` on the topic policy (so
#     the audit topic has no policy at all) scored 1.0 on hcl_raw against
#     0.0 for its awscdk twin. `slot_is_plan_time_unknown` only ever
#     rejected laundered LITERALS, and `slot_provenance_conflict` only knew
#     about TOPIC-ARN slots, so any OTHER resource's `.arn` sailed through.
#
# (2) FALSE NEGATIVE / opposite-direction parity break + a factually FALSE
#     deny (Amendment 29 §6 RULING 3), PROVEN: the same reference solution
#     with its two locals merged into the ordinary DRY map --
#     `locals { arns = { media_bucket = aws_s3_bucket.media.arn,
#     audit_topic = aws_sns_topic.audit.arn } }` -- scored 0.0 on hcl_raw
#     while the awscdk twin (`const arns = { mediaBucket: bucket.bucketArn,
#     ... }`) scored 1.0. Cause: `terraform show -json` emits BOTH
#     `local.arns.media_bucket` AND the bare container `local.arns` in one
#     slot's `.references` list, so the round-10/11 provenance test matched
#     the container the two slots SHARE and denied a slot that demonstrably
#     holds `aws_s3_bucket.media.arn` -- with a message whose headline
#     ("nothing ties this grant to the bucket ... no local./var.
#     indirection usable as one") was false about the artifact it denied.
#
# THE FIX, in three parts, all of them reading facts the artifact really
# carries:
#
#   a. `deepest_refs` -- compare whole traversals, never prefixes. A slot's
#      `.references` list carries every prefix of what it found there
#      (`["local.arns.media_bucket", "local.arns"]`, and likewise
#      `["aws_sns_topic.audit.arn", "aws_sns_topic.audit"]`); only the
#      entries no other entry extends are what the argument was actually
#      set to. This alone fixes (2).
#
#   b. `config_reaches_arn_of` -- a POSITIVE test, from the plan's own
#      top-level `relevant_attributes` list, which terraform computes AFTER
#      expression evaluation and which therefore sees THROUGH the `locals`
#      hop the `.configuration` reference graph dead-ends on. A `local.` in
#      a bucket-ARN slot is accepted only if this configuration depends on
#      the `arn` attribute of SOME `aws_s3_bucket` at all. This closes the
#      bucket half of (1): with the local repointed at the Lambda, the plan
#      lists `aws_s3_bucket.media ["id"]` and no `arn` entry for it
#      anywhere, so there is nothing for any indirection to be reaching.
#
#   c. CORROBORATION for the attachment slot -- `aws_sns_topic_policy.arn`
#      accepts a symbol only if this configuration uses THAT SAME symbol in
#      another dedicated topic-ARN slot it did not write itself (the
#      notification's `topic[*].topic_arn`, a subscription's `topic_arn`).
#      This closes the attachment half of (1): `local.ingest_fn_arn`
#      appears in no such slot. `relevant_attributes` alone could not close
#      it, because a solution that wires the topic at all makes
#      `aws_sns_topic.audit.arn` a real dependency of the plan whatever the
#      policy is attached to.
#
# WHAT IS STILL RESIDUAL, stated exactly, MEASURED rather than estimated,
# and NOT called "closed" (the mistake rounds 8, 10 and 11 each made in
# turn). The plan document maps no `local.` symbol to the attribute it
# reaches, so `config_reaches_arn_of` can only ask whether SOME bucket ARN
# is reached by this configuration at all. Two shapes were built and RUN at
# round 12 to find where that gives out:
#
#   * TWO SYMBOLS, one per slot -- `locals { invoke_source =
#     aws_lambda_function.ingest.arn }` for `source_arn`, with the topic
#     policy's `aws:SourceArn` condition still on the real
#     `local.arns.media_bucket` -- is DENIED (reward 0.0, executed). Not by
#     the bucket slot, which this residual does defeat, but by the SNS
#     half: `bucket_denoting_indirections` only carries symbols that the
#     `source_arn` slot ITSELF holds, so the condition's symbol has no
#     provenance and the document rule fires. The two halves compose.
#   * THREE USES -- the same laundered symbol in BOTH slots, plus one
#     unrelated use of the real bucket ARN elsewhere in the configuration
#     (`output "media_bucket_arn" { value = local.arns.media_bucket }` is
#     enough) -- scores reward 1.0 on hcl_raw, and its awscdk twin scores
#     0.0. THAT is the residual, and it is IRREDUCIBLE from this artifact:
#     the decoy makes `aws_s3_bucket.media ["arn"]` a genuine dependency of
#     the plan, and nothing in `terraform show -json` says which symbol
#     reaches it (a "hidden attribute" refinement -- attributes reached
#     ONLY through locals -- does not separate the two either; it was tried
#     and both artifacts satisfy it).
#
# It is recorded as a standing one-sided CROSS-ARM STRICTNESS difference in
# specs/s3-notification-authoritative-singleton.yaml (the
# `lambda-permission-scoped-to-bucket-tf` assert, the `rego_hints` entry,
# and "oracle must tolerate/defend" point 8), never as a closed hole. It is
# strictly narrower than what round 11 left open -- a single wrong-type
# local, the one-token slip, is now rejected on every arm -- and every
# shape a single symbol can express is decided identically everywhere.
#
# FIXTURE COVERAGE of the two reason sets below, so no clause is asserted
# rather than exercised. `source_arn`: no-reference ->
# `lambda-permission-not-scoped-to-bucket` and
# `lambda-permission-scoped-to-a-different-bucket`; references-something-
# else -> `lambda-permission-scoped-via-an-interpolated-literal`;
# laundered literal -> `lambda-permission-scoped-to-a-laundered-literal`;
# topic-provenance conflict -> `lambda-permission-scoped-to-the-topic-arn-
# behind-a-local` (+ `...-direct-policy-attach`,
# `...-with-an-inline-topic-policy`, `second-lambda-permission-scoped-to-
# the-topic`); no bucket `arn` dependency at all ->
# `lambda-permission-scoped-to-the-lambdas-own-arn-behind-a-local` (round
# 12). `aws_sns_topic_policy.arn`: no-reference ->
# `sns-topic-policy-attached-to-a-different-topic`; missing corroboration
# -> `sns-topic-policy-attached-to-a-lambda-arn-behind-a-local` (round 12).
# Its remaining two clauses -- a DIRECT reference to a resource of another
# type, and a laundered literal in this slot -- ship no fixture of their
# own (they are the attachment-slot mirrors of two `source_arn` clauses
# that do); both were verified at round 12 by evaluating this policy
# against the reference plan with exactly those two edits applied, and both
# emit only their own clause.
#
# FAIL-CLOSED NOTE: if `relevant_attributes` were absent from the plan
# document (a terraform older than the 1.15.8 the arm images pin), every
# `local.`/`var.` hop would be REJECTED rather than waved through, and this
# scenario's own reference solution -- authored in the hoisted map shape --
# would fail `make falsifiability` loudly instead of quietly re-opening the
# leniency.

# ===========================================================================
# ROUND 13 (2026-08-23) -- RESOLUTION REPLACES THE HEURISTIC
# ===========================================================================
#
# Everything rounds 8-12 built in this file's bucket/topic ARN slots was an
# attempt to reason about a SYMBOL because the REFERENT was out of reach:
# `terraform show -json` does not emit `locals`, so `local.arns.media_bucket`
# was a dead end and the only evidence available was circumstantial
# (`relevant_attributes` says the configuration depends on SOME bucket's
# `arn`; the same symbol also appears in a topic slot; the plan does/doesn't
# resolve the slot to a constant). That evidence was configuration-wide, not
# per-slot, and it produced BOTH directions of error -- proven by execution,
# repeatedly (see this file's rounds 8-12 and docs/design/
# conftest-hcl-traversal-spike.md sect 1):
#
#   FALSE PASS -- `media_bucket = aws_lambda_function.ingest.arn` plus one
#     ordinary, correct IAM read grant on the real bucket. The read grant
#     alone put `aws_s3_bucket.media ["arn"]` into `relevant_attributes`, so
#     `config_reaches_arn_of("aws_s3_bucket.")` held while the invoke
#     permission was scoped to the LAMBDA'S OWN ARN. reward 1.0.
#   FALSE FAIL -- the topic ARN hoisted into a local for the policy
#     attachment and spelled DIRECTLY in the notification (both idiomatic,
#     both correct). The "corroboration" clause required the SAME symbol in
#     both slots, so one direct spelling defeated it. reward 0.0, with a deny
#     message that was factually false about the artifact.
#
# The harness now parses the agent's own `.tf` files with `hcl2json` and
# merges them into this policy's `input` under `_hcl` (generator/gen.py::
# build_static_tiers_sh, gated on `oracle.hcl_traversal: true`). The referent
# is reachable, so the heuristics are DELETED rather than left standing
# beside the real thing:
#
#   `config_reaches_arn_of`  + `relevant_arn_resources`   -- deleted
#   `references_bucket` clause 2 (the local./var. leniency) -- deleted
#   `bucket_denoting_indirections` + `indirection_symbols`  -- deleted
#   `topic_denoting_indirections` / `topic_target_indirections` /
#   `topic_arn_slot_references` / `slot_conflicting_symbols`
#   (round 10/11/12's provenance-conflict and corroboration proxies) -- deleted
#   `slot_planned_value` / `slot_is_plan_time_unknown` (the laundered-literal
#   proxy: a laundered literal now simply RESOLVES to a literal) -- deleted
#   `deepest_refs` / `extended_in` (string-prefix dedupe) -- deleted; the
#   library dedupes by SEGMENT ARRAY, which "local.ab" vs "local.abc" makes
#   necessary rather than cosmetic
#
# WHAT REPLACES THEM. `data.cdktn_bench.hcl` (oracles/rego/lib/
# hcl_traversal.rego, copied into this task's tests/ beside this file and
# loaded with a second `-d`). Read that file's header before this section:
# it carries the three-valued contract, the arity gate, and the three
# executed defects that dictate its shape.
#
#   hcl.slot(refs) -> exactly one of
#       {"kind":"resolved",     "referent_path":[...], "referent":"..."}
#       {"kind":"ambiguous",    "candidates":[...],    "reason":"..."}
#       {"kind":"unresolvable", "reason":"..."}
#
# AMBIGUOUS and UNRESOLVABLE both DENY here, naming the symbol and quoting
# what stood in the way. There is no fourth outcome, and `hcl.slot` carries
# the `count(deepest) == 1` ARITY GATE itself so that neither of these two
# twin slots can be shipped without one -- which is exactly what happened to
# the spike prototype (memo sect 5.7: the gate on slot 1, omitted on slot 2,
# an executed silent PASS, and a regression against a fixture already in this
# repo). The gate is `== 1`, in one place, for both slots.
#
# TWO ARMS, ONE POLICY, AND WHY THIS IS NOT AN hcl_raw-ONLY RULE. This file
# also grades terraconstructs. `_hcl` is present only on hcl_raw, and it is
# needed only to resolve `local.` symbols -- a DIRECT reference resolves out
# of the plan's own `.references` list, with no `_hcl` at all. cdktn resolves
# TS variables at synth time and emits no `locals` block (verified across
# five real `cdk.tf.json` documents, spike memo sect 9), so terraconstructs
# only ever takes the direct path and is graded by the identical rule.
# Should an agent ever reach for `TerraformLocal` on that arm, the symbol is
# UNRESOLVABLE and the slot DENIES -- fail-closed and loud, never silent.
#
# SAME-TYPE / WRONG-INSTANCE IS NOW CLOSED, and this is new capability, not
# a re-statement. Resolution answers "what does this symbol point at", which
# for the first time makes "is that the RIGHT one of two buckets" a question
# this policy can ask. It was previously open on ALL THREE ARMS, in BOTH
# spellings, and no fixture covered it:
#
#     locals { arns = { media_bucket = aws_s3_bucket.decoy.arn, ... } }
#     resource "aws_s3_bucket_notification" "media" { bucket = aws_s3_bucket.media.id ... }
#
#   -- an invoke permission scoped to a bucket the notification does not
#   wire, i.e. S3 can never invoke the function. Executed: silent under
#   round 12 (both layers), reward 1.0 on a genuinely broken solution. The
#   DIRECT spelling (`source_arn = aws_s3_bucket.decoy.arn`, no local at
#   all) was silent too -- the existing `lambda-permission-scoped-to-a-
#   different-bucket` fixture does NOT cover it, because its `source_arn` is
#   a zero-reference string literal caught by the arity gate, not by
#   instance discrimination.
#
#   The join is: the slot must resolve to the `.arn` of the SAME resource
#   INSTANCE that this configuration's own `aws_s3_bucket_notification`
#   wires (`bucket` for the bucket half, `topic[*].topic_arn` for the topic
#   half). Keyed on type + configuration label, i.e. the plan address --
#   never on a physical cloud resource name, never on a label this scenario
#   picked (Amendment 29 sect 6 RULING 1). Fixtures:
#   `lambda-permission-scoped-to-a-decoy-bucket-behind-a-local`,
#   `lambda-permission-scoped-to-a-decoy-bucket-directly`,
#   `sns-topic-policy-attached-to-a-decoy-topic-behind-a-local`.
#
#   *** SUPERSEDED AT ROUND 14, AND ITS CENTRAL CLAIM RETRACTED. This
#   paragraph used to read: "DEGRADATION, DECLARED: if the notification's own
#   slot does not itself resolve to exactly one instance ... the rule then
#   falls back to the type-only test rounds 8-12 used and records the
#   degradation in `not_verifiable` ... Every artifact that reaches that
#   fallback is already denied at tier 0 by
#   `exactly-one-notification-resource-per-bucket-tf` /
#   `object-removed-notification-targets-a-topic`."
#
#   THE LAST SENTENCE WAS FALSE. Neither of those tier-0 asserts looks at
#   what the `bucket` argument resolves to -- one counts notification
#   resources, the other whitelists the topic target's event strings -- and
#   an executed artifact that reached the fallback printed `tier0_pass=1`
#   and scored REWARD 1.0 while being genuinely broken. There is no
#   type-only fallback any more: an anchor that cannot be established DENIES.
#   Read the ROUND 14 block further down for the counterexample and for the
#   two positive routes that replaced it. ***
#
# WHAT THIS DELIBERATELY DOES NOT DO. It does not resolve the topic policy
# DOCUMENT as an expression -- a `jsonencode(...)` body is opaque and stays
# opaque. Each reference the plan reports for that document is resolved
# INDIVIDUALLY, and the document check stays what it always was: a POSITIVE
# existence test ("does this document name the bucket the notification
# wires"), not a three-valued slot. The three-valued contract binds
# dedicated single-ARN ARGUMENT slots, which is what the spike memo
# recommends adopting and all it recommends adopting.

# WHAT IS RESIDUAL AFTER ROUND 13 -- the single operator-facing list for
# this file. Stated here rather than scattered, and stated as residual
# rather than as "recorded and therefore fine":
#
#   1. A `count`/`for_each` INDEX ON THE REFERENT is a live FALSE FAIL.
#      `media_bucket = aws_s3_bucket.media[0].arn` is a CORRECT solution and
#      the resolver refuses it (the tokenizer cannot tile a numeric index),
#      so the slot DENIES. It is in the loud direction -- `make
#      falsifiability` catches it the moment a fixture uses it -- but it is
#      a real defect, it is in the corpus at
#      oracles/tests/test_hcl_traversal.py, and it is NOT fixed.
#   2. MODULES are not crossed. `module.x.out` is refused BY NAME. A future
#      `hcl-modules` arm needs a second resolver on top of this one.
#   3. THE POLICY DOCUMENT IS NOT A SLOT and is not three-valued. Each
#      reference in it is resolved individually and the test is positive
#      existence ("does this document name the bucket the notification
#      wires"). A `jsonencode(...)` body is opaque and stays opaque; this
#      does not attempt document-wide expression resolution.
#   4. THE SAME-TYPE/WRONG-INSTANCE RULE IS CLOSED ON ALL THREE ARMS -- it
#      is mirrored into oracles/rego-cfn/ so the closure is not one-sided --
#      BUT SHIPS FIXTURES ON hcl_raw AND awscdk ONLY. terraconstructs is
#      graded by THIS file and therefore runs the same rule, with no fixture
#      exercising it. A COVERAGE gap, not a rule gap -- and coverage gaps
#      are how the last five rounds' holes stayed invisible, so it is named
#      here.
#      ROUND-14 QUALIFIER: "closed" is only true as of round 14. Round 13
#      shipped this same sentence while a type-only fallback silently
#      re-opened it for any artifact whose notification `bucket` argument
#      did not resolve -- reward 1.0 on a genuinely broken solution. That
#      fallback is deleted; see the ROUND 14 block below.
#   7. A NOTIFICATION `topic_arn` THIS RESOLVER CANNOT FOLLOW IS A LOUD
#      FALSE FAIL, by choice. The bucket anchor has a plan-value route (the
#      `bucket` argument takes a NAME, which is plan-time-known), but a
#      topic ARN is provider-computed and absent from the plan, so a
#      `topic_arn` built by an opaque expression, or pasted as a literal
#      ARN string, denies even though the artifact may be correct. It is in
#      the LOUD direction and `make falsifiability` catches it the moment a
#      fixture uses that spelling. The alternative -- accepting on type --
#      is the round-13 hole this round exists to close.
#   8. THE PLAN-VALUE BUCKET ROUTE IS NAME-BASED, so a notification whose
#      `bucket` name matches no bucket this configuration creates (a
#      pre-existing bucket adopted by name, a typo) has no anchor and
#      DENIES. For THIS scenario that is correct -- the ticket asks for a
#      bucket this configuration creates -- but a future ADOPTION scenario
#      reusing this file would need a third route.
#   5. PARSER SKEW between the pinned hcl2json and the pinned terraform is
#      possible in principle. A file terraform accepts and hcl2json rejects
#      is reported as ENGINE_ERROR by the generated script (the run is
#      INVALID, not failed) rather than being charged to the agent.
#   6. THE ENGINE_ERROR HARDENING IS SCOPED TO THIS SCENARIO. Every other
#      scenario in this repo still pipes `opa eval` straight into
#      `jq -e 'length == 0'`, so an aborted evaluation there is still scored
#      as the agent's failure.

# --- fail-closed: the merge ran and found nothing ------------------------
#
# Without this the policy fails OPEN on an empty `_hcl`: every `local.`
# symbol is unresolvable, which denies -- but a solution written with no
# locals at all would sail through on an oracle that cannot read anything.
# Denying outright makes "the resolver had no source" a loud, named outcome.
deny contains msg if {
	hcl.no_source_supplied
	msg := "the tier-1 oracle was handed an EMPTY parsed-HCL document (`input._hcl` is present but has no files in it), so no `local.` symbol in this configuration can be resolved to what it actually names -- denying rather than grading on partial information. This is a harness/toolchain condition (the `*.tf` glob matched nothing, or hcl2json produced nothing), not necessarily a defect in the solution."
}

# ===========================================================================
# ROUND 14 (2026-08-24) -- THE TYPE-ONLY FALLBACK IS DELETED. IT WAS A LIVE
# SILENT PASS, AND ITS STATED MITIGATION WAS FALSE.
# ===========================================================================
#
# WHAT ROUND 13 SHIPPED. `slot_names_arn_of` had TWO clauses: the instance
# join, and a second clause that accepted on resource TYPE alone whenever
# `count(anchors) != 1`. `_names_anchor_instance` had the same escape hatch
# for the topic-policy DOCUMENT test. The degradation was written to
# `not_verifiable`, which the generated static_tiers.sh states, in the
# script itself, "does NOT deny the plan and does NOT affect
# tier1_status/reward".
#
# WHY THAT WAS A HOLE. The anchors are derived from the notification's own
# `bucket` / `topic[*].topic_arn` slot. `count(anchors) != 1` is therefore
# not a rare toolchain condition -- it is reachable by an ORDINARY, VALID
# spelling of the notification's own `bucket` argument, because that
# argument takes a bucket NAME:
#
#     resource "aws_s3_bucket_notification" "media" {
#       bucket = "cdktn-bench-media-ingest-media"   # <- zero references
#       ...
#     }
#
# Executed, in the real hcl_raw image, `--network none`: two buckets
# (`media`, `decoy`), that literal `bucket`, `source_arn =
# aws_s3_bucket.decoy.arn` and an `aws:SourceArn` condition naming the decoy
# -- an artifact in which S3 can NEVER invoke the Lambda -- scored
# tier0_pass=1, tier1_status=PASS, deny `[]`, REWARD 1.0. Reproduced three
# ways: the plain literal; `bucket = local.notif_bucket` with `notif_bucket
# = format("%s", aws_s3_bucket.media.id)`; and the topic half via `topic_arn
# = local.opaque_topic` plus `aws_sns_topic_policy.arn =
# aws_sns_topic.decoy.arn`. `bucket = var.x` reads the same way.
#
# AND THE MITIGATION ROUND 13 CLAIMED WAS FALSE. *** RETRACTION: this file
# stated "Every artifact that reaches that fallback is already denied at
# tier 0 by `exactly-one-notification-resource-per-bucket-tf` /
# `object-removed-notification-targets-a-topic`." IT IS NOT. Both of those
# asserts are jq over `.planned_values`: one counts notification resources,
# the other whitelists the topic target's event strings. NEITHER looks at
# what the `bucket` argument resolves to. Every one of the three
# reproductions above printed `tier0_pass=1`. The same false sentence stood
# in oracles/rego-cfn/.../policy.rego and in the spike memo's sect 5.3, and
# is retracted at all three sites. ***
#
# WHAT REPLACES IT: two POSITIVE routes to the anchor, and a DENY when
# neither establishes one. "I cannot tell which bucket this notification
# wires" is exactly the fail-closed condition the rest of this oracle is
# built around, and it is now graded the same way every other unresolvable
# slot is -- as a deny naming what could not be resolved, not as a widening.
# Nothing here is gated on `count(anchors) != 1` any more.

notification_resource_configs := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket_notification"
]

# A SET OF PAIRS, not an object keyed by address, for the reason the shared
# library's header gives at length (rule 3): an object rule that data can key
# raises `eval_conflict_error` the moment two clauses bind one key to two
# values, and an aborted evaluation scores a correct solution 0.0 with no
# message at all. A set cannot conflict.
#
# ROUTE 1 -- the `bucket` argument REFERENCES a bucket this configuration
# creates. This is the ordinary spelling (`bucket = aws_s3_bucket.media.id`)
# and it goes through the same total `hcl.slot` reader, and therefore the
# same arity gate, as the two graded slots.
notification_bucket_anchor contains [addr, inst] if {
	some r in notification_resource_configs
	addr := r.address
	v := hcl.slot(object.get(r, ["expressions", "bucket", "references"], []))
	v.kind == "resolved"
	v.referent_path[0] == "aws_s3_bucket"
	inst := v.instance
}

# ROUTE 2 -- POSITIVELY ESTABLISHED FROM THE PLAN, not a widening. The
# `bucket` argument of `aws_s3_bucket_notification` takes a bucket NAME, so
# writing that name -- as a literal, or through any expression terraform can
# reduce at plan time -- is valid, ordinary and CORRECT. Refusing it outright
# would be a false FAIL on a good solution. Instead the anchor is taken from
# the PLAN's own values: the notification's planned `bucket` string must be
# the planned `bucket` name of EXACTLY ONE `aws_s3_bucket` this
# configuration creates.
#
# This is a positive identification of one instance, not a fallback that
# accepts anything: `count == 1` is required, a plan-time-UNKNOWN `bucket`
# has no `values.bucket` at all and matches nothing, and a name that belongs
# to no bucket in this plan (a pre-existing bucket, a typo) matches nothing
# either. All three of those land in the DENY below.
notification_bucket_anchor contains [addr, inst] if {
	some r in notification_resource_configs
	addr := r.address
	name := planned_bucket_argument(addr)
	matches := buckets_planned_named(name)
	count(matches) == 1
	some inst in matches
}

planned_bucket_argument(addr) := n if {
	some p in planned_resources
	p.address == addr
	n := object.get(p, ["values", "bucket"], null)
	is_string(n)
}

# ROUND 15: an instance identity, INCLUDING the `for_each`/`count` key, so
# route 2 keys on exactly what `hcl.instance_of` now produces for route 1.
# `terraform show -json` puts that key in `.index` on each planned instance
# (verified: `{"address":"aws_s3_bucket.b[\"...-decoy\"]", "name":"b",
# "index":"...-decoy"}`), so the two routes agree per INSTANCE rather than
# per resource BLOCK. Keying on `[type, name]` alone -- what this returned
# before -- collapsed every key of one `for_each` block into one anchor and
# was half of the executed reward-1.0 wrong-instance pass.
buckets_planned_named(name) := {inst |
	some p in planned_resources
	p.type == "aws_s3_bucket"
	object.get(p, ["values", "bucket"], null) == name
	inst := _planned_instance(p)
}

# The plan-side twin of `hcl.instance_of`: `["aws_s3_bucket","b","media"]`
# for a `for_each` instance, `["aws_s3_bucket","media"]` for a plain one.
# A NUMERIC `count` index is a number in the plan and is stringified here so
# it can never silently equal a string key of the same digits.
_planned_instance(p) := [p.type, p.name, p.index] if {
	is_string(p.index)
} else := [p.type, p.name, sprintf("%v", [p.index])] if {
	p.index
} else := [p.type, p.name]

notification_bucket_instances := {inst |
	some [_, inst] in notification_bucket_anchor
}

# Only the notification's own `topic[*].topic_arn` is used as the topic
# anchor -- not a subscription's `topic_arn`. It is the slot this scenario's
# tier-0 `object-removed-notification-targets-a-topic` already requires to
# exist, and every solution that wires the audit topic at all has it,
# whichever policy shape it chose.
#
# THERE IS NO ROUTE 2 HERE, and that asymmetry is deliberate rather than an
# oversight: `topic_arn` takes an ARN, and the ARN of a topic this
# configuration creates is provider-computed, so it is plan-time UNKNOWN and
# `.values.topic[*].topic_arn` is absent from the plan (verified on this
# scenario's own reference plan). There is no plan-side value to identify an
# instance by. A topic_arn this resolver cannot follow therefore DENIES --
# see the residual list at the top of this file, item 7.
# ROUND 15: the tuple carries the BLOCK INDEX. It used to be
# `[addr, inst]`, and the gate below (`_has_topic_anchor`) was satisfied if
# ANY block of a notification resolved -- so a second `topic` block whose
# `topic_arn` this resolver cannot follow contributed no instance and was
# never mentioned again. Per-block is the only granularity at which "every
# topic this notification wires is graded" is even statable.
notification_topic_anchor contains [addr, i, inst] if {
	some r in notification_resource_configs
	addr := r.address
	some i, t in object.get(r, ["expressions", "topic"], [])
	v := hcl.slot(object.get(t, ["topic_arn", "references"], []))
	v.kind == "resolved"
	v.referent_path[0] == "aws_sns_topic"
	inst := v.instance
}

notification_topic_instances := {inst |
	some [_, _, inst] in notification_topic_anchor
}

# --- the anchors are GATING: no anchor, no grade, and a loud deny ---------
#
# Quantified PER NOTIFICATION RESOURCE, so the message names the resource
# whose argument could not be resolved rather than reporting a set-level
# count. Each message states facts about the artifact -- the slot's own
# verdict text and the plan's own value -- and asserts no conclusion the
# artifact could contradict (Amendment 29 sect 6 RULING 3).

_has_bucket_anchor(addr) if {
	some [a, _] in notification_bucket_anchor
	a == addr
}

_has_topic_anchor(addr) if {
	some [a, _, _] in notification_topic_anchor
	a == addr
}

_topic_block_resolves(addr, i) if {
	some [a, j, _] in notification_topic_anchor
	a == addr
	j == i
}

# EVERY `topic` block is gated, not just the first one that happens to
# resolve. A block whose `topic_arn` cannot be followed names a topic this
# oracle cannot check a policy against, and an unchecked topic must never
# read as a checked one.
deny contains msg if {
	some r in notification_resource_configs
	some i, t in object.get(r, ["expressions", "topic"], [])
	not _topic_block_resolves(r.address, i)
	refs := object.get(t, ["topic_arn", "references"], [])
	msg := sprintf(
		"%s: its `topic` block #%d does not name an aws_sns_topic this configuration creates, so WHICH topic that block wires -- and therefore which topic must carry an sns:Publish policy -- cannot be established. Its `topic_arn` reference list %v reads as: %s. A topic ARN is provider-computed and therefore plan-time-unknown, so unlike the `bucket` argument there is no planned value to identify a topic by: write `topic_arn = aws_sns_topic.<name>.arn`, or a `local.` symbol this resolver can follow to it.",
		[r.address, i, refs, _slot_label(hcl.slot(refs))],
	)
}

# TOTAL: quotes the plan's own value for the argument, or says it is not a
# plan-time-known string, without claiming which.
_planned_bucket_argument_label(addr) := sprintf("`%v`", [planned_bucket_argument(addr)]) if {
	planned_bucket_argument(addr)
} else := "not a plan-time-known string (absent, or computed only at apply time)"

# EVERY ARGUMENT OF THIS MESSAGE IS TOTAL, and that is load-bearing rather
# than tidy. A deny rule whose `msg` expression goes UNDEFINED does not
# deny -- it silently does not fire, which is precisely the failure class
# this round exists to remove. The first draft of this rule read
# `hcl.slot(...).reason` (absent on a `resolved` verdict) and
# `count(buckets_planned_named(planned_bucket_argument(addr)))` (undefined
# when the planned value is not a string): BOTH went undefined on an
# executed counterexample, and the diagnostic deny vanished while the two
# slot denies happened to carry the score. Every helper below has an
# unconditional `else`.
deny contains msg if {
	some r in notification_resource_configs
	not _has_bucket_anchor(r.address)
	msg := sprintf(
		"%s: this configuration's own notification resource does not identify exactly one of the aws_s3_bucket resources this configuration creates, so WHICH bucket the invoke permission and the topic policy must be scoped to cannot be established -- and this oracle refuses to fall back to grading them by resource TYPE alone, which cannot tell two buckets apart. Two routes were tried and both failed. (1) Its `bucket` argument's reference list %v reads as: %s. (2) Its planned `bucket` value is %s; that matches the planned `bucket` name of %d of the %d aws_s3_bucket resource(s) in this plan (%v). Write `bucket = aws_s3_bucket.<name>.id`, or a bucket name that is plan-time-known and belongs to exactly one bucket this configuration creates.",
		[
			r.address,
			object.get(r, ["expressions", "bucket", "references"], []),
			_slot_label(hcl.slot(object.get(r, ["expressions", "bucket", "references"], []))),
			_planned_bucket_argument_label(r.address),
			count(_planned_bucket_matches(r.address)),
			count([b | some b in planned_resources; b.type == "aws_s3_bucket"]),
			sort([b.address | some b in planned_resources; b.type == "aws_s3_bucket"]),
		],
	)
}

_planned_bucket_matches(addr) := buckets_planned_named(planned_bucket_argument(addr)) if {
	planned_bucket_argument(addr)
} else := set()

deny contains msg if {
	some r in notification_resource_configs
	not _has_topic_anchor(r.address)
	msg := sprintf(
		"%s: none of this notification resource's `topic` blocks names an aws_sns_topic this configuration creates, so WHICH topic the aws_sns_topic_policy must be attached to cannot be established -- and this oracle refuses to fall back to grading the attachment by resource TYPE alone, which cannot tell two topics apart. Its `topic[*].topic_arn` slots resolve as: %v. A topic ARN is provider-computed and therefore plan-time-unknown, so unlike the `bucket` argument there is no planned value to identify a topic by: write `topic_arn = aws_sns_topic.<name>.arn`, or a `local.` symbol this resolver can follow to it.",
		[r.address, _topic_arn_slot_labels(r)],
	)
}

_topic_arn_slot_labels(r) := sort([label |
	some t in object.get(r, ["expressions", "topic"], [])
	refs := object.get(t, ["topic_arn", "references"], [])
	v := hcl.slot(refs)
	label := sprintf("%v -> %s", [refs, _slot_label(v)])
])

_slot_label(v) := v.referent if {
	v.kind == "resolved"
} else := sprintf("<%s: %s>", [v.kind, v.reason])

# --- the ONE acceptance test both dedicated single-ARN slots use ----------
#
# ONE clause. The second clause round 13 shipped -- accept on resource TYPE
# alone when `count(anchors) != 1` -- is DELETED, not narrowed; see the ROUND
# 14 block above for the executed reward-1.0 counterexample it allowed. The
# precise claim, stated no wider than it is: this rule now accepts a slot ONLY
# if the instance it names is one of the instances the artifact's own
# notification resources identify. There is no remaining clause that accepts
# on resource TYPE alone, and `anchors` is never widened -- an artifact whose
# notification identifies no single instance is DENIED by the two
# `notification_resource_configs` rules above rather than graded loosely here.
# ROUND 15: `v.attr_path` (the attribute path RELATIVE TO the resource
# instance) replaces the old `count(referent_path) >= 3` + `attr_of` pair,
# and `v.instance` replaces `hcl.instance_of(v.referent_path)`. Both changes
# are the same change: the segment array cannot tell `.foo` from `["foo"]`,
# so reading the instance off it collapsed every `for_each` key of one
# resource block into a single instance and let a permission scoped to the
# DECOY bucket score 1.0. `v.instance` is derived where the bracket
# information still exists and carries the key.
slot_names_arn_of(v, type_prefix, anchors) if {
	v.kind == "resolved"
	v.referent_path[0] == type_prefix
	v.attr_path == ["arn"]
	v.instance in anchors
}

# --- the reason, TOTAL by `else` chain -----------------------------------
#
# Rounds 8-12 built the deny message out of a SET of independently-firing
# `..._reason` partial rules, which has exactly the failure mode this whole
# round is about: if no clause happens to match, the message is empty and
# the reader learns nothing about why the artifact was denied. An ordered
# `else` chain terminating in an unconditional catch-all cannot do that --
# every verdict produces exactly one reason, and exactly one clause can
# produce it (which also makes an `eval_conflict_error` between two
# overlapping clauses impossible; see the library header for why that
# matters more than it sounds).
#
# Every clause states a fact about the artifact and quotes it. None asserts
# a conclusion the artifact could contradict (RULING 3).
slot_reason(v, type_prefix, anchors) := r if {
	v.kind == "ambiguous"
	r := sprintf("%s -- resolution refuses to pick one, so this slot is not accepted (candidates: %v)", [v.reason, object.get(v, "candidates", [])])
} else := r if {
	v.kind == "unresolvable"
	r := v.reason
} else := r if {
	v.kind == "resolved"
	v.referent_path[0] != type_prefix
	r := sprintf("it resolves to `%s`, which is not an attribute of any `%s` resource this configuration creates", [v.referent, type_prefix])
} else := r if {
	v.kind == "resolved"
	count(v.attr_path) == 0
	r := sprintf("it resolves to `%s`, which names the `%s` instance `%s` but no attribute of it -- an ARN slot needs `.arn`", [v.referent, type_prefix, hcl.instance_addr(v.instance)])
} else := r if {
	v.kind == "resolved"
	v.attr_path != ["arn"]
	r := sprintf("it resolves to `%s` -- the `%s` attribute of `%s`, not its `arn`", [v.referent, concat(".", v.attr_path), hcl.instance_addr(v.instance)])
} else := r if {
	# ROUND 15: split on `count(anchors) > 0` / `== 0`, NOT on `== 1` /
	# `!= 1`. Round 14 wrote the second clause for `!= 1` and said "there is
	# nothing to check WHICH instance this argument names against". That was
	# true when the only reachable non-1 value was 0 -- but this round makes
	# N>1 a LEGITIMATE, GRADED shape (two wired topics, both carrying a
	# policy), and in that shape the slot IS checked against the set and
	# rejected by it. Emitting "there is nothing to check against" there
	# would be a message the artifact contradicts (Amendment 29 RULING 3),
	# which is the failure mode this file has been corrected for three
	# rounds running. Each clause below now states only what is true of the
	# case it fires on.
	v.kind == "resolved"
	count(anchors) > 0
	r := sprintf("it resolves to `%s`, i.e. the `arn` of `%s`, which is not among the %d `%s` instance(s) this configuration's own aws_s3_bucket_notification resources wire (%v) -- so this argument names a resource that is not on the notification path at all", [v.referent, hcl.instance_addr(v.instance), count(anchors), type_prefix, sort([hcl.instance_addr(a) | some a in anchors])])
} else := r if {
	# ROUND 14: this used to be the type-only ACCEPT clause of
	# `slot_names_arn_of` (an executed silent PASS, see the ROUND 14 block
	# above). It is now a REFUSAL with a reason. The companion
	# `notification_resource_configs` deny states which argument could not
	# be resolved; this states the consequence for THIS slot.
	v.kind == "resolved"
	count(anchors) == 0
	r := sprintf("it resolves to `%s`, and this configuration's own aws_s3_bucket_notification resources identify NO `%s` instance at all, so there is nothing to check WHICH instance this argument names against -- the slot is refused rather than accepted on resource TYPE alone, because a type test cannot tell two `%s` resources apart", [v.referent, type_prefix, type_prefix])
} else := sprintf("its resolved verdict %v is not one this rule accepts, and no clause of `slot_reason` explains why -- this is the fail-closed catch-all, not a judgement about the artifact", [v])

# --- slot 1: aws_lambda_permission.source_arn ----------------------------

source_arn_verdict(rp) := hcl.slot(source_arn_references(rp))

references_bucket(rp) if {
	slot_names_arn_of(source_arn_verdict(rp), "aws_s3_bucket", notification_bucket_instances)
}

# --- ROUND 16: `source_arn = each.value.arn` on a `for_each` permission ---
#
# *** EXECUTED FALSE FAIL THIS CLOSES, with a RULING-3 message. `for_each`
# on the GRADED `aws_lambda_permission` was an UNDECLARED live false FAIL:
# the only natural `source_arn` spelling for one is `each.value.arn`, the
# resolver refused it as a reserved root, and the refusal asserted that
# `each` "name[s] no resource at all" about an artifact where `each.value`
# IS the bucket instance the notification wires. Executed, real terraform
# 1.15.8 plan:
#
#   resource "aws_s3_bucket" "b" { for_each = toset(["media"]) ... }
#   resource "aws_lambda_permission" "allow_s3_invoke" {
#     for_each = aws_s3_bucket.b
#     principal = "s3.amazonaws.com"; source_arn = each.value.arn }
#   -> TIER1=FAIL, reward 0.0
#
# Memo residual 10 declared the `count`/`for_each` join FIXED and reasoned
# explicitly about "a `for_each`-expanded permission [with] N planned
# instances"; this case was in neither the memo's nor the spec's residual
# list, which named only the NUMERIC index on the REFERENT and module
# boundaries. Both are corrected.
#
# WHY THIS IS SOUND AND NOT A WIDENING. `each.value` denotes an instance of
# whatever `for_each` iterates. `hcl.for_each_referent` returns a referent
# ONLY when the block's `for_each` argument is EXACTLY one whole-resource
# reference (`for_each = aws_s3_bucket.b`) -- a `toset([...])`, a `for`
# comprehension, a `merge()` or a conditional all fail its `count(segs) ==
# 2` test and leave the slot UNRESOLVABLE, i.e. still denied and still loud.
# When it does return one, `each.value` is an instance of THAT resource with
# THAT resource's own instance keys, and terraform's plan gives the keys
# directly as `.index` on each planned instance of the permission.
#
# THE QUANTIFIER IS "EVERY INSTANCE", not "some". A `for_each` permission
# expands to N grants; accepting it because ONE of them lands on a wired
# bucket would be exactly the same silent pass the round-15 per-wired-bucket
# rule closed from the other direction. `count(insts - anchors) == 0` says
# every instance this block expands to is scoped to a wired bucket.
_planned_instance_keys(rtype, rname) := {k |
	some p in planned_resources
	p.type == rtype
	p.name == rname
	k := sprintf("%v", [p.index])
}

each_value_arn_instances(rp) := insts if {
	v := source_arn_verdict(rp)
	v.kind == "unresolvable"
	v.symbol == "each.value.arn"
	ref := hcl.for_each_referent(rp.type, rp.name)
	segs := hcl.parse_traversal(ref)
	keys := _planned_instance_keys(rp.type, rp.name)
	count(keys) > 0
	insts := {[segs[0], segs[1], k] | some k in keys}
}

references_bucket(rp) if {
	insts := each_value_arn_instances(rp)
	count(insts - notification_bucket_instances) == 0
}

# What a permission's `source_arn` resolved to, for the deny messages. The
# `each.value` route reports the INSTANCES it expands to; every other route
# reports the slot verdict's own label. Total by `else` chain.
_source_arn_label(rp) := l if {
	insts := each_value_arn_instances(rp)
	l := sprintf("each.value.arn over `for_each = %s` -> %v", [
		hcl.for_each_referent(rp.type, rp.name),
		sort([hcl.instance_addr(i) | some i in insts]),
	])
} else := _slot_label(source_arn_verdict(rp))

# The REASON a permission's `source_arn` was not accepted. The `each.value`
# route needs its own clause: `slot_reason` is handed the slot verdict alone
# and would report "no caller resolved it", which is FALSE of an artifact
# where the caller DID resolve it and rejected the instances it found
# (RULING 3, caught on this round's own first cut -- executed on a two-key
# `for_each` bucket with only one key wired). Total by `else` chain.
_source_arn_reason(rp) := r if {
	insts := each_value_arn_instances(rp)
	bad := insts - notification_bucket_instances
	count(bad) > 0
	r := sprintf("its `source_arn` is `each.value.arn`, and this block's `for_each = %s` expands it to %v -- of which %v are NOT among the %d bucket instance(s) this configuration's own aws_s3_bucket_notification resources wire (%v). A `for_each` permission grants EVERY instance it expands to, so every one of them has to land on a wired bucket", [
		hcl.for_each_referent(rp.type, rp.name),
		sort([hcl.instance_addr(i) | some i in insts]),
		sort([hcl.instance_addr(i) | some i in bad]),
		count(notification_bucket_instances),
		sort([hcl.instance_addr(a) | some a in notification_bucket_instances]),
	])
} else := slot_reason(source_arn_verdict(rp), "aws_s3_bucket", notification_bucket_instances)

deny contains msg if {
	some rp in s3_invoke_permissions
	not references_bucket(rp)
	msg := sprintf(
		"%s: principal is s3.amazonaws.com, but this plan does not show the grant scoped to the bucket this configuration's own notification resource wires -- %s. (source_arn is resolved to a single referent: a direct reference is taken from the plan, and a `local.` symbol is followed through the parsed .tf `locals` table -- see tests/hcl_traversal.rego. A slot holding zero or more than one reference, or a symbol whose referent cannot be determined, is refused rather than guessed at.)",
		[rp.address, _source_arn_reason(rp)],
	)
}

# --- ROUND 15: GRADE PER WIRED BUCKET, NOT PER PERMISSION -----------------
#
# The exact twin of the per-wired-topic rule below, and it exists for the
# same reason: `references_bucket` asks whether a permission names SOME
# member of the anchor set, which says nothing about whether the bucket that
# actually invokes the Lambda has a permission at all. Two buckets, each
# with its own notification, both wiring the same Lambda, and ONE permission
# scoped to the first would leave the second's invocations denied by Lambda
# while every per-permission rule passed.
#
# Only buckets whose notification actually has a `lambda_function` block
# need one -- a bucket wired for the topic alone never invokes the Lambda,
# so requiring a permission for it would be a false FAIL.
_notification_wires_a_lambda(addr) if {
	some r in notification_resource_configs
	r.address == addr
	some _ in object.get(r, ["expressions", "lambda_function"], [])
}

notification_lambda_bucket_instances := {inst |
	some [addr, inst] in notification_bucket_anchor
	_notification_wires_a_lambda(addr)
}

_bucket_has_invoke_permission(inst) if {
	some rp in s3_invoke_permissions
	slot_names_arn_of(source_arn_verdict(rp), "aws_s3_bucket", {inst})
}

_bucket_has_invoke_permission(inst) if {
	some rp in s3_invoke_permissions
	inst in each_value_arn_instances(rp)
}

deny contains msg if {
	some inst in notification_lambda_bucket_instances
	not _bucket_has_invoke_permission(inst)
	msg := sprintf(
		"%s: this configuration's own aws_s3_bucket_notification wires this bucket to a lambda_function target, but no aws_lambda_permission with principal s3.amazonaws.com in this plan is scoped to it -- S3 cannot invoke the function for this bucket. The s3.amazonaws.com-principal'd permissions in this plan resolve their `source_arn` to: %v.",
		[
			hcl.instance_addr(inst),
			sort([sprintf("%s -> %s", [rp.address, _source_arn_label(rp)]) |
				some rp in s3_invoke_permissions
			]),
		],
	)
}

# Fail-closed: a bucket exists but no s3.amazonaws.com-principal'd Lambda
# permission exists anywhere in the plan at all.
deny contains msg if {
	count(s3_buckets) > 0
	count(s3_invoke_permissions) == 0
	msg := sprintf(
		"an aws_s3_bucket exists, but no aws_lambda_permission resource granting principal s3.amazonaws.com exists anywhere in the plan -- S3 cannot invoke the Lambda function without one. What this rule actually looked at: the plan's `aws_lambda_permission` instances and their principals are %v, and the configuration's `aws_lambda_permission` blocks are %v. (RULING 3: those two lists are quoted rather than summarised so this message cannot assert something the artifact contradicts -- an earlier revision of this rule fired on a plan that DID contain an s3.amazonaws.com permission, because the config<->plan join was on `.address` and a `count` meta-argument broke it.)",
		[
			sort([sprintf("%s -> %v", [r.address, object.get(r, ["values", "principal"], null)]) |
				some r in planned_resources
				r.type == "aws_lambda_permission"
			]),
			sort([r.address | some r in permission_configs]),
		],
	)
}

# --- SNS topic-policy scoping (this scenario's own new rule) --------------
#
# TWO POLICY-DOCUMENT AUTHORING IDIOMS, verified directly against real
# `cdktn synth` + `terraform plan` runs of this scenario's own reference
# solutions. terraconstructs' `TopicBase.addToResourcePolicy()` does NOT emit
# a raw `jsonencode(...)`-shaped `policy` argument the way the hand-written
# hcl_raw reference solution does -- it composes via a
# `data "aws_iam_policy_document"` and sets
# `policy = data.aws_iam_policy_document.<name>.json`, so
# `aws_sns_topic_policy.<addr>.expressions.policy.references` contains ONLY
# `["data.aws_iam_policy_document.<name>.json",
# "data.aws_iam_policy_document.<name>"]` -- no `aws_s3_bucket.*` entry at
# that hop at all.
#
# *** ROUND-16 RETRACTION, carried here rather than deleted, because the
# mechanism this paragraph used to describe is gone and the sentence that
# described it was load-bearing in a REWARD-1.0 LAUNDER. Until round 16 the
# indirection was followed by `policy_references_deep` + `all_references`: a
# FLAT UNION of every `.references` list found ANYWHERE inside the data
# source's `.expressions` tree, unioned with the direct references, and the
# grading question was "does any member of that union resolve to the wired
# bucket". That union DELIBERATELY THREW AWAY POSITION -- the header used to
# call it "a generic recursive walk ... instead of hand-picking one fixed
# path" and treat that as a virtue. It is not a virtue: with no position, a
# bucket reference interpolated into a statement's `Sid` string is
# indistinguishable from one standing in an `aws:SourceArn` condition, and
# ONE such line laundered a checked-in 0.0 fixture to REWARD 1.0 (executed;
# the transcript is in the block above `_statements`).
# `policy_references_deep`, `all_references` and `_names_anchor_instance`
# are DELETED, not left beside their replacement. The position IS
# hand-picked now -- `statement[*].condition[*]` for the data-source shape,
# `Statement[*].Condition.<op>["aws:SourceArn"]` for the structured shape --
# because the graded question is a question about a position. ***

topic_policy_configs := [r |
	some r in configured_resources
	r.type == "aws_sns_topic_policy"
]

# ROUND-2 CORRECTION (see this file's header): the OTHER accepted shape --
# `policy` set directly on `aws_sns_topic` (the provider's own first-listed
# example for this exact wiring). `r.expressions.policy` is only present in
# `.configuration` when the argument is actually set in HCL (an
# `aws_sns_topic` with no `policy` block has no `policy` key under
# `.expressions` at all), so this list is naturally empty for a topic that
# uses the standalone `aws_sns_topic_policy` shape instead -- the two lists
# are disjoint per topic, never double-counted.
inline_policy_topics := [r |
	some r in configured_resources
	r.type == "aws_sns_topic"
	r.expressions.policy
]

# *** ROUND 17: `data_resources_by_addr` is DELETED, not left beside the
# real thing. It indexed the PLAN's `data` resources so route 3 could read a
# `data "aws_iam_policy_document"` out of `expressions`. That source cannot
# answer the question: the plan reports a `condition`'s `values` as a flat
# `.references` list with every LITERAL DROPPED, so a value list holding a
# wildcard beside the wired bucket is indistinguishable there from one
# holding the bucket alone (executed at REWARD 1.0). Route 3 now reads the
# same parsed .tf source routes 1 and 2 read, via `hcl.data_blocks`. ***

# ROUND 16: `all_references(value)` (every `.references` list found anywhere
# under an arbitrarily-nested value) and `policy_references_deep(tp)` (its
# union with the direct list) are DELETED. They are the position-destroying
# union the retraction above describes; `granting_statements` reads the
# `data "aws_iam_policy_document"` shape at its real path instead. What
# survives is the two SLOT reference lists, which are genuine slots.
policy_references(tp) := object.get(tp.expressions.policy, "references", [])

arn_references(tp) := object.get(tp.expressions.arn, "references", [])

# --- slot 2: aws_sns_topic_policy.arn (the ATTACHMENT slot) --------------
#
# The twin of the bucket slot above, and written from the same three
# helpers on purpose. The spike memo's sect 5.7 finding is that two twin
# rules twenty lines apart drifted -- one carried the arity gate, one did
# not, and the one that did not was an executed silent PASS. Both now share
# `hcl.slot` (which IS the gate), `slot_names_arn_of` and `slot_reason`, so
# there is nothing left to drift.
#
# WHAT THIS FIXES that round 12 got wrong (executed, spike memo sect 1
# defect (b)): round 12 accepted a hoisted `arn` only if the SAME SYMBOL
# also appeared in a topic-wiring slot. A solution that hoisted the topic
# ARN for this slot and spelled the notification's `topic_arn` DIRECTLY --
# both idiomatic, both correct -- was denied, with a message claiming
# "nothing in this plan connects that symbol to an aws_sns_topic this
# configuration creates" about an artifact whose symbol demonstrably held
# `aws_sns_topic.audit.arn`. Resolution compares REFERENTS, so the mixed
# spelling now passes and the residual round 12 recorded is closed, not
# documented. It is shipped as a fixture
# (`sns-topic-policy-hoisted-arn-with-a-direct-notification-topic-arn`
# under solution/broken/ is its NEGATIVE twin; the positive is exercised by
# the falsifiability gate through the reference solution's own spelling).
topic_arn_verdict(tp) := hcl.slot(arn_references(tp))

# --- ROUND 16: WHICH policies this scenario is entitled to grade ---------
#
# *** EXECUTED FALSE FAIL THIS CLOSES, with a message the artifact flatly
# refutes (Amendment 29 sect 6 RULING 3). Both topic-policy rules used to be
# quantified over EVERY `aws_sns_topic_policy` in the configuration. A
# CORRECT solution that also declares an unrelated topic -- an ops/alarms
# topic with its own policy, which has nothing to do with the notification
# path -- was DENIED with:
#
#   "aws_sns_topic_policy.ops: nothing in this topic policy scopes
#    sns:Publish to the bucket this configuration's own notification
#    resource wires ... Without an aws:SourceArn-shaped condition naming
#    this bucket, any S3 bucket in any account can publish to the audit
#    topic."
#
# The artifact's `aws_sns_topic_policy.audit` demonstrably DID carry that
# condition, so the final clause was false OF THAT ARTIFACT. Executed on a
# real terraform 1.15.8 plan; TIER1=FAIL, reward 0.0, on a solution that
# does everything the ticket asks. ***
#
# The narrowing below is the whole fix, and it is safe precisely BECAUSE
# `_wired_topic_has_policy` (round 15) already supplies per-wired-topic
# coverage from the other direction: every topic the notification wires must
# have SOME accepted policy shape attached. So a policy attached to a decoy,
# to a lambda ARN, or to nothing this resolver can follow is still caught --
# by the topic it leaves uncovered, which is a statement about the artifact
# that is true -- while a policy on a topic that is simply not on the
# notification path is left alone, which is also true.
_policy_topic_instance(tp) := inst if {
	v := topic_arn_verdict(tp)
	v.kind == "resolved"
	v.referent_path[0] == "aws_sns_topic"
	v.attr_path == ["arn"]
	inst := v.instance
}

graded_topic_policies := [tp |
	some tp in topic_policy_configs
	_policy_topic_instance(tp) in notification_topic_instances
]

# The inline mirror. An inline `policy` is set on the `aws_sns_topic` BLOCK,
# so it is graded when that block expands to a wired instance -- matched on
# type+label without the key, exactly as `_inline_policy_covers` does and
# for the same reason.
graded_inline_topics := [t |
	some t in inline_policy_topics
	some inst in notification_topic_instances
	t.type == inst[0]
	t.name == inst[1]
]

# *** DELETED AT ROUND 16, not narrowed and not left beside its replacement:
# the per-policy `references_this_topic` DENY ("this plan does not show this
# policy attached to the aws_sns_topic this configuration's own notification
# resource wires"). It is the rule that produced the false FAIL above, and
# narrowing it to `graded_topic_policies` would make it vacuous by
# construction -- it would deny, for not being attached to a wired topic,
# exactly the policies selected for being attached to one. Its coverage is
# carried in full by `_wired_topic_has_policy` below, whose message names
# the uncovered TOPIC (a fact) instead of accusing a POLICY of being
# misdirected (an inference the artifact can refute). The `arn` verdict of
# every policy that failed to resolve is folded into that message so the
# diagnostic is not lost -- see `_topic_policy_attachment_report`. ***

# --- the topic policy DOCUMENT: POSITIONAL, per granting statement -------
#
# *** THE EXECUTED REWARD-1.0 LAUNDER THIS ROUND EXISTS FOR. Until round 16
# this was a MENTION test: `policy_document_names_the_bucket` required only
# that SOME reference ANYWHERE in the whole policy document resolve to the
# wired bucket instance. There was no position requirement of any kind, so a
# reference in a `Sid` string satisfied it. Executed, image built from this
# task's own Dockerfile, `docker run --network none`, generated
# tests/static_tiers.sh verbatim:
#
#   solution/broken/sns-topic-policy-not-scoped-to-bucket, UNMODIFIED
#     -> tier0_pass=1 tier1_status=FAIL, REWARD 0.0
#   the SAME file with ONE line changed --
#     Sid = "AllowS3Publish"  ->  Sid = "AllowS3Publish${aws_s3_bucket.media.id}"
#     -> tier0_pass=1 tier1_status=PASS, REWARD 1.0, deny []
#
# The laundered artifact still grants `s3.amazonaws.com` `sns:Publish` with
# NO `aws:SourceArn` condition -- the exact defect that fixture's own header
# describes. The same one-line edit also flipped the inline-policy fixture.
# This re-opened the round-9 finding in a new spelling, and the CFN mirror
# had the identical shape, so it was cross-arm. ***
#
# WHAT REPLACES IT, and why it is a real position test rather than a
# narrower mention test. The graded question is now, per STATEMENT:
#
#   for every statement of this document that grants the S3 service
#   principal sns:Publish, does that statement carry a condition on
#   `aws:SourceArn` whose value resolves to the bucket instance this
#   configuration's own notification resource wires?
#
# "For every granting statement", not "for some statement anywhere", so a
# scoped statement sitting next to an unconditioned one does not launder the
# unconditioned one either.
#
# THE DOCUMENT HAS TO BE READ STRUCTURALLY FOR THAT TO BE STATABLE AT ALL,
# and `terraform show -json` does not carry the structure: a
# `jsonencode({...})` argument is one opaque expression whose references it
# reports as a FLAT UNION with no position. Three routes are read, and a
# document none of them can read is DENIED naming the shape rather than
# graded on a mention (see `_policy_document_unreadable` below):
#
#   1. `policy = jsonencode({...})` -- the harness re-parses the body with
#      THE SAME hcl2json (generator/gen.py::build_hcl_merge_block) and the
#      shared library exposes it as `hcl.resource_jsonencode`. Every leaf
#      comes back as raw `"${...}"` source; nothing is evaluated.
#   2. `policy = "<literal JSON>"` -- a heredoc or plain string. Parsed with
#      `json.unmarshal`, GUARDED by `json.is_valid` (an unguarded
#      `json.unmarshal` on a non-JSON string RAISES, and a runtime error
#      aborts the whole evaluation, empties stdout and scores a correct
#      solution 0.0 with no deny message -- the same class of defect as the
#      dot-joined key the shared library's header retracts).
#   3. `policy = data.aws_iam_policy_document.x.json` -- the position is in
#      the PLAN's own configuration, at `statement[*].condition[*]`, which
#      is where terraconstructs' synthesis puts it. Verified against a real
#      terraform 1.15.8 plan.
#
# All three funnel into ONE acceptance: a REFERENCE LIST per SourceArn
# condition position, graded by `hcl.slot` + `slot_names_arn_of` -- the same
# audited arity gate and the same instance-discriminating acceptance test
# the two dedicated ARN slots use. There is no second acceptance path.

# Statement may be a single object or a list of them; IAM accepts both.
#
# *** ROUND 17. A `Statement` key that is PRESENT but is not a statement
# object / list of statement objects (`Statement = local.stmts`, hoisted
# into `locals` -- the ordinary DRY spelling) used to fall through this
# rule's `else := set()` and be graded as "this document has 0 granting
# statements", which is a claim the artifact refutes: the document has a
# statement, this reader could not read it. It is now reported by
# `_statement_list_unreadable` and routed to the LOUD "cannot read the
# STRUCTURE of this document" deny instead. See Amendment 29 RULING 3. ***
_statements(d) := ss if {
	l := _read(object.get(d, "Statement", []))
	is_array(l)
	ss := {st | some e in l; st := _read(e); is_object(st)}
} else := ss if {
	st := _read(object.get(d, "Statement", null))
	is_object(st)
	ss := {st}
} else := set()

# `Statement` present, but not readable as statements. NOT the same as
# absent (`{"Version": "2012-10-17"}` really does grant nothing) and NOT the
# same as empty (`Statement = []` really is zero statements).
_statement_list_unreadable(d) if {
	v := _read(object.get(d, "Statement", null))
	v != null
	not _statement_list_readable(v)
}

_statement_list_readable(v) if {
	is_array(v)
	every e in v {
		is_object(_read(e))
	}
}

_statement_list_readable(v) if is_object(v)

# --- `_read`: follow ONE `local.` symbol to the value it holds ------------
#
# *** ROUND 17. The whole reason this shared library exists is defect (b) of
# the spike memo: an ordinary DRY hoist must not be graded as if the SYMBOL
# were the value. That was fixed for ARN slots and NOT fixed one level down,
# INSIDE a policy document, where `policy = jsonencode(local.topic_doc)`,
# `Statement = local.stmts`, `Principal = local.s3_principal` and
# `Action = local.publish_action` are all ordinary spellings a correct
# solution may write. All four were EXECUTED at REWARD 0.0 on a fully
# correct artifact. `hcl.deref_local` reads the value out of the same parsed
# `locals` every other hop already reads (nothing is evaluated; the value
# comes back as raw `"${...}"` source and every leaf still goes through
# `hcl.slot`), and is UNDEFINED when the symbol is ambiguous, cyclic or not
# a `local.` at all -- in which case `_read` hands the value back unchanged
# and the fail-closed branches below (`_policy_document_unreadable`, the
# per-position value gate) refuse it LOUDLY. This widens what can be READ,
# never what is ACCEPTED: every read value is graded by exactly the same
# position/value rules an inline one is. ***
_read(v) := d if {
	d := hcl.deref_local(v)
} else := v

_is_string_or_array(v) if is_string(v)

_is_string_or_array(v) if is_array(v)

_as_list(v) := v if {
	is_array(v)
} else := [v] if {
	is_string(v)
} else := []

_lower(v) := lower(v) if {
	is_string(v)
} else := ""

# An expression hcl2json handed back as SOURCE rather than as a literal --
# i.e. a value with an interpolation anywhere in it. `contains`, not
# `interp_body`, on purpose: `"${local.p}"`, `"${local.a}-suffix"` and
# `"arn:${local.part}:..."` are all values this reader cannot decide, and
# every one of them has to err in the SAME direction.
_expr_is_opaque(v) if {
	is_string(v)
	contains(v, "${")
}

# Does this statement grant the S3 service principal sns:Publish? Written to
# err TOWARDS "yes", because a "yes" only ever ADDS a statement that must be
# scoped -- the conservative direction is the one that cannot hide a grant.
_grants_s3_publish(st) if {
	# `!= "deny"`, not `== "allow"`: an `Effect` this rule cannot read (a
	# non-string, an interpolation) must count as GRANTING, which is the
	# direction that cannot hide a grant. `== "allow"` would have let an
	# unreadable Effect exempt the statement from scoping entirely.
	_lower(object.get(st, "Effect", "Allow")) != "deny"
	_principal_covers_s3(st)
	_action_covers_publish(st)
}

# *** ROUND 17 -- "ERRS TOWARDS 'THIS STATEMENT GRANTS'" IS NOW WHAT THE
# CODE ACTUALLY DOES, WHICH IT WAS NOT. Both predicates used to fall back to
# "covers" only when the key was ABSENT (`== null`). A key present but
# UNREADABLE -- `Principal = local.s3_principal`, `Action =
# local.publish_action`, both ordinary DRY hoists -- matched neither the
# literal test nor the absent test, so the statement was silently DROPPED
# from grading. Executed: a fully correct, correctly-scoped topic policy
# scored REWARD 0.0 with a deny message asserting it had "0 statement(s)
# granting ... sns:Publish". Both are now written as "unless this reader can
# read the value AND that readable value excludes the grant", so ANY
# unreadable spelling counts as granting. ***
_principal_covers_s3(st) if not _principal_definitely_excludes_s3(st)

# Every SCALAR leaf of the value, each passed through `_read` so a hoisted
# `local.` symbol is read as what it holds.
_principal_raw_leaves(v) := [raw |
	walk(v, [_, raw])
	not is_object(raw)
	not is_array(raw)
]

_principal_leaves(v) := [leaf |
	some raw in _principal_raw_leaves(v)
	leaf := _read(raw)
	is_string(leaf)
]

# A leaf this reader has NO reading for: still an interpolation after
# `_read`, or not a string at all (a number, a bool, a null, or a `local.`
# that holds a nested structure). Every one of those errs towards "this
# statement GRANTS" -- the direction that cannot hide a grant.
_principal_has_unreadable_leaf(v) if {
	some raw in _principal_raw_leaves(v)
	_leaf_is_unreadable(_read(raw))
}

_leaf_is_unreadable(leaf) if not is_string(leaf)

_leaf_is_unreadable(leaf) if _expr_is_opaque(leaf)

# `Principal` is `{"Service": "s3.amazonaws.com"}`, `{"Service": [...]}`, or
# the bare string "*". `walk` reaches every leaf of whichever, so no fixed
# nesting is assumed.
#
# *** WRITTEN AS AN EXPLICIT `== null`, NOT `not object.get(...)`, AND THAT
# IS NOT A STYLE CHOICE. `object.get` returns its DEFAULT when the key is
# missing, and `null` is TRUTHY in Rego -- so `not object.get(st, "X", null)`
# is FALSE whether the key is absent or present, and the clause is DEAD CODE.
# Executed: `not object.get({"Action": "..."}, "Principal", null)` is
# undefined, i.e. the guard never fires. This is the SAME defect class as the
# dead `not parse_traversal(x)` guards round 16 fixes in the shared library:
# a guard that reads like a check and is always false. ***
_principal_definitely_excludes_s3(st) if {
	v := _read(object.get(st, "Principal", null))
	v != null
	not _principal_has_unreadable_leaf(v)
	every leaf in _principal_leaves(v) {
		not _lower(leaf) in {"s3.amazonaws.com", "*"}
	}
}

_action_covers_publish(st) if not _action_definitely_excludes_publish(st)

_action_definitely_excludes_publish(st) if {
	v := _read(object.get(st, "Action", null))
	v != null
	_is_string_or_array(v)
	every a in _action_entries(v) {
		is_string(a)
		not _expr_is_opaque(a)
		not _lower(a) in {"sns:publish", "sns:*", "*"}
	}
}

_action_entries(v) := [a |
	some e in _as_list(v)
	a := _read(e)
]

# The `aws:SourceArn` condition POSITIONS of ONE statement. `Condition` is
# {<operator>: {<condition key>: <value(s)>}}, and ONE POSITION is one
# (operator, condition key) pair carrying its WHOLE value list.
#
# *** ROUND 17 -- THE TWO QUANTIFIERS ARE DIFFERENT LOGICAL CONNECTIVES AND
# THIS RULE USED TO CONFLATE THEM. It emitted ONE SLOT PER VALUE and
# `_statement_is_scoped` accepted on `some` slot. But IAM OR-s the values
# inside ONE condition position and AND-s distinct positions, so
#     ArnLike = { "aws:SourceArn" = [local.arns.media_bucket, "arn:aws:s3:::*"] }
# was graded as scoped while actually letting ANY bucket in ANY account
# publish -- the exact property the deny message claims to enforce.
# EXECUTED at REWARD 1.0 on all three document routes and on the CFN arm; it
# was the round-16 `Sid` launder relocated one level down, into the value
# list. A POSITION is now the unit, `every` grades the values inside it, and
# `some` grades across positions (adding an AND-ed condition can only
# narrow a grant, so `some` is sound there). ***
#
# THREE FAMILIES OF OPERATOR ARE EXCLUDED, all for the same reason -- none
# of them RESTRICTS the grant to this bucket, so counting one as scoping
# evidence would be an inversion an adversarial solution could write on
# purpose. Excluding an operator leaves the statement unscoped, which is the
# LOUD direction:
#
#   * "...Not..."      -- `ArnNotLike aws:SourceArn = <this bucket>` scopes
#                         the grant to every bucket EXCEPT this one.
#   * "...IfExists"    -- `ArnLikeIfExists` is satisfied VACUOUSLY when the
#                         request carries no `aws:SourceArn` at all, so it
#                         constrains nothing a caller cannot simply omit.
#   * "ForAllValues:"  -- also satisfied vacuously on an absent/empty key.
#                         (`ForAnyValue:` is NOT excluded: it requires at
#                         least one present value to match, which for a
#                         single-valued key like aws:SourceArn is the same
#                         restriction.)
#
# An operator this reader cannot read at all (an interpolated key) is
# excluded too: it could BE any of the three.
_statement_source_arn_positions(st) := {[op, k, vals] |
	cond := _read(object.get(st, "Condition", {}))
	is_object(cond)
	some op, keys_raw in cond
	keys := _read(keys_raw)
	is_object(keys)
	is_string(op)
	not _expr_is_opaque(op)
	_operator_restricts(op)
	some k, v in keys
	_lower(k) == "aws:sourcearn"
	vals := [_expr_refs(e) | some e in _as_list(_read(v))]
}

# ONE expression -> the reference list `hcl.slot` grades. A lone `"${...}"`
# interpolation yields its body; anything else (a literal ARN string, an
# interpolation with text around it) yields the EMPTY list, which `hcl.slot`
# reports as "the slot carries no resource reference at all" -- refused, and
# named in the deny message, rather than waved through.
_operator_restricts(op) if {
	not contains(op, "Not")
	not contains(op, "IfExists")
	not startswith(op, "ForAllValues:")
}

_expr_refs(e) := [b] if {
	b := hcl.interp_body(e)
} else := []

# --- route 1 + 2: a structured document read out of the .tf source -------

# *** ROUND 17 -- THE MISSING `is_object` GUARD. This union used to take
# `hcl.resource_jsonencode(...)` RAW. `policy = jsonencode(local.doc)`
# re-parses perfectly well -- the recovered body is the STRING
# "${local.doc}", not an object -- so it contributed an "entry",
# `_policy_document_unreadable` was FALSE, and the promised loud deny never
# fired: the document was graded as having 0 granting statements and a
# CORRECT, DRY solution scored REWARD 0.0 with a message it refutes. The
# JSON-literal route one rule down always had this guard; this route did
# not. (The claim in the shared library's own header, in specs/SCHEMA.md
# and in the spike memo that such a body "contributes NO entry" was false
# and is retracted in all three places.) ***
_policy_structured_docs(r) := _policy_jsonencode_docs(r) | _policy_json_literal_docs(r)

_policy_jsonencode_docs(r) := {d |
	some raw in hcl.resource_jsonencode(r.type, r.name, "policy")
	d := _read(raw)
	is_object(d)
}

# What the jsonencode route recovered but could NOT accept as a document, so
# the unreadable deny quotes the artifact instead of asserting about it.
_policy_jsonencode_rejects(r) := {d |
	some raw in hcl.resource_jsonencode(r.type, r.name, "policy")
	d := _read(raw)
	not is_object(d)
}

_policy_json_literal_docs(r) := {d |
	some v in hcl.resource_attr_values(r.type, r.name, "policy")
	is_string(v)
	json.is_valid(v)
	d := json.unmarshal(v)
	is_object(d)
}

# --- route 3: a `data "aws_iam_policy_document"` --------------------------
#
# *** ROUND 17 -- READ FROM THE .tf SOURCE, NOT FROM THE PLAN. The plan
# reports a `condition`'s `values` as `{"references": [...]}`, a FLAT list
# with the LITERALS DROPPED: for
#     values = [local.arns.media_bucket, "arn:aws:s3:::*"]
# the wildcard is not in `.references` at all, so the position looked like a
# single confidently-resolved reference and the artifact scored REWARD 1.0
# while letting any bucket in any account publish. The value list has to be
# read where the literals still exist, which is the same parsed HCL every
# other route already reads. A referenced document with no matching `data`
# block in the parsed .tf (one built inside a module, say) yields NO
# document, so the caller finds nothing readable and DENIES loudly. ***

# WHICH `data "aws_iam_policy_document"` this policy argument names, from
# TWO sources.
#
# The plan's own `.references` is the first, and it is enough for
# `policy = data.aws_iam_policy_document.x.json` written directly. It is NOT
# enough for the DRY spelling `policy = local.doc_json` -- terraform reports
# that argument's references as `["local.doc_json"]` and stops there, so the
# document was invisible and the policy DENIED an ordinary correct solution
# for holding an unreadable document. Same defect class as residual 14, one
# argument further out. The second source dereferences the symbol against
# the parsed `locals` and reads the traversal it holds.
_policy_document_data_names(r) := from_plan | from_source if {
	from_plan := {name |
		some addr in policy_references(r)
		startswith(addr, "data.aws_iam_policy_document.")
		parts := split(addr, ".")
		count(parts) >= 3
		name := parts[2]
	}
	from_source := {name |
		some v in hcl.resource_attr_values(r.type, r.name, "policy")
		body := hcl.interp_body(_read(v))
		segs := hcl.parse_traversal(body)
		count(segs) >= 3
		segs[0] == "data"
		segs[1] == "aws_iam_policy_document"
		name := segs[2]
	}
}

_policy_document_data_blocks(r) := {[name, blk] |
	some name in _policy_document_data_names(r)
	some [dtype, dname, blk] in hcl.data_blocks
	dtype == "aws_iam_policy_document"
	dname == name
}

# *** THE PLAN FALLBACK, AND ITS COST, STATED OUT LOUD. ***
#
# `hcl.data_blocks` reads the parsed .tf/.tf.json the harness merged. When
# NO parsed source was supplied at all (`hcl.hcl_supplied` false -- an arm
# whose generated static_tiers.sh loads the library but runs no merge), the
# HCL route finds nothing and the caller would DENY the arm's own reference
# solution. So the PLAN's `expressions.statement` is read instead, in that
# case ONLY.
#
# `.configuration` alone CANNOT grade this: it reports a `condition`'s
# `values` as `{"references": [...]}` with EVERY LITERAL DROPPED, so
# `values = [x, "arn:aws:s3:::*"]` and `values = [x]` are indistinguishable
# there -- the executed REWARD-1.0 launder residual 13 records. The arity
# and the literals ARE in `.planned_values` (one entry per value, `null` for
# an unknown, the literal verbatim otherwise), so the fallback reads BOTH
# halves and refuses a position `.planned_values` shows holding a literal.
# What remains residual on this path is narrower and is stated where it is
# used: if terraform defers the data source entirely there is no planned
# list to check, and the reference slot alone decides.
#
# Guarded by `not hcl.hcl_supplied` rather than by "the HCL route found
# nothing", so an arm that DOES supply parsed source can never silently fall
# back to the weaker reader by hiding its data block.
_policy_document_plan_statements(r) := {[name, si, st] |
	not hcl.hcl_supplied
	some name in _policy_document_data_names(r)
	some ds in configured_resources
	ds.mode == "data"
	ds.type == "aws_iam_policy_document"
	ds.name == name
	some si, st in object.get(ds, ["expressions", "statement"], [])
	is_object(st)
}

# The plan spells every leaf `{"constant_value": ...}` or
# `{"references": [...]}`. `_plan_leaf` flattens the first to the value and
# the second to nothing -- a reference is not a readable literal -- so the
# SAME predicates grade both spellings.
_plan_leaf(v) := object.get(v, "constant_value", null)

_plan_statement_grants_s3_publish(st) if {
	_lower(_plan_leaf(object.get(st, "effect", {}))) != "deny"
	_plan_principal_covers_s3(st)
	_plan_action_covers_publish(st)
}

_plan_principal_covers_s3(st) if {
	some p in _as_block_list(object.get(st, "principals", []))
	some id in _as_list(_plan_leaf(object.get(p, "identifiers", {})))
	_lower(id) in {"s3.amazonaws.com", "*"}
}

# An `identifiers` built from a reference is not knowable here; counted as
# covering, which is the direction that cannot hide a grant.
_plan_principal_covers_s3(st) if {
	some p in _as_block_list(object.get(st, "principals", []))
	object.get(p, ["identifiers", "references"], null) != null
}

_plan_principal_covers_s3(st) if object.get(st, "principals", null) == null

_plan_action_covers_publish(st) if {
	some a in _as_list(_plan_leaf(object.get(st, "actions", {})))
	_lower(a) in {"sns:publish", "sns:*", "*"}
}

_plan_action_covers_publish(st) if object.get(st, ["actions", "references"], null) != null

_plan_action_covers_publish(st) if object.get(st, "actions", null) == null

# ONE POSITION per `condition` block, joined BY INDEX to `.planned_values`.
#
# *** WHY `.planned_values` AND NOT JUST `.configuration`. The configuration
# reports a condition's `values` as `{"references": [...]}` with every
# LITERAL DROPPED. `.planned_values` reports the SAME list with its arity
# intact: one entry per value, `null` for a value terraform cannot know yet
# (which is what every reference to a not-yet-created bucket's `arn` is) and
# the LITERAL VERBATIM for a constant. So `values = [x, "arn:aws:s3:::*"]`
# comes back as `[null, "arn:aws:s3:::*"]`, and the wildcard the
# configuration hid is visible again. Verified against a real terraform
# 1.15.8 plan; see `_plan_position_has_a_literal`. ***
_plan_statement_source_arn_positions(st, name, si) := {[test, variable, vals] |
	some ci, cond in _as_block_list(object.get(st, "condition", []))
	is_object(cond)
	test := _plan_leaf(object.get(cond, "test", {}))
	is_string(test)
	_operator_restricts(test)
	variable := _plan_leaf(object.get(cond, "variable", {}))
	is_string(variable)
	_lower(variable) == "aws:sourcearn"
	vals := _plan_position_value_slots(cond, name, si, ci)
}

# The reference list this position carries -- ONE slot, which `hcl.slot`
# then grades with its usual arity gate (two independent references are
# AMBIGUOUS and refused) -- UNLESS `.planned_values` shows the position also
# holds a hardcoded literal, in which case the position is given an EMPTY
# value list, which `_position_is_scoped` refuses outright.
_plan_position_value_slots(cond, name, si, ci) := [] if {
	_plan_position_has_a_literal(name, si, ci)
} else := [object.get(cond, ["values", "references"], [])]

_plan_position_has_a_literal(name, si, ci) if {
	some v in _plan_planned_condition_values(name, si, ci)
	v != null
}

# `.planned_values` is also how this reader knows the position exists at
# all. When the plan carries no planned entry for it (terraform deferred the
# whole data source), there is no list to check and NOTHING is asserted here
# -- the reference slot alone decides, exactly as it did before, and that
# is the residual this arm still carries.
_plan_planned_condition_values(name, si, ci) := vals if {
	some r in planned_resources
	r.address == sprintf("data.aws_iam_policy_document.%s", [name])
	vals := object.get(r, ["values", "statement", si, "condition", ci, "values"], null)
	is_array(vals)
}

# A `data "aws_iam_policy_document"` statement, read from parsed HCL. Same
# three predicates as the JSON shape, erring in the same direction, over the
# provider's own snake_case argument names.
_data_statements(blk) := [st |
	some raw in _as_block_list(_read(object.get(blk, "statement", [])))
	st := _read(raw)
	is_object(st)
]

_as_block_list(v) := v if {
	is_array(v)
} else := [v] if {
	is_object(v)
} else := []

_data_statement_grants_s3_publish(st) if {
	_lower(_read(object.get(st, "effect", "Allow"))) != "deny"
	_data_principal_covers_s3(st)
	_data_action_covers_publish(st)
}

_data_principal_covers_s3(st) if not _data_principal_definitely_excludes_s3(st)

_data_principals(st) := [p |
	some raw in _as_block_list(_read(object.get(st, "principals", [])))
	p := _read(raw)
	is_object(p)
]

_data_principal_identifiers(st) := [id |
	some p in _data_principals(st)
	some e in _as_list(_read(object.get(p, "identifiers", [])))
	id := _read(e)
]

_data_principal_definitely_excludes_s3(st) if {
	object.get(st, "principals", null) != null
	count(_data_principals(st)) > 0
	not _principal_has_unreadable_leaf(_read(object.get(st, "principals", [])))
	every id in _data_principal_identifiers(st) {
		is_string(id)
		not _expr_is_opaque(id)
		not _lower(id) in {"s3.amazonaws.com", "*"}
	}
}

_data_action_covers_publish(st) if not _data_action_definitely_excludes_publish(st)

_data_action_definitely_excludes_publish(st) if {
	v := _read(object.get(st, "actions", null))
	v != null
	_is_string_or_array(v)
	every a in _action_entries(v) {
		is_string(a)
		not _expr_is_opaque(a)
		not _lower(a) in {"sns:publish", "sns:*", "*"}
	}
}

# The same POSITION unit as the JSON shape: one (test, variable) pair
# carrying its WHOLE `values` list, literals included.
_data_statement_source_arn_positions(st) := {[test, variable, vals] |
	some raw in _as_block_list(_read(object.get(st, "condition", [])))
	cond := _read(raw)
	is_object(cond)
	test := _read(object.get(cond, "test", null))
	is_string(test)
	not _expr_is_opaque(test)
	_operator_restricts(test)
	variable := _read(object.get(cond, "variable", null))
	is_string(variable)
	_lower(variable) == "aws:sourcearn"
	vals := [_expr_refs(e) | some e in _as_list(_read(object.get(cond, "values", null)))]
}

# --- the union: every granting statement, with its SourceArn positions ---
#
# A SET of `[label, positions]` pairs -- a set, never an object keyed by
# data, for the reason the shared library's header states at length.
# (A FUNCTION returning a UNION of two set comprehensions, not two partial
# `contains` clauses -- Rego reserves `contains` for rules without arguments.)
granting_statements(r) := (structured | from_data) | from_plan if {
	structured := {[label, positions] |
		some d in _policy_structured_docs(r)
		some st in _statements(d)
		_grants_s3_publish(st)
		label := sprintf("%s statement %v", [r.address, object.get(st, "Sid", "<no Sid>")])
		positions := _statement_source_arn_positions(st)
	}
	from_data := {[label, positions] |
		some [name, blk] in _policy_document_data_blocks(r)
		some i, st in _data_statements(blk)
		_data_statement_grants_s3_publish(st)
		label := sprintf("%s -> data.aws_iam_policy_document.%s statement #%d", [r.address, name, i])
		positions := _data_statement_source_arn_positions(st)
	}
	from_plan := {[label, positions] |
		some [name, si, st] in _policy_document_plan_statements(r)
		_plan_statement_grants_s3_publish(st)
		label := sprintf("%s -> data.aws_iam_policy_document.%s statement #%d (read from the plan, no parsed source on this arm)", [r.address, name, si])
		positions := _plan_statement_source_arn_positions(st, name, si)
	}
}

# ONE POSITION is scoped iff it carries at least one value AND *EVERY* one
# of its values resolves to the `arn` of a bucket instance this
# configuration's own notification resources wire. `every`, because the
# values inside one condition position are OR-ed by IAM: one wildcard beside
# the right bucket makes the whole position grant to everything. A position
# with NO readable value list at all (a value that is not a string and not a
# list of them) fails here rather than passing vacuously.
# `slot_names_arn_of` is the SAME acceptance test both dedicated ARN slots
# use -- there is no looser variant here.
_position_is_scoped(pos) if {
	count(pos[2]) > 0
	every refs in pos[2] {
		slot_names_arn_of(hcl.slot(refs), "aws_s3_bucket", notification_bucket_instances)
	}
}

# ONE statement is scoped iff SOME of its `aws:SourceArn` condition
# POSITIONS is scoped. `some` across positions, because distinct
# (operator, condition key) positions are AND-ed by IAM: an extra AND-ed
# condition can only narrow a grant, never widen it.
_statement_is_scoped(positions) if {
	some pos in positions
	_position_is_scoped(pos)
}

# EVERY granting statement, not SOME: a correctly-scoped statement sitting
# beside an unconditioned one must not launder the unconditioned one.
# Written as "no granting statement is unscoped" rather than with `every`
# over a destructured pair, which Rego's `every` does not accept.
_unscoped_granting_statements(r) := {label |
	some [label, positions] in granting_statements(r)
	not _statement_is_scoped(positions)
}

# *** ROUND 17 -- the `count(granting_statements(r)) > 0` term is DELETED
# from this rule, not kept. It made "this document has zero granting
# statements" indistinguishable from "one of its granting statements is
# unscoped", so both borrowed the SAME deny message and the zero case was
# told, falsely, that "not every one of them is scoped ... any S3 bucket in
# any account can publish". Zero granting statements now has its own deny
# (below), the way the CFN arm's mirror always did. ***
policy_document_scopes_to_the_bucket(r) if {
	count(_unscoped_granting_statements(r)) == 0
}

# TRUE when NO route produced a document this resolver can read structurally.
# A separate, LOUDER deny than "not scoped": the two say different things and
# only one of them can be true of a given artifact.
_policy_document_unreadable(r) if {
	count(_policy_structured_docs(r)) == 0
	count(_policy_document_data_blocks(r)) == 0
	count(_policy_document_plan_statements(r)) == 0
}

# ... and a document that IS an object but whose `Statement` key this reader
# cannot read as statements (`Statement = local.stmts`). Grading that as
# "0 granting statements" states something the artifact refutes.
_policy_document_unreadable(r) if {
	some d in _policy_structured_docs(r)
	_statement_list_unreadable(d)
}

# ... and the route-3 twin: a `data "aws_iam_policy_document"` block whose
# `statement` argument this reader cannot turn into blocks. Same reason --
# "found no granting statement" would be a claim the artifact refutes.
_policy_document_unreadable(r) if {
	some [_, blk] in _policy_document_data_blocks(r)
	v := _read(object.get(blk, "statement", null))
	v != null
	not _statement_list_readable(v)
}

# What each SourceArn condition position resolved to, quoted so the message
# states the artifact rather than a diagnosis of it (RULING 3). Every VALUE
# of every position is listed, so a position refused for holding a wildcard
# beside the right bucket says so.
_position_value_labels(pos) := ["<this condition position carries no readable value list at all, so no value of it can name a bucket>"] if {
	count(pos[2]) == 0
} else := [_slot_label(hcl.slot(refs)) | some refs in pos[2]]

_position_label(pos) := sprintf("%v %v = value(s) %v", [pos[0], pos[1], _position_value_labels(pos)])

policy_document_report(r) := sort([entry |
	some [label, positions] in granting_statements(r)
	entry := sprintf("%s -> aws:SourceArn condition position(s) %v", [
		label,
		sort([_position_label(pos) | some pos in positions]),
	])
])

# What the three document routes recovered, quoted for the unreadable deny.
_policy_document_shape_report(r) := sprintf(
	"the `policy` argument holds %v; policy references %v; the jsonencode(...) body re-parsed to a NON-OBJECT in %d case(s) (%v); readable structured document(s): %d; `data \"aws_iam_policy_document\"` block(s) found in the parsed .tf for the referenced document(s) %v: %d",
	[
		sort([sprintf("%v", [v]) | some v in hcl.resource_attr_values(r.type, r.name, "policy")]),
		sort(policy_references(r)),
		count(_policy_jsonencode_rejects(r)),
		sort([sprintf("%v", [d]) | some d in _policy_jsonencode_rejects(r)]),
		count(_policy_structured_docs(r)),
		sort([n | some n in _policy_document_data_names(r)]),
		count(_policy_document_data_blocks(r)),
	],
)

deny contains msg if {
	some tp in graded_topic_policies
	_policy_document_unreadable(tp)
	msg := sprintf(
		"%s: this resolver cannot read the STRUCTURE of this topic policy's `policy` argument, so it cannot tell an aws:SourceArn condition that scopes the sns:Publish grant to a bucket from a bucket reference sitting anywhere else in the document (a `Sid` string, for one). It reads three shapes -- `jsonencode({...})` whose body is an OBJECT CONSTRUCTOR (re-parsed from the .tf source by the harness; `jsonencode(local.doc)` re-parses to the bare symbol, which is not a document), a literal JSON string, and a `data \"aws_iam_policy_document\"` block in the parsed .tf -- and a document whose `Statement` key holds something other than a statement object or a list of them (`Statement = local.stmts`) is refused here too rather than counted as zero statements. What the routes found: %s. Refused rather than graded on a bare mention. Inline the document (or the `Statement` list) at the argument, or build it with `data \"aws_iam_policy_document\"`.",
		[tp.address, _policy_document_shape_report(tp)],
	)
}

# *** ROUND 17: "ZERO GRANTING STATEMENTS" GETS ITS OWN, HONEST MESSAGE.
# It used to borrow the "not every one of them is scoped ... any S3 bucket
# in any account can publish" message, which is false on both counts for a
# document that grants s3.amazonaws.com nothing at all. The CFN arm has had
# this dedicated deny since round 16; this is its TF twin, and the
# cross-arm strictness asymmetry it closes was a real one. ***
deny contains msg if {
	some tp in graded_topic_policies
	not _policy_document_unreadable(tp)
	count(granting_statements(tp)) == 0
	msg := sprintf(
		"%s: this resolver read this topic policy's document and found NO statement granting the s3.amazonaws.com service principal sns:Publish at all, so S3 cannot publish to the topic this configuration's own aws_s3_bucket_notification wires. A statement counts as granting unless its Effect reads `Deny`, its Principal is readable and names neither s3.amazonaws.com nor `*`, or its Action is readable and covers neither sns:Publish nor a wildcard -- an unreadable Effect, Principal or Action counts as GRANTING, so this is not a reading failure. What the routes found: %s.",
		[tp.address, _policy_document_shape_report(tp)],
	)
}

deny contains msg if {
	some tp in graded_topic_policies
	not _policy_document_unreadable(tp)
	count(granting_statements(tp)) > 0
	not policy_document_scopes_to_the_bucket(tp)
	msg := sprintf(
		"%s: this topic policy has %d statement(s) granting the s3.amazonaws.com service principal sns:Publish, and not every one of them is scoped by an aws:SourceArn condition to a bucket this configuration's own aws_s3_bucket_notification wires (%v). Read POSITIONALLY and per VALUE -- a bucket reference elsewhere in the document, in a `Sid` or a `Resource`, is not a scoping condition, and neither is a condition position whose value LIST also holds a wildcard or some other bucket, because IAM OR-s the values inside one condition position -- each granting statement's aws:SourceArn condition position resolves as: %v. Without a condition position EVERY value of which names the wired bucket, any S3 bucket in any account can publish to this topic.",
		[
			tp.address,
			count(granting_statements(tp)),
			sort([hcl.instance_addr(a) | some a in notification_bucket_instances]),
			policy_document_report(tp),
		],
	)
}

# --- ROUND 15: GRADE PER WIRED TOPIC, NOT PER POLICY RESOURCE -------------
#
# *** Executed reward-1.0 silent PASS this closes. `notification_topic_
# instances` is a UNION over every `topic` block, and `references_this_topic`
# only asked whether a policy's `arn` names SOME MEMBER of that set. So a
# solution could wire TWO topic blocks -- `aws_sns_topic.audit` (which the
# ticket is about) and a decoy -- attach its one `aws_sns_topic_policy` to
# the DECOY, and leave `aws_sns_topic.audit` with no resource policy at all.
# Every existing rule passed: the policy named a member of the anchor set,
# and nothing anywhere required the graded policy to cover EVERY wired
# topic. `tier0_pass=1 tier1_status=PASS deny [] REWARD 1.0`, on an artifact
# where S3 can never publish to the audit topic. It laundered the
# checked-in `sns-topic-policy-attached-to-a-decoy-topic-*` catch by adding
# one block. ***
#
# The requirement below is the quantifier the old rules were missing: for
# EVERY topic instance any `topic` block wires, SOME accepted policy shape
# must be attached to THAT instance.
topic_policy_instances := {inst |
	some tp in topic_policy_configs
	v := topic_arn_verdict(tp)
	v.kind == "resolved"
	v.referent_path[0] == "aws_sns_topic"
	v.attr_path == ["arn"]
	inst := v.instance
}

# An inline `policy` argument is set on the `aws_sns_topic` BLOCK, so it
# covers every instance that block expands to -- matching on type+label
# (without the key) is correct here and is not the collapse the round-15
# `instance_of` fix removes.
_inline_policy_covers(inst) if {
	some t in inline_policy_topics
	t.type == inst[0]
	t.name == inst[1]
}

# The per-policy `arn` diagnostic the DELETED `references_this_topic` deny
# used to carry, folded into the per-wired-topic message so that a policy
# whose `arn` is ambiguous, opaque or pointed at the wrong resource is still
# EXPLAINED rather than merely counted absent. Every entry states what the
# resolver read and what it made of it; none asserts a conclusion about the
# policy (RULING 3).
_topic_policy_attachment_report := sort([entry |
	some tp in topic_policy_configs
	entry := sprintf("%s -> %s", [tp.address, _slot_label(topic_arn_verdict(tp))])
])

_wired_topic_has_policy(inst) if inst in topic_policy_instances

_wired_topic_has_policy(inst) if _inline_policy_covers(inst)

deny contains msg if {
	some inst in notification_topic_instances
	not _wired_topic_has_policy(inst)
	msg := sprintf(
		"%s: this configuration's own aws_s3_bucket_notification wires this topic, but no aws_sns_topic_policy is attached to it and it carries no inline `policy` argument -- S3 cannot publish to a topic whose resource policy does not grant it sns:Publish, so this notification target is dead. The topics this configuration's notification resources wire are %v. What each aws_sns_topic_policy's own `arn` argument resolves to is: %v. The topics carrying an inline `policy` argument are %v.",
		[
			hcl.instance_addr(inst),
			sort([hcl.instance_addr(a) | some a in notification_topic_instances]),
			_topic_policy_attachment_report,
			sort([sprintf("%s.%s", [t.type, t.name]) | some t in inline_policy_topics]),
		],
	)
}

# The inline-shape mirror -- the SAME two denies, over the SAME helpers, so
# the two accepted policy shapes cannot drift apart. That drift is exactly
# what the round-16 launder exploited: the one-line `Sid` edit flipped the
# standalone-policy fixture AND the inline-policy fixture, because both rules
# were the same mention test written twice. They are now the same POSITION
# test written twice, and both read `granting_statements`, which takes the
# resource and reads its `policy` argument the same way regardless of which
# resource type carries it.
#
# No attachment ("is this the audit topic's policy") clause is needed here:
# an inline `policy` is set on the `aws_sns_topic` resource itself, so the
# question is answered by `graded_inline_topics` selecting the block whose
# instances the notification wires.
deny contains msg if {
	some t in graded_inline_topics
	_policy_document_unreadable(t)
	msg := sprintf(
		"%s: this resolver cannot read the STRUCTURE of this topic's inline `policy` argument, so it cannot tell an aws:SourceArn condition that scopes the sns:Publish grant to a bucket from a bucket reference sitting anywhere else in the document (a `Sid` string, for one). It reads three shapes -- `jsonencode({...})` whose body is an OBJECT CONSTRUCTOR (re-parsed from the .tf source by the harness; `jsonencode(local.doc)` re-parses to the bare symbol, which is not a document), a literal JSON string, and a `data \"aws_iam_policy_document\"` block in the parsed .tf -- and a document whose `Statement` key holds something other than a statement object or a list of them (`Statement = local.stmts`) is refused here too rather than counted as zero statements. What the routes found: %s. Refused rather than graded on a bare mention. Inline the document (or the `Statement` list) at the argument, or build it with `data \"aws_iam_policy_document\"`.",
		[t.address, _policy_document_shape_report(t)],
	)
}

# The inline twin of the standalone arm's dedicated zero-granting deny.
deny contains msg if {
	some t in graded_inline_topics
	not _policy_document_unreadable(t)
	count(granting_statements(t)) == 0
	msg := sprintf(
		"%s: this resolver read this topic's inline `policy` document and found NO statement granting the s3.amazonaws.com service principal sns:Publish at all, so S3 cannot publish to the topic this configuration's own aws_s3_bucket_notification wires. A statement counts as granting unless its Effect reads `Deny`, its Principal is readable and names neither s3.amazonaws.com nor `*`, or its Action is readable and covers neither sns:Publish nor a wildcard -- an unreadable Effect, Principal or Action counts as GRANTING, so this is not a reading failure. What the routes found: %s.",
		[t.address, _policy_document_shape_report(t)],
	)
}

deny contains msg if {
	some t in graded_inline_topics
	not _policy_document_unreadable(t)
	count(granting_statements(t)) > 0
	not policy_document_scopes_to_the_bucket(t)
	msg := sprintf(
		"%s: this topic's inline `policy` argument has %d statement(s) granting the s3.amazonaws.com service principal sns:Publish, and not every one of them is scoped by an aws:SourceArn condition to a bucket this configuration's own aws_s3_bucket_notification wires (%v). Read POSITIONALLY and per VALUE -- a bucket reference elsewhere in the document, in a `Sid` or a `Resource`, is not a scoping condition, and neither is a condition position whose value LIST also holds a wildcard or some other bucket, because IAM OR-s the values inside one condition position -- each granting statement's aws:SourceArn condition position resolves as: %v. Without a condition position EVERY value of which names the wired bucket, any S3 bucket in any account can publish to this topic.",
		[
			t.address,
			count(granting_statements(t)),
			sort([hcl.instance_addr(a) | some a in notification_bucket_instances]),
			policy_document_report(t),
		],
	)
}

# Fail-closed: a topic exists but NEITHER accepted policy shape exists
# anywhere -- no standalone `aws_sns_topic_policy` AND no `aws_sns_topic`
# carrying its own inline `policy` argument (the Rego-side, now-sole check
# for "no topic policy at all": the old tier-0 `sns-topic-policy-exists`
# assert was narrowed to awscdk-only, see this file's header ROUND-2
# CORRECTION, precisely because a single tier-0 jsonpath op cannot OR these
# two TF-shaped resource forms together).
deny contains msg if {
	count(sns_topics) > 0
	count(topic_policy_configs) == 0
	count(inline_policy_topics) == 0
	msg := "an aws_sns_topic exists, but no aws_sns_topic_policy resource AND no aws_sns_topic with its own inline `policy` argument exists anywhere in the plan -- S3 cannot publish to the audit topic without one of the two"
}

# --- ROUND 14: the two `not_verifiable` DEGRADATION rules are DELETED ----
#
# They recorded "same-type/wrong-instance discrimination is DEGRADED for the
# bucket/topic half ... graded by resource TYPE only" and were the ONLY
# consequence of an unresolvable anchor. `not_verifiable` is informational by
# contract -- the generated static_tiers.sh says so in the script itself
# ("does NOT deny the plan and does NOT affect tier1_status/reward") -- so
# logging that message WAS the silent pass, dressed as diligence. The
# condition they described is now a DENY (see the two
# `notification_resource_configs` rules above), which is gating, so there is
# nothing left for them to record.

# --- Audit-topic events must cover an ordinary user-initiated delete
# (ROUND 6, 2026-08-22 -- an adversarial verifier PROVEN, by execution,
# that the tier-0 `object-removed-notification-targets-a-topic` whitelist
# (SCHEMA.md's `op: in`) can only bound which events are ALLOWED on the
# topic target -- it cannot require that any particular one is PRESENT. A
# topic wired to `["s3:LifecycleExpiration:*"]` ALONE (zero
# `s3:ObjectRemoved:*`-family entries anywhere) passed that whitelist
# outright (its one resolved event is a member of the six-literal set)
# even though `s3:LifecycleExpiration:*` never fires for an ordinary
# user-initiated delete -- only for one S3's own Lifecycle engine
# performs (AWS's own S3 User Guide, already cited in this scenario's own
# spec.yaml header comment at round 5). The identical gap already existed
# for `s3:ObjectRemoved:DeleteMarkerCreated` alone: this scenario never
# enables bucket versioning, and that event only fires on a versioned
# bucket, so it alone never fires for THIS scenario's own bucket either.
#
# FIX: a presence/OR requirement, layered on TOP of the existing
# whitelist (not a narrower whitelist -- every shape the whitelist already
# allows that ALSO includes one of the two literals below still passes
# both rules unchanged): at least one of `s3:ObjectRemoved:*` /
# `s3:ObjectRemoved:Delete` -- the two forms that actually fire for a real
# delete on this unversioned bucket -- must be present among the topic
# target's wired events. Reads `.values.topic[*].events` from
# PLANNED_resources, mirroring the tier-0 jsonpath check's own path
# (SCHEMA.md §4.2.1: these are agent-typed string literals, always
# plan-time-known, never provider-computed, so there is no plan-time-
# unknown concern here the way there is for `source_arn`/`policy`
# elsewhere in this file). Only fires when a topic notification is wired
# at all (`count(topic_events) > 0`) -- an entirely missing topic
# notification is a DIFFERENT, already-caught failure
# (object-removed-notification-targets-a-topic / sns-topic-exists, both
# tier 0).
#
# Verified against this scenario's own reference solution/solve.sh (PASS,
# deny empty -- `s3:ObjectRemoved:*` is present) and the new
# audit-topic-wired-only-to-lifecycle-expiration broken fixture (FAILs
# this rule alone, denying with `topic_events =
# {"s3:LifecycleExpiration:*"}`). Every OTHER existing fixture is
# unaffected: `only-one-of-the-two-events-wired` never wires a topic
# notification at all (topic_events stays empty, this rule vacuously does
# not fire, exactly as before this fix -- that fixture is already caught
# at tier 0), and every other broken fixture wires `s3:ObjectRemoved:*`
# on the topic exactly as the reference solution does.

notification_planned := [r |
	some r in planned_resources
	r.type == "aws_s3_bucket_notification"
]

topic_events := {ev |
	some r in notification_planned
	some t in object.get(r.values, "topic", [])
	some ev in object.get(t, "events", [])
}

fires_for_a_real_delete if {
	some ev in topic_events
	ev in {"s3:ObjectRemoved:*", "s3:ObjectRemoved:Delete"}
}

deny contains msg if {
	count(topic_events) > 0
	not fires_for_a_real_delete
	msg := sprintf(
		"topic notification events %v include no s3:ObjectRemoved:* or s3:ObjectRemoved:Delete entry -- this bucket does not enable versioning (so DeleteMarkerCreated alone never fires) and s3:LifecycleExpiration:* never fires for an ordinary user-initiated delete (AWS's own docs) -- 'when any object is deleted' is not satisfied by this wiring alone",
		[topic_events],
	)
}

# --- REUSABLE HELPER: cardinality of an authoritative child resource per
# parent (this scenario's own stated purpose per the design blueprint --
# built once here, to be copied and generalized by a future scenario with
# >1 parent to discriminate; see this file's own header comment for why it
# is not wired into `deny` in THIS package). `children` is the list of
# configured resources of the authoritative child type; `parent_addr` is
# the target parent's own resource address. Returns the count of children
# whose relevant reference attribute (here: `bucket`) references that
# parent. -------------------------------------------------------------------

authoritative_child_unique_per_parent(children, parent_addr) := count([c |
	some c in children
	parent_addr in object.get(c.expressions.bucket, "references", [])
])

notification_configs := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket_notification"
]

# Self-check note only (never denies -- this scenario's own tier-0
# exactly-one-notification-resource-per-bucket-tf assert already covers
# every fixture this could catch, see this file's header comment): for
# every bucket this configuration creates, confirm the general per-parent
# helper agrees with the flat tier-0 count.
not_verifiable contains msg if {
	some b in s3_buckets
	n := authoritative_child_unique_per_parent(notification_configs, b.address)
	n != 1
	msg := sprintf(
		"%s: %d aws_s3_bucket_notification resource(s) REFERENCE this bucket by address (general per-parent helper). Informational only. Read it with two caveats, so it is not mistaken for a coverage claim: (1) it counts REFERENCES, so a notification whose `bucket` argument is written as a literal bucket NAME -- valid, ordinary, and accepted by this oracle through the plan-value anchor route -- reads as 0 here even though it wires this bucket; (2) the tier-0 flat count assert only covers this when the plan has exactly one bucket. The AUTHORITATIVE per-notification check is the round-14 anchor deny above, which is gating; this helper is template code for a future scenario with >1 parent to discriminate.",
		[b.address, n],
	)
}
