# Hand-authored (Batch A scenario-authoring task, 2026-08-20) -- NOT a
# generator stub. emit_oracles() never overwrites this file once it exists
# (specs/SCHEMA.md §8.2 rule 7).
#
# Scenario:   s3-bucket-hardening-decomposition (specs/s3-bucket-hardening-decomposition.yaml)
# Intent doc: oracles/s3-bucket-hardening-decomposition/intent.md
# Graded against `terraform show -json` plan JSON for BOTH TF-shaped arms
# (hcl_raw and, when enabled, terraconstructs) -- specs/SCHEMA.md §4.2/§8.
# `input` at policy-evaluation time is that plan JSON document. A generated
# tests/static_tiers.sh runs:
#   opa eval -f raw -I -d policy.rego 'data.cdktn_bench.s3_bucket_hardening_decomposition.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Encodes three tier-1 structural_assert families
# (specs/s3-bucket-hardening-decomposition.yaml):
#
#   1. tls-deny-covers-objects-too-tf -- the bucket policy's Resource
#      expression must reference the created bucket TWICE (once for the
#      bucket ARN itself, once for the "${...}/*"} object-ARN
#      interpolation) -- a Resource set naming only the bucket ARN (the
#      plausible-wrong catch, tls-policy-misses-object-arn) produces
#      exactly ONE such reference. VERIFIED DIRECTLY at authoring time
#      against real `terraform show -json` plan output (offline,
#      hashicorp/aws 6.58.0): a two-ARN Deny statement's
#      `.configuration...aws_s3_bucket_policy.expressions.policy.references`
#      resolves to `["aws_s3_bucket.this.arn", "aws_s3_bucket.this",
#      "aws_s3_bucket.this.arn", "aws_s3_bucket.this"]` (the BARE resource
#      address `"aws_s3_bucket.this"` appearing TWICE, once per HCL-source
#      occurrence -- Terraform's own reference-tracking convention: EVERY
#      specific-attribute reference to a resource, e.g. `.arn`, is
#      accompanied by that same bare-address entry alongside it); a
#      single-ARN Deny statement resolves to `["aws_s3_bucket.this.arn",
#      "aws_s3_bucket.this"]` (ONE such entry).
#
#      SHAPE-INVARIANCE FIX (this authoring pass, 2026-08-21,
#      verifier-found major): counting only `.arn`-SUFFIXED references
#      (this package's previous `arn_ref_count`) rejected an equally
#      correct policy built from `aws_s3_bucket.this.id` instead of
#      `.arn` (a standard, working idiom for constructing
#      `"arn:aws:s3:::${aws_s3_bucket.this.id}"` by hand) -- that shape's
#      references resolve to `["aws_s3_bucket.this.id", "aws_s3_bucket.this",
#      "aws_s3_bucket.this.id", "aws_s3_bucket.this"]`, zero `.arn`-suffixed
#      entries, so the old count was 0 and the fail-closed rule fired on a
#      correct solution. VERIFIED DIRECTLY (this authoring pass): a real
#      `terraform show -json` plan for an `.id`-derived Deny statement
#      gives exactly that reference list. FIX: `bucket_ref_count` (renamed
#      from `arn_ref_count`) counts occurrences of the BARE resource
#      address itself (`ref == bucket_addr`, not a `.arn`-suffix
#      startswith) -- shape-invariant across `.arn`/`.id`/`.bucket`-derived
#      constructions, since Terraform emits that bare-address entry
#      unconditionally alongside ANY specific-attribute reference to the
#      resource, regardless of which attribute. Re-verified the ORIGINAL
#      `.arn`-based reference solution and the plausible-wrong single-ARN
#      fixture both still resolve to counts of 2 and 1 respectively under
#      the new counting rule (unchanged outcome for those two shapes; only
#      the `.id`-derived shape's outcome changes, from reject to accept).
#
#      Also verified for the `data "aws_iam_policy_document"` idiomatic
#      shape: the SAME two-vs-one bare-address signal appears one hop
#      further, on `data.aws_iam_policy_document.*`'s own
#      `.expressions.statement[*].resources.references` -- so this package
#      follows that one hop when the direct reference is to a
#      `data.aws_iam_policy_document.*` address instead of the bucket
#      itself (mirrors oracles/rego/toy-ssm-parameter/policy.rego's own
#      one-hop-indirection precedent). Re-verified directly for an
#      `.id`-derived `data "aws_iam_policy_document"` statement too: same
#      bare-address-twice shape, one hop down.
#
#   2. every-subresource-targets-this-bucket-tf -- every
#      aws_s3_bucket_versioning / _server_side_encryption_configuration /
#      _public_access_block / _policy resource's `bucket` expression must
#      REFERENCE the aws_s3_bucket resource this configuration creates,
#      never a literal/hardcoded bucket name string (subresource-targets-
#      wrong-bucket's own mechanism).
#
#   3. sse-kms-references-created-key-tf -- the SSE configuration's
#      `kms_master_key_id` expression must REFERENCE an aws_kms_key
#      resource this configuration creates, never an imported/hardcoded
#      key ARN literal (kms-key-not-referenced's own mechanism). VERIFIED
#      DIRECTLY: a correct fixture's
#      `.expressions.rule[*].apply_server_side_encryption_by_default[*].kms_master_key_id.references`
#      resolves to `["aws_kms_key.archive.arn", "aws_kms_key.archive"]`;
#      `.planned_values...values` for the SAME resource has NO
#      `kms_master_key_id` key at all (plan-time-unknown, SCHEMA.md
#      §4.2.1 -- confirming the VALUE path is unsound and only the
#      graph-edge path is sound here, exactly the class of bug that
#      spec's own header comment documents having found and corrected
#      against the blueprint's original design). Also follows a one-hop
#      `aws_kms_alias` indirection now (see `resolved_kms_key_refs` below,
#      verifier-found major fixed 2026-08-21 second pass): a
#      `kms_master_key_id = aws_kms_alias.x.arn` whose alias's own
#      `target_key_id` references an `aws_kms_key` this configuration
#      creates is accepted -- see this package's header note on the
#      2026-08-21 second-pass fixes below for the real plan-JSON evidence.
#
# VERIFIER-FOUND FIXES, 2026-08-21 SECOND PASS (this scenario's second
# verification run):
#  (a) LOCALS-HOIST: a `locals { bucket_arn = aws_s3_bucket.x.arn }` +
#      `Resource = [local.bucket_arn, "${local.bucket_arn}/*"]` policy is
#      genuinely correct but `local.*` values are not represented
#      anywhere in `terraform show -json` plan output's `.configuration`
#      block at all (VERIFIED DIRECTLY: `.configuration.root_module`'s
#      own keys for such a plan are exactly `["resources", "variables"]`,
#      no `locals` key -- there is no hop to follow, unlike the
#      `data.aws_iam_policy_document` and `aws_kms_alias` one-hop cases,
#      both of which ARE full `configured_resources` entries with real
#      `.expressions`). `bucket_ref_count` was already correctly 0 for
#      this shape, but the generic fail-closed deny message ("no
#      aws_s3_bucket_policy resource references this bucket's ARN at
#      all") is FACTUALLY FALSE for it -- the policy does reference the
#      bucket, just not visibly so from this artifact. Fixed by adding
#      `local_only_refs`/`local_only_policies`, which detect this
#      specific shape and emit an ACCURATE reason (still a deny -- a
#      documented v1 static-oracle scope limit, not an accept; see this
#      scenario's spec YAML "Oracle must tolerate/defend" comments) while
#      suppressing the generic, now-inaccurate-for-this-shape message for
#      the same bucket. This is a genuine, unresolvable-from-a-static-
#      artifact gap (accepting it blindly would let a `local` aliasing an
#      entirely unrelated ARN pass as correct), not a bug to route around.
#  (b) IN-CONFIG KMS ALIAS: `kms_master_key_id = aws_kms_alias.x.arn`
#      where `aws_kms_alias.x.target_key_id` references an `aws_kms_key`
#      this configuration creates is exactly "a key created in this same
#      configuration" (oracles/s3-bucket-hardening-decomposition/intent.md's
#      own wording) but was previously rejected outright: the SSE
#      config's `kms_master_key_id.references` resolves to
#      `["aws_kms_alias.archive.arn", "aws_kms_alias.archive"]`, no
#      `aws_kms_key.` prefix. Fixed by `resolved_kms_key_refs`, which
#      follows the alias's own `target_key_id.references` one hop when
#      the direct reference is to an `aws_kms_alias` address -- mirrors
#      `policy_references()`'s existing `data.aws_iam_policy_document`
#      one-hop pattern exactly. VERIFIED DIRECTLY: a real fixture's
#      `aws_kms_alias.archive.target_key_id = aws_kms_key.archive.key_id`
#      resolves the alias's own references to
#      `["aws_kms_key.archive.key_id", "aws_kms_key.archive"]`.
#
# DELIBERATELY NOT ENCODED (documented gap, see the spec's own
# NOT_VERIFIABLE rego_hints entry and oracle.intent wording note): this
# package does not attempt to verify the Deny statement's Effect/Condition
# literal content on the TF-shaped arms -- `aws_s3_bucket_policy.values.policy`
# is entirely ABSENT from `.planned_values` (not present-with-wrong-value)
# whenever the policy references the created bucket's provider-computed
# `.arn` anywhere inside it, REGARDLESS of whether the policy is authored
# via a raw `jsonencode(...)` call or a `data "aws_iam_policy_document"` +
# `.json` reference -- both collapse the SAME way once handed to
# `aws_s3_bucket_policy.policy`. Verified directly both ways at authoring
# time. Only awscdk's own tls-deny-condition-present (tier 0, CFN is always
# fully static) checks the Condition/Effect literal at all. This is an
# accepted, documented v1 static-oracle scope limit, not an oversight --
# an adversarial TF-shaped policy that references the bucket ARN twice
# inside an unrelated ALLOW statement would not be caught by rule 1 above.
# Not defended against here, consistent with this codebase's existing
# convention for this class of gap (see
# oracles/cfn-guard/s3-lambda-log-retention/policy.guard's own header
# comment for the precedent this follows).

