# oracles/rego/acm-dns-validation-record-wiring/policy.rego -- HAND-AUTHORED
# (SCHEMA.md §8.2 rule 7). Encodes specs/acm-dns-validation-record-wiring.yaml's
# tier-"1" structural_asserts `validation-records-one-per-domain` and
# `validation-waits-for-records` (both applies_to: [hcl_raw, terraconstructs])
# + oracle.rego_hints. Graded against `terraform show -json` PLAN JSON for
# BOTH TF-shaped arms -- specs/SCHEMA.md §4.2/§8. `input` at policy-evaluation
# time is that plan JSON document. A generated tests/static_tiers.sh runs
#   opa eval -f raw -I -d policy.rego \
#     'data.cdktn_bench.acm_dns_validation_record_wiring.deny' < plan.json
# and fails tier-1 iff that result set is non-empty.
#
# Intent doc: oracles/acm-dns-validation-record-wiring/intent.md
#
# WHY BOTH FACTS ARE TIER 1 AND NOT TIER 0.
#   - validation-records-one-per-domain needs a CARDINALITY count ("exactly
#     2, one per validated domain name"). SCHEMA.md §4.2's op table has no
#     count/length op -- `set_eq` dedups to a SET and can't count instances,
#     `contains`/`in` only assert membership. Cardinality is Rego's job.
#   - Both facts are also GRAPH-EDGE checks (SCHEMA.md §4.2.1): a record's
#     `zone_id` and a validation resource's `validation_record_fqdns` are
#     built from provider-computed attributes of resources THIS
#     configuration creates (the zone's own `.zone_id`, a record's own
#     `.fqdn`) and are therefore plan-time-UNKNOWN -- `.planned_values...
#     values.zone_id` resolves to `null` for a CORRECT solution exactly as
#     often as an incorrect one, so a value-content check there would be
#     unfalsifiable both ways. `.configuration...expressions.<attr>.
#     references` is populated from the HCL source itself and stays known
#     regardless.
#
# TWO SHAPES ACCEPTED (specs/acm-dns-validation-record-wiring.yaml's own
# "ORACLE MUST TOLERATE / DEFEND" header comment, point 1): a `for_each`
# over a transform of `domain_validation_options`, or two separately-named
# `aws_route53_record` resources. Neither rule below reads the CONFIG
# ADDRESS'S NAME or whether it came from `for_each`/`count` expansion --
# only (a) whether its `zone_id` expression references a zone created here,
# and (b) how many `.planned_values` INSTANCES exist at that address (one
# per for_each key, or exactly one for a plain block). Both shapes produce
# the same counted fact.
#
# `type` ("CNAME") is deliberately NEVER READ here (see the spec's own
# "ORACLE MUST TOLERATE / DEFEND" point 2): a correct solution that derives
# `type` from the certificate's own `domain_validation_options[*].
# resource_record_type` has an unknown `.values.type` at plan time, exactly
# like `zone_id`. Only the Terraform RESOURCE TYPE (`aws_route53_record`,
# always known) and the zone_id graph edge are checked.
#
# Verified against real `terraform init && terraform plan` output for both
# TF-shaped arms: this scenario's own reference solution/solve.sh (PASS,
# `deny` empty) and every solution/broken/<catch>/ fixture for
# no-validation-records-at-all, one-record-for-two-domains and
# missing-certificate-validation-resource (each FAIL, `deny` non-empty --
# see this repo's `make falsifiability`/`make grading-proof` output for this
# spec).

package cdktn_bench.acm_dns_validation_record_wiring

import rego.v1

# --------------------------------------------------------------------------
# The configuration-side module walk
#
# The normalised plan hoists every module resource into
# `planned_values.root_module.resources`, so the VALUES side needs no
# module-aware path (oracles/rego/README.md "How a policy addresses a module
# resource"). The CONFIGURATION side is not hoisted: a module's own resource
# blocks stay under `configuration.root_module.module_calls.<call>.module.
# resources`, and both facts below are graph-edge facts read from there
# (SCHEMA.md §4.2.1 -- a zone_id/fqdn VALUE is plan-time-unknown for a correct
# solution). A rule that reads `configuration.root_module.resources` alone
# therefore sees nothing at all on the hcl_modules arm and denies a correct
# module-composed solution.
#
# `config_modules` is the root module node plus every module-call body, each
# paired with the path that reached it. A module node path alternates
# "module_calls" / <call name> / "module", so its length is a multiple of 3
# and every third segment is a literal -- that shape is the filter, because
# `walk` yields every sub-object in the document and only these are modules.
# For a plan with no module in it the set is exactly `[[], root_module]` and
# every rule below reduces to what it was before this walk existed.
# --------------------------------------------------------------------------

