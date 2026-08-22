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

qualifying_record_config_addresses := {c.address |
	some c in input.configuration.root_module.resources
	c.type == "aws_route53_record"
	refs := object.get(object.get(c, "expressions", {}), "zone_id", {}).references
	references_a_created_zone(refs)
}

# Every PLANNED instance of a qualifying config address -- covers both a
# plain (no for_each/count) block, whose sole planned instance's `.address`
# equals the config address exactly, and a for_each/count-expanded block,
# whose planned instances are `<address>["key"]` / `<address>[N]`.
validation_record_instances := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_route53_record"
	some qa in qualifying_record_config_addresses
	r.address == qa
]

validation_record_instances_expanded := [r |
	some r in input.planned_values.root_module.resources
	r.type == "aws_route53_record"
	some qa in qualifying_record_config_addresses
	startswith(r.address, sprintf("%s[", [qa]))
]

all_validation_records := array.concat(validation_record_instances, validation_record_instances_expanded)

# "!= 2" (not "< 2") is the one predicate this catch family needs: it fires
# identically on 0 (no-validation-records-at-all), 1
# (one-record-for-two-domains), and -- just as correctly, though no catch
# targets it -- on 3+ (a stray extra record). Fail-closed by construction:
# an EMPTY qualifying_record_config_addresses set (no route53_record
# references the created zone at all) makes all_validation_records empty
# too, count 0, and this still fires -- no separate "zero exists" rule
# needed the way validation-waits-for-records below needs one (that fact
# has no natural "!= N" framing since N is 1, not a fixed 2).
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

validation_configs := [c |
	some c in input.configuration.root_module.resources
	c.type == "aws_acm_certificate_validation"
]

# Fail-closed companion (mirrors s3-lambda-log-retention's own
# "role_has_no_recognized_policy" convention): a certificate exists in this
# plan but zero aws_acm_certificate_validation resources exist anywhere --
# catches missing-certificate-validation-resource directly, and doubles as
# a second, independent signal on no-validation-records-at-all (which also
# tends to omit the resource that would have nothing to wait for).
deny contains msg if {
	some cert in input.planned_values.root_module.resources
	cert.type == "aws_acm_certificate"
	count(validation_configs) == 0
	msg := sprintf(
		"%s exists but no aws_acm_certificate_validation resource exists anywhere in this configuration -- nothing ever waits for the DNS validation records to be observed, so ISSUED is never confirmed",
		[cert.address],
	)
}

deny contains msg if {
	some cfg in validation_configs
	refs := object.get(object.get(cfg, "expressions", {}), "validation_record_fqdns", {}).references
	count([r | some r in refs; startswith(r, "aws_route53_record.")]) == 0
	msg := sprintf(
		"%s's validation_record_fqdns does not reference any aws_route53_record resource created in this configuration",
		[cfg.address],
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