package cdktn_bench.s3_bucket_hardening_decomposition

import rego.v1

# Every resource the configuration declares, in the SAME address domain the
# normalised `planned_values` already uses: a module body's own addresses and
# references are module-local, so a call path prefix is what makes the two
# sides join. On a module-free plan the prefix is empty and this is exactly
# `input.configuration.root_module.resources`.
#
# `walk` rather than recursion (Rego forbids a recursive rule): a body is a
# configuration scope when it is the document root or the value of a
# `module_calls.<name>.module` key, and its call path is every name that
# follows a `module_calls` step.
config_scope_path(path) if count(path) == 0

config_scope_path(path) if path[count(path) - 1] == "module"

module_prefix(path) := concat(".", [sprintf("module.%s", [path[i]]) |
	some i
	path[i - 1] == "module_calls"
])

qualify(prefix, name) := name if prefix == ""

qualify(prefix, name) := concat(".", [prefix, name]) if prefix != ""

config_scopes contains scope if {
	walk(input.configuration.root_module, [path, body])
	is_object(body)
	config_scope_path(path)
	scope := {"prefix": module_prefix(path), "resources": object.get(body, "resources", [])}
}

# Address and references qualified together, EVERY reference including the
# `var.`/`local.`/`each.` ones. Enumerating which reference kinds name a
# resource is the list that goes stale when a new kind appears, and the one
# rule below that keys on a reference kind -- the local-value rule, which
# denies a policy whose Resource list is spelled through a `locals` block --
# is one this arm must not reach anyway: inside a module EVERY policy is
# spelled through a local, and that rule's remedy ("reference the
# aws_s3_bucket resource directly") is advice about a file the agent did not
# write. Qualification takes `local.policy` out of that rule's reach, and
# `module_policy_unverifiable` below says the true thing instead.
qualified_resource(prefix, r) := object.union(r, {
	"address": qualify(prefix, r.address),
	# The call path this resource was declared under, kept alongside the
	# qualified address because a NESTED BLOCK's own references are not
	# qualified above and have to be qualified where they are read.
	"prefix": prefix,
	"expressions": {attr: qualified_expression(prefix, expr) |
		some attr, expr in object.get(r, "expressions", {})
	},
})