segment_ok(p, i) if {
	i % 3 == 0
	p[i] == "module_calls"
}

segment_ok(p, i) if i % 3 == 1

segment_ok(p, i) if {
	i % 3 == 2
	p[i] == "module"
}

is_module_node_path(p) if {
	count(p) % 3 == 0
	every i, _ in p {
		segment_ok(p, i)
	}
}

config_modules contains [p, m] if {
	walk(input.configuration.root_module, [p, m])
	is_module_node_path(p)
	is_object(m)
}

config_resources contains [p, r] if {
	some [p, m] in config_modules
	some r in m.resources
	is_object(r)
}

# The address prefix a resource configured at module node path `p` carries in
# `planned_values` after hoisting: "" at the root, "module.<call>." per level.
# Instance keys are NOT reconstructed here -- a module call with count/for_each
# plans as `module.<call>[k].…`, which no prefix built from the configuration
# can name; such a record simply fails to match and the count rule below denies
# it, which is the fail-closed direction.
module_prefix(p) := concat("", [sprintf("module.%s.", [n]) |
	some i, n in p
	i % 3 == 1
])

# The `module_calls.<call>` node that instantiated module node path `p`: the
# same path with its trailing "module" segment dropped.
calling_node(p) := object.get(input.configuration.root_module, array.slice(p, 0, count(p) - 1), {})

references(r, attribute) := object.get(object.get(r, "expressions", {}), attribute, {}).references

# --------------------------------------------------------------------------
# validation-records-one-per-domain
# --------------------------------------------------------------------------

created_zone_addresses := {addr |
	some r in input.planned_values.root_module.resources
	r.type == "aws_route53_zone"
	addr := r.address
}

references_a_created_zone(refs) if {
	some ref in refs
	some z in created_zone_addresses
	startswith(ref, z)
}

# A zone created INSIDE a module call is named by the caller through that
# call's output (`module.<call>.id`), never by the zone's own hoisted address,
# so every created zone's call prefix is a valid reference prefix too. A call
# with count/for_each hoists as `module.<call>[k].…`, which no plain
# `module.<call>.…` reference matches -- still denied, the fail-closed
# direction. With no module-created zone the set is empty and this second
# definition never holds: hcl_raw/terraconstructs strictness is unchanged.
created_zone_call_prefixes := {prefix |
	some addr in created_zone_addresses
	startswith(addr, "module.")
	prefix := concat("", ["module.", split(trim_prefix(addr, "module."), ".")[0], "."])
}

references_a_created_zone(refs) if {
	some ref in refs
	some prefix in created_zone_call_prefixes
	startswith(ref, prefix)
}

# A record's `zone_id` references, spelled as absolute plan addresses.
#
# At the root (`module_prefix` empty) this is the reference list verbatim --
# the hcl_raw and terraconstructs reading, unchanged. Inside a module the
# record's own expression names the module's INPUT (`var.zone_id`), so the
# reference that decides the fact is the argument the caller passed for that
# input: one hop up, qualified with the caller's own prefix. Only that one hop
# is resolved. An argument that is itself a `var.…` (a module calling a module
# and forwarding the input) stays unresolved, the record does not qualify, and
# the count rule denies -- the fail-closed direction, and no module this arm
# serves nests the acm record that deep.
absolute_zone_refs(p, r) := {ref |
	some ref in references(r, "zone_id")
	not startswith(ref, "var.")
} | {qualified |
	some ref in references(r, "zone_id")
	startswith(ref, "var.")
	name := split(trim_prefix(ref, "var."), ".")[0]
	some arg in references(calling_node(p), name)
	not startswith(arg, "var.")
	qualified := concat("", [module_prefix(array.slice(p, 0, count(p) - 3)), arg])
}