qualified_expression(prefix, expr) := out if {
	is_object(expr)
	refs := object.get(expr, "references", null)
	is_array(refs)
	out := object.union(expr, {"references": [qualify(prefix, ref) | some ref in refs]})
}

# A NESTED BLOCK's expression is a list of blocks rather than a
# `{"references": [...]}` object (`rule`, and
# `apply_server_side_encryption_by_default` inside it, are read that way by
# `kms_master_key_refs` below). It passes through unqualified, and that is not
# a gap: a module body never carries one on a plan this oracle grades -- the
# vendored s3-bucket module writes both of those as `dynamic` blocks, which
# Terraform's configuration representation omits entirely -- so the only
# nested blocks reaching here are the root module's own, where the prefix is
# empty and qualification is the identity. The KMS edge inside a module call
# is resolved from the CALL's arguments instead (`call_kms_key_refs`).
#
# An expression that names nothing (a constant) passes through for the same
# reason it must produce a value at all: an undefined expression makes the
# whole enclosing `qualified_resource` undefined, which drops the resource
# from the configuration silently -- the wrong-answer-no-error failure this
# join exists to avoid.
qualified_expression(_, expr) := expr if not is_object(expr)

qualified_expression(_, expr) := expr if {
	is_object(expr)
	not is_array(object.get(expr, "references", null))
}

configured_resources := [r |
	some scope in config_scopes
	some res in scope.resources
	r := qualified_resource(scope.prefix, res)
]

# The prefix a call named `name` inside the scope `parent` declares its own
# resources under.
child_prefix(parent, name) := qualify(parent, sprintf("module.%s", [name]))

# Every `module` block, with the prefix its body's resources carry. `walk`
# stops at the `module_calls` map, whose keys are the call names; the parent
# scope is the path up to it, read by the same rule `config_scopes` uses.
module_call_sites contains site if {
	walk(input.configuration.root_module, [path, body])
	is_object(body)
	path[count(path) - 1] == "module_calls"
	some name, call in body
	parent := module_prefix(array.slice(path, 0, count(path) - 1))
	site := {"parent": parent, "prefix": child_prefix(parent, name), "call": call}
}

# Every reference a call's ARGUMENTS make, qualified to the CALLER's scope --
# the only place a module resource's inputs are visible, since a module body
# names them `var.<x>` and the plan carries no link back.
call_argument_refs(prefix) := {ref |
	some site in module_call_sites
	site.prefix == prefix
	some _, expr in object.get(site.call, "expressions", {})
	is_object(expr)
	some raw in object.get(expr, "references", [])
	ref := qualify(site.parent, raw)
}

# `module.<call>.<output>` -> what that output's own expression references,
# qualified into the called module's scope. One hop, no further: an output
# built from another call's output is not followed, and the edge below then
# simply does not resolve.
module_output_refs(ref) := refs if {
	some site in module_call_sites
	some name, out in object.get(object.get(site.call, "module", {}), "outputs", {})
	ref == concat(".", [site.prefix, name])
	refs := {qualify(site.prefix, r) |
		some r in object.get(out.expression, "references", [])
	}
}

# A reference names a resource block when it IS that block's address or
# continues it with an attribute (`.arn`) or an instance key (`[0]`). Matching
# against the block addresses this plan actually declares, rather than testing
# a fixed `aws_s3_bucket.`/`aws_kms_key.` prefix, is what keeps the resolution
# correct for a module-qualified address, whose own prefix contributes
# segments of its own.
reference_names_block(ref, block_addr) if ref == block_addr

reference_names_block(ref, block_addr) if startswith(ref, concat("", [block_addr, "."]))

reference_names_block(ref, block_addr) if startswith(ref, concat("", [block_addr, "["]))

planned_resources := input.planned_values.root_module.resources

s3_buckets := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket"
]

bucket_addrs := {r.address |
	some r in s3_buckets
}

kms_keys := [r |
	some r in configured_resources
	r.type == "aws_kms_key"
]

kms_key_addrs := {r.address |
	some r in kms_keys
}

bucket_policies := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket_policy"
]

policy_documents_by_addr := {r.address: r |
	some r in configured_resources
	r.type == "aws_iam_policy_document"
}

# --- rule 1: tls-deny-covers-objects-too-tf --------------------------------

# The raw list of references this bucket_policy's `policy` expression
# carries -- either direct (a `jsonencode(...)`-authored policy referencing
# the bucket directly) or, when the only reference is to a
# `data.aws_iam_policy_document.*` address, followed one hop further into
# that data source's own `resources` references (the idiomatic
# `data "aws_iam_policy_document"` shape, and terraconstructs' own L2
# `iam.Role.addToPolicy()`-style helper).
policy_references(bp) := refs if {
	direct := object.get(bp.expressions.policy, "references", [])
	# Iterate every raw reference and let the exact-address map lookup do
	# the filtering, rather than pattern-matching a prefix and taking
	# element [0] -- a `.references` list produced by a Terraform
	# attribute-of-a-data-source expression (e.g.
	# `data.aws_iam_policy_document.x.json`) ALWAYS carries the attribute
	# path itself alongside the bare resource address (verified directly:
	# `["data.aws_iam_policy_document.foo.json",
	# "data.aws_iam_policy_document.foo"]`, in that order), and only the
	# bare address is a valid `policy_documents_by_addr` key -- picking
	# `doc_refs[0]` unconditionally grabbed the `.json`-suffixed entry and
	# silently missed the map on every real terraconstructs plan, falling
	# through to the (wrong, too-permissive) `else` branch. Mirrors
	# oracles/rego/toy-ssm-parameter/policy.rego's own
	# `data_policy_docs[ref]` one-hop precedent exactly.
	some ref in direct
	doc := policy_documents_by_addr[ref]
	refs := doc_resource_refs(doc)
} else := object.get(bp.expressions.policy, "references", [])

# The resource addresses one `aws_iam_policy_document`'s statements name. Its
# `statement` blocks are a nested-block LIST, which `qualified_expression`
# passes through unqualified, so the qualification happens here, against the
# document's own call path -- empty, and therefore the identity, on a
# module-free plan.
doc_resource_refs(doc) := [qualify(doc.prefix, ref) |
	some stmt in object.get(doc.expressions, "statement", [])
	some ref in object.get(object.get(stmt, "resources", {}), "references", [])
]

# Counts occurrences of the BUCKET RESOURCE'S BARE ADDRESS itself (never a
# `.arn`-suffixed -- or any other attribute-suffixed -- string) among the
# policy's references. Shape-invariant: Terraform emits this exact bare
# address alongside ANY specific-attribute reference to the resource
# (`.arn`, `.id`, `.bucket`, ...), so a Deny statement built from
# `aws_s3_bucket.x.arn` and one built from
# `"arn:aws:s3:::${aws_s3_bucket.x.id}"` both produce the bare address
# TWICE for a two-element (bucket + object) Resource list -- see this
# file's header comment, "SHAPE-INVARIANCE FIX", for the real plan-JSON
# evidence both ways. Renamed from `arn_ref_count` (previously
# `.arn`-suffix-only, the bug this fix corrects).
bucket_ref_count(bp, bucket_addr) := count([ref |
	some ref in policy_references(bp)
	ref == bucket_addr
])