qualifying_record_addresses := {addr |
	some [p, c] in config_resources
	c.type == "aws_route53_record"
	references_a_created_zone(absolute_zone_refs(p, c))
	addr := concat("", [module_prefix(p), c.address])
}

# Every PLANNED instance of a qualifying config address -- covers both a
# plain (no for_each/count) block, whose sole planned instance's `.address`
# equals the config address exactly, and a for_each/count-expanded block,
# whose planned instances are `<address>["key"]` / `<address>[N]` (the shape
# the acm module's own one-record-per-domain `count` plans as).
validation_record_instances := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_route53_record"
	some qa in qualifying_record_addresses
	r.address == qa
]

validation_record_instances_expanded := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_route53_record"
	some qa in qualifying_record_addresses
	startswith(r.address, sprintf("%s[", [qa]))
]

all_validation_records := array.concat(validation_record_instances, validation_record_instances_expanded)

# "!= 2" (not "< 2") is the one predicate this catch family needs: it fires
# identically on 0 (no-validation-records-at-all), 1
# (one-record-for-two-domains), and -- just as correctly, though no catch
# targets it -- on 3+ (a stray extra record). Fail-closed by construction:
# an EMPTY qualifying_record_addresses set (no route53_record references the
# created zone at all) makes all_validation_records empty too, count 0, and
# this still fires -- no separate "zero exists" rule needed the way
# validation-waits-for-records below needs one (that fact has no natural
# "!= N" framing since N is 1, not a fixed 2).
deny contains msg if {
	count(all_validation_records) != 2
	msg := sprintf(
		"expected exactly 2 aws_route53_record resources (one per validated domain name -- the apex and www) referencing the hosted zone created in this configuration; found %d",
		[count(all_validation_records)],
	)
}

# --------------------------------------------------------------------------
# validation-waits-for-records
# --------------------------------------------------------------------------

validation_configs := [[p, c] |
	some [p, c] in config_resources
	c.type == "aws_acm_certificate_validation"
]

planned_validations := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_acm_certificate_validation"
]

# Fail-closed companion (mirrors s3-lambda-log-retention's own
# "role_has_no_recognized_policy" convention): a certificate is planned but
# no aws_acm_certificate_validation is -- catches
# missing-certificate-validation-resource directly, and doubles as a second,
# independent signal on no-validation-records-at-all (which also tends to
# omit the resource that would have nothing to wait for).
#
# The count is over PLANNED resources, not over configuration blocks. A
# resource block with no count/for_each always plans exactly one instance, so
# on a module-free plan the two readings are the same set and this rule is
# what it always was. They diverge inside a module, where the block is
# declared unconditionally and a `count = <flag> ? 1 : 0` is what a flag such
# as acm@6.3.1's `wait_for_validation` switches off: the configuration still
# carries the block, and only the values side records that nothing waits.
deny contains msg if {
	some cert in input.planned_values.root_module.resources
	cert.type == "aws_acm_certificate"
	count(planned_validations) == 0
	msg := sprintf(
		"%s exists but no aws_acm_certificate_validation resource is planned anywhere in this configuration -- nothing ever waits for the DNS validation records to be observed, so ISSUED is never confirmed",
		[cert.address],
	)
}

# The reference is matched where it is WRITTEN, not as an absolute address:
# a module's own `aws_acm_certificate_validation` names the module's own
# `aws_route53_record` block, at the same strictness the root-level reading
# has always applied to a root-level reference.
deny contains msg if {
	some [p, cfg] in validation_configs
	refs := references(cfg, "validation_record_fqdns")
	count([r | some r in refs; startswith(r, "aws_route53_record.")]) == 0
	msg := sprintf(
		"%s's validation_record_fqdns does not reference any aws_route53_record resource created in this configuration",
		[concat("", [module_prefix(p), cfg.address])],
	)
}

# --------------------------------------------------------------------------
# not_verifiable (SCHEMA.md §4.2.1): not needed for this scenario. Both
# facts above are fully resolvable from graph-edge references alone -- there
# is no value-content half left unchecked the way s3-lambda-log-retention's
# SourceArn-scoping check has one. No `not_verifiable` rule is defined;
# per SCHEMA.md §4.2.1's own convention, an undefined `not_verifiable`
# evaluates to empty and no marker is ever written.
# --------------------------------------------------------------------------