deny contains msg if {
	some bp in bucket_policies
	some bucket_addr in bucket_addrs
	n := bucket_ref_count(bp, bucket_addr)
	n > 0
	n < 2
	msg := sprintf(
		"%s: policy references %s only %d time(s) (need 2 -- once for the bucket ARN, once for the object-ARN pattern); a Deny naming only the bucket ARN leaves every object-level request over plain HTTP allowed",
		[bp.address, bucket_addr, n],
	)
}

# RESOLVED-VALUE FALLBACK (literal-ARN shape, verifier-found major, 3rd
# verification pass, 2026-08-22): `bucket_ref_count` counts GRAPH EDGES in
# `.configuration...expressions.policy.references` -- but a Deny statement
# whose Resource list is written as LITERAL ARN STRINGS (e.g.
# `Resource = ["arn:aws:s3:::cdktn-bench-document-archive",
# "arn:aws:s3:::cdktn-bench-document-archive/*"]`, the bucket's own name
# hand-copied rather than referenced) contains no reference to the bucket
# resource AT ALL -- `bucket_ref_count` is correctly 0, but unlike the
# locals-hoist case above, this is NOT an unresolvable-from-a-static-
# artifact gap: nothing here is provider-computed, so SCHEMA.md §4.2.1's G2
# contagion never triggers, and `.planned_values` carries the FULLY
# RESOLVED policy value. VERIFIED DIRECTLY (offline, terraform 1.15.8,
# hashicorp/aws 6.58.0, cdktn-bench/hcl-raw:dev): a main.tf identical to
# solution/solve.sh except the Deny statement's Resource list uses those
# two literal strings instead of `aws_s3_bucket.archive.arn`-derived
# expressions plans successfully, and
# `.planned_values...aws_s3_bucket_policy.values.policy` decodes to exactly
# that two-element, SecureTransport-false Deny statement (while
# `.configuration...expressions.policy` is `{}`, no `references` key --
# there is genuinely nothing to graph-edge count, unlike the locals case
# where a `local.*` reference IS present but unfollowable). The bucket
# resource's OWN `.planned_values...values` has NO `arn` key either
# (verified directly) -- S3 bucket ARNs are never plan-time-resolved as a
# bucket attribute -- so the expected ARN is derived the same way S3
# itself derives it, `"arn:aws:s3:::" + <bucket-name>`, from the bucket
# resource's own (separately resolved) `values.bucket` name. Falls back to
# this path ONLY when `.planned_values` actually holds a resolved policy
# string; whenever any part of the Resource list embeds a provider-computed
# reference, contagion makes this absent and the graph-edge rule above (or
# the locals/fail-closed rules below) is the only signal available, exactly
# as before.
# `s3_buckets`/`bucket_addrs` above are drawn from `configured_resources`
# (`.configuration.root_module.resources`), which carries `.expressions`
# only -- never a `.values` key (verified directly: a configured
# `aws_s3_bucket` entry's own keys are exactly `["address", "expressions",
# "mode", "name", "provider_config_key", "schema_version", "type"]`, no
# `values`). The bucket's own RESOLVED name (needed to derive its ARN) is
# a `.planned_values` fact, so this looks the bucket up in
# `planned_resources` by address instead.
resolved_bucket_arn(bucket_addr) := sprintf("arn:aws:s3:::%s", [name]) if {
	some pr in planned_resources
	pr.address == bucket_addr
	name := object.get(pr.values, "bucket", null)
	name != null
}

as_resource_list(x) := x if is_array(x)

as_resource_list(x) := [x] if not is_array(x)

resolved_policy_covers(bp, bucket_addr) if {
	some pr in planned_resources
	pr.address == bp.address
	raw := object.get(pr.values, "policy", null)
	raw != null
	doc := json.unmarshal(raw)
	some stmt in doc.Statement
	stmt.Effect == "Deny"
	object.get(object.get(stmt, "Condition", {}), "Bool", {})["aws:SecureTransport"] == "false"
	resources := as_resource_list(stmt.Resource)
	barn := resolved_bucket_arn(bucket_addr)
	barn in resources
	some r2 in resources
	r2 != barn
	startswith(r2, sprintf("%s/", [barn]))
}

resolved_policy_covers_for_bucket(bucket_addr) if {
	some bp in bucket_policies
	resolved_policy_covers(bp, bucket_addr)
}

# MODULE-COMPOSED POLICY. A module builds its bucket policy by combining
# several `aws_iam_policy_document` data sources through a `local`, and a
# `local` has no representation anywhere in plan JSON -- so the policy
# attribute's own references dead-end and its planned value is unknown
# (contagion from the bucket ARN inside it). The evidence that IS in the
# artifact is the documents themselves: a document DECLARED in the same call
# and actually PLANNED -- the module's `count` gates it on the input the agent
# passed, so an unattached document is not planned -- whose statements name
# this bucket twice, once for the bucket ARN and once for the object-ARN
# pattern, is the same two-reference fact `bucket_ref_count` demands of a
# hand-authored policy.
#
# Reachable ONLY where the policy is otherwise unverifiable, so no arm's
# existing verdict moves: on a module-free plan the policy attribute is
# followable (directly, or one hop into its own document) or its value is
# resolved, and this path is never consulted.
module_composed_policy_covers(bp, bucket_addr) if {
	bp.prefix != ""
	some doc in configured_resources
	doc.type == "aws_iam_policy_document"
	doc.prefix == bp.prefix
	planned_here(doc.address)
	count([ref |
		some ref in doc_resource_refs(doc)
		ref == bucket_addr
	]) >= 2
}

planned_here(config_addr) if {
	some pr in planned_resources
	reference_names_block(pr.address, config_addr)
}

# Per-POLICY (not per-bucket) version of the same resolved-value check, used
# to guard the locals-only deny rule below: a `bp` whose Resource list is
# `[local.bucket_arn, "${local.bucket_arn}/*"]` has ALL-`local.`-prefixed
# graph references (so `local_only_refs(bp)` is non-empty) but MAY still
# have a fully resolved `.planned_values` policy value -- exactly like the
# literal-ARN case above, just reached through a `local` instead of typed
# directly. `resolved_policy_covers(bp, bucket_addr)` doesn't care how the
# Resource strings were spelled in HCL, only what they resolved to, so it
# already returns true for this shape once fed the right bucket_addr; this
# just tries every bucket_addr for one specific `bp`.
resolved_policy_covers_any(bp) if {
	some bucket_addr in bucket_addrs
	resolved_policy_covers(bp, bucket_addr)
}

module_composed_policy_covers_for_bucket(bucket_addr) if {
	some bp in bucket_policies
	module_composed_policy_covers(bp, bucket_addr)
}

# LOCALS-HOIST CASE (verifier-found major, 2026-08-21 second pass): a
# `locals { bucket_arn = aws_s3_bucket.x.arn }` + `Resource =
# [local.bucket_arn, "${local.bucket_arn}/*"]` policy is a genuinely
# correct shape (the local really does resolve to this bucket's ARN), but
# `local.*` values are NOT represented anywhere in `terraform show -json`
# plan output's `.configuration` block -- VERIFIED DIRECTLY (this pass,
# offline, hashicorp/aws 6.58.0): `.configuration.root_module` for a real
# plan built from exactly this shape has only `["resources",
# "variables"]` as keys, no `locals` key at all, and the policy
# resource's own `.expressions.policy.references` resolves to
# `["local.bucket_arn", "local.bucket_arn"]` -- the local's OWN defining
# expression is simply not present anywhere in this artifact to follow a
# hop into (unlike the `data.aws_iam_policy_document` one-hop above,
# where the data resource IS a full `configured_resources` entry with its
# own `.expressions`). This is a genuine, unresolvable-from-a-static-
# artifact gap, not a bug to patch around: a `local.bucket_arn` could
# just as easily be a hardcoded literal ARN for an unrelated bucket, and
# this oracle has no way to tell the two apart. `bucket_ref_count` is
# therefore correctly 0 for this shape (the bare address
# "aws_s3_bucket.<x>" never appears), but the generic fail-closed rule
# below used to fire on it with the message "no aws_s3_bucket_policy
# resource references this bucket's ARN at all" -- FACTUALLY FALSE for
# this shape, since the policy does reference the bucket, just not
# visibly so. This rule instead gives an ACCURATE reason (still a deny --
# this is a documented v1 static-oracle scope limit, see this scenario's
# spec YAML "Oracle must tolerate/defend" comments, not an accept) and
# suppresses the generic fail-closed message for the same bucket_policy
# below.
#
# RESOLVED-LOCAL FIX (verifier-found major, 3rd verification pass,
# 2026-08-22): the reasoning above is sound ONLY when the local's value is
# genuinely absent from the plan artifact -- i.e. `local.bucket_arn =
# aws_s3_bucket.x.arn`, where `.planned_values` for the policy resource has
# NO `policy` key at all (VERIFIED DIRECTLY, this pass: `.planned_values
# ...aws_s3_bucket_policy.values` carries no `policy` key for that shape).
# It does NOT hold when the local is built from a fully resolvable literal,
# e.g. `locals { bucket_name = "cdktn-bench-document-archive"; bucket_arn =
# "arn:aws:s3:::${local.bucket_name}" }` -- there `.configuration...
# references` is STILL exactly `["local.bucket_arn", "local.bucket_arn"]`
# (indistinguishable at the graph-edge level from the unresolvable case),
# but `.planned_values...aws_s3_bucket_policy.values.policy` IS fully
# resolved to the two-ARN, SecureTransport-false Deny statement (VERIFIED
# DIRECTLY, this pass, terraform 1.15.8 + hashicorp/aws 6.58.0, `docker run
# --network none cdktn-bench/hcl-raw:dev`) -- the same resolved-value
# signal the literal-ARN fix above already extracts via
# `resolved_policy_covers`. Firing the "cannot verify... local value" deny
# on that plan is factually false (`resolved_policy_covers_any(bp)` is
# `true` for it) and scored a genuinely-working solution 0.0. Guarding this
# rule with `not resolved_policy_covers_any(bp)` -- exactly mirroring the
# guard the fail-closed rule below already has -- restores the accurate
# message to ONLY the sub-case this comment block was originally written
# for (no resolved `.planned_values` policy at all), while a resolvable
# locals-hoist now falls through to the same silent accept every other
# resolvable shape gets.
local_only_refs(bp) := refs if {
	refs := policy_references(bp)
	count(refs) > 0
	every ref in refs {
		startswith(ref, "local.")
	}
}

# Only counts a policy as "local-only" for suppression purposes if it is
# ALSO unresolvable (mirrors the deny rule's own guard immediately below).
# Otherwise a resolved locals-hoisted policy for bucket A -- which no
# longer gets the locals deny message itself -- would still poison this
# set and suppress the fail-closed rule below for an UNRELATED bucket B
# that genuinely has no policy at all.
local_only_policies contains bp.address if {
	some bp in bucket_policies
	local_only_refs(bp)
	not resolved_policy_covers_any(bp)
}

deny contains msg if {
	some bp in bucket_policies
	refs := local_only_refs(bp)
	not resolved_policy_covers_any(bp)
	msg := sprintf(
		"%s: policy's Resource expression references only local value(s) (%v) -- Terraform's plan JSON `.configuration` representation does not expose a `local` value's own definition anywhere, so this oracle cannot verify from a static artifact whether it resolves to this bucket's ARN (a documented v1 static-oracle scope limit -- verified directly, 2026-08-21, that `.configuration.root_module` carries no `locals` key at all). Author the Deny statement's Resource list referencing the aws_s3_bucket resource (or a one-hop data.aws_iam_policy_document) directly, not through a local value.",
		[bp.address, refs],
	)
}

# Fail-closed: a bucket exists but no aws_s3_bucket_policy resource
# references it at all (by ANY bucket, not just via bucket_ref_count,
# since a policy referencing zero bucket ARNs has bucket_ref_count 0 for
# every bucket and the rule above only fires on 1 <= n < 2). Guarded
# against `local_only_policies` (immediately above) so a locals-hoisted
# policy gets ONLY the accurate "references only a local value" message,
# never ALSO this generic, factually-false-for-that-shape one. ALSO guarded
# against `resolved_policy_covers_for_bucket` (literal-ARN shape, above):
# a policy whose Resource list is written as literal ARN strings has ZERO
# graph-edge references to the bucket (correctly 0 here) but IS fully
# resolved and IS verifiably correct in `.planned_values` -- firing this
# generic "no policy references this bucket's ARN at all" message on it
# would be factually false the same way it would be for the locals case.
deny contains msg if {
	some bucket_addr in bucket_addrs
	referencing := [bp |
		some bp in bucket_policies
		bucket_ref_count(bp, bucket_addr) > 0
	]
	count(referencing) == 0
	count(local_only_policies) == 0
	not resolved_policy_covers_for_bucket(bucket_addr)
	not module_composed_policy_covers_for_bucket(bucket_addr)
	not module_policy_unverifiable(bucket_addr)
	msg := sprintf(
		"%s: no aws_s3_bucket_policy resource references this bucket's ARN at all -- the TLS-deny requirement cannot be satisfied without one",
		[bucket_addr],
	)
}

# A module-authored bucket policy whose content this artifact does not carry:
# the module composed it from a `local`, which plan JSON never represents, and
# its planned value is unknown because the bucket ARN is inside it. Denied,
# not accepted -- the two-ARN fact is exactly what this scenario measures, and
# an unverifiable policy is not a verified one -- but with the reason it has
# rather than the generic rule's "no policy references this bucket at all",
# which is false here: a policy IS attached. The same documented static-oracle
# scope limit the local-value rule above records, reached through a module
# input instead of through a `locals` block.
module_policy_unverifiable(bucket_addr) if {
	some bp in bucket_policies
	bp.prefix != ""
	bucket_ref_count(bp, bucket_addr) == 0
	not resolved_policy_covers(bp, bucket_addr)
	not module_composed_policy_covers(bp, bucket_addr)
}

deny contains msg if {
	some bucket_addr in bucket_addrs
	some bp in bucket_policies
	bp.prefix != ""
	bucket_ref_count(bp, bucket_addr) == 0
	not resolved_policy_covers(bp, bucket_addr)
	not module_composed_policy_covers(bp, bucket_addr)
	msg := sprintf(
		"%s: this module composes its bucket policy from a local value, so neither the policy's own references nor its planned value carry what it grants for %s -- nothing in this plan shows the TLS deny covering the object ARNs as well as the bucket ARN. Pass the policy through the module input that builds the deny-insecure-transport statement itself, whose Resource list this plan does carry.",
		[bp.address, bucket_addr],
	)
}

# --- rule 2: every-subresource-targets-this-bucket-tf ----------------------

s3_subresource_types := {
	"aws_s3_bucket_versioning",
	"aws_s3_bucket_server_side_encryption_configuration",
	"aws_s3_bucket_public_access_block",
	"aws_s3_bucket_policy",
}

s3_subresources := [r |
	some r in configured_resources
	r.type in s3_subresource_types
]

references_a_bucket(r) if {
	some ref in object.get(r.expressions.bucket, "references", [])
	some bucket_addr in bucket_addrs
	reference_names_block(ref, bucket_addr)
}

deny contains msg if {
	some r in s3_subresources
	not references_a_bucket(r)
	msg := sprintf(
		"%s: %s's `bucket` argument does not reference any aws_s3_bucket resource this configuration creates (hardcoded literal name, or a reference to something else entirely)",
		[r.address, r.type],
	)
}

# --- rule 3: sse-kms-references-created-key-tf ------------------------------

sse_configs := [r |
	some r in configured_resources
	r.type == "aws_s3_bucket_server_side_encryption_configuration"
]

kms_master_key_refs(r) := refs if {
	some rule in r.expressions.rule
	some default_block in rule.apply_server_side_encryption_by_default
	refs := object.get(default_block.kms_master_key_id, "references", [])
} else := []

kms_aliases_by_addr := {r.address: r |
	some r in configured_resources
	r.type == "aws_kms_alias"
}

# IN-CONFIG KMS ALIAS one-hop (verifier-found major, 2026-08-21 second
# pass): `kms_master_key_id = aws_kms_alias.x.arn` where
# `aws_kms_alias.x.target_key_id = aws_kms_key.y.key_id` is a genuinely
# correct "a key created in this same configuration" shape (unlike the
# locals-hoist case above, an `aws_kms_alias` resource IS a full
# `configured_resources` entry with its own real `.expressions`, exactly
# like `data.aws_iam_policy_document` above -- there is a hop to follow,
# not a gap). VERIFIED DIRECTLY (this pass, offline, hashicorp/aws
# 6.58.0): the SSE config's own `kms_master_key_id.references` resolves
# to `["aws_kms_alias.archive.arn", "aws_kms_alias.archive"]` (no
# `aws_kms_key.` prefix, so the direct-only check below used to reject
# this shape outright), while `aws_kms_alias.archive`'s OWN
# `.expressions.target_key_id.references` resolves to
# `["aws_kms_key.archive.key_id", "aws_kms_key.archive"]` -- the created
# key's bare address IS visible, one hop down. Mirrors
# `policy_references()`'s own one-hop pattern: iterate the direct refs,
# take the first one that is a valid alias-map key (the bare address,
# never the `.arn`-suffixed entry), and follow it.
resolved_kms_key_refs(r) := refs if {
	direct := kms_master_key_refs(r)
	some ref in direct
	alias := kms_aliases_by_addr[ref]
	refs := object.get(alias.expressions.target_key_id, "references", [])
} else := kms_master_key_refs(r)

references_a_kms_key(r) if {
	some ref in resolved_kms_key_refs(r)
	some key_addr in kms_key_addrs
	reference_names_block(ref, key_addr)
}

# THE SAME EDGE, READ ONE SCOPE UP, for an SSE configuration a MODULE
# declares. The module writes its `rule` block as a `dynamic` block, which
# Terraform's configuration representation omits entirely, so
# `kms_master_key_refs` above has nothing to read and no amount of address
# qualification recovers it. What the agent actually authored is the CALL: the
# key reaches the bucket through one of the call's arguments, so the edge is
# read there instead, following a `module.<call>.<output>` reference one hop
# into that output's own expression.
#
# Coarser than the direct read in exactly one way, stated here because it is
# the strictness this arm is graded at: it does not check WHICH argument
# carries the key, only that the call passes a key this configuration creates.
# Naming the argument would be naming one module's input, which is not a fact
# about the scenario. The catch it has to decide -- a hardcoded/imported key
# ARN literal -- passes no key reference at all and is denied either way.
references_a_kms_key(r) if {
	r.prefix != ""
	some ref in call_argument_refs(r.prefix)
	some resolved in resolution_of(ref)
	some key_addr in kms_key_addrs
	reference_names_block(resolved, key_addr)
}

# A reference, plus whatever a `module.<call>.<output>` reference resolves to.
resolution_of(ref) := {ref} | module_output_refs(ref)

resolution_of(ref) := {ref} if not module_output_refs(ref)

deny contains msg if {
	some r in sse_configs
	not references_a_kms_key(r)
	msg := sprintf(
		"%s: kms_master_key_id does not reference any aws_kms_key resource this configuration creates -- an imported/hardcoded key ARN literal is not verifiably 'a key we control' from a static artifact",
		[r.address],
	)
}
