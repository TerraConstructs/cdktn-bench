# Hand-authored awscdk tier-1 bundle (ROADMAP.md M8: OPA/Rego grades tier 1
# on every arm). `input` is the awscdk arm's synthesized CloudFormation
# template, cdk.out/ScenarioStack.template.json. Intent:
# oracles/acm-dns-validation-record-wiring/intent.md.
#
# Encodes validation-options-name-the-zone: both validated domain names --
# the apex and its www alias -- must have a DomainValidationOptions entry,
# and each entry's HostedZoneId must resolve, by LOGICAL ID through Ref /
# Fn::GetAtt, to an AWS::Route53::HostedZone created in this same template.
# That join is the CFN twin of the TF policy's own `references_a_created_zone`
# edge on a record's `zone_id`: same fact, same strictness, both arms.
#
# not_verifiable: a HostedZoneId built from an Fn::ImportValue or a template
# Parameter names a zone this template cannot see. Recorded, never denied --
# the verdict the retired cfn-guard `HostedZoneId EXISTS` rule also gave it.
#
# Strictness vs the retired oracles/cfn-guard/<id>/policy.guard: the guard
# accepted ANY HostedZoneId, a literal zone id this template never creates
# included; the logical-id join it could not express refuses that. No fixture
# verdict changes (reference PASS, both broken fixtures FAIL as before).

package cdktn_bench.acm_dns_validation_record_wiring

import rego.v1

validated_domain_names := {"storefront.example.com", "www.storefront.example.com"}

certificates[lid] := r if {
	some lid, r in input.Resources
	r.Type == "AWS::CertificateManager::Certificate"
}

hosted_zone_logical_ids := {lid |
	some lid, r in input.Resources
	r.Type == "AWS::Route53::HostedZone"
}

validation_options(cert) := object.get(cert, ["Properties", "DomainValidationOptions"], [])

options_for(cert, domain) := [o |
	some o in validation_options(cert)
	object.get(o, "DomainName", null) == domain
]

# The logical id a HostedZoneId intrinsic names, when it names one at all.
referenced_logical_id(v) := lid if lid := v.Ref

referenced_logical_id(v) := lid if {
	arr := v["Fn::GetAtt"]
	lid := arr[0]
}

# A HostedZoneId whose value only exists after another stack deploys, or is
# supplied at deploy time: nothing in this template can decide it.
deploy_time_only(v) if v["Fn::ImportValue"]

deploy_time_only(v) if {
	lid := v.Ref
	object.get(input, ["Parameters", lid], null) != null
}

names_created_zone(v) if {
	lid := referenced_logical_id(v)
	lid in hosted_zone_logical_ids
}

# Fail-closed companion: a hosted zone exists but no certificate does, so
# every rule below would be vacuous.
deny contains msg if {
	count(hosted_zone_logical_ids) > 0
	count(certificates) == 0
	msg := "a public hosted zone exists but no AWS::CertificateManager::Certificate resource was found in the template"
}

deny contains msg if {
	some lid, cert in certificates
	some domain in validated_domain_names
	count(options_for(cert, domain)) == 0
	msg := sprintf(
		"AWS::CertificateManager::Certificate %q (logical id) has no DomainValidationOptions entry naming %q -- that domain will never get a DNS validation record and the certificate cannot reach ISSUED on its own",
		[lid, domain],
	)
}

deny contains msg if {
	some lid, cert in certificates
	some domain in validated_domain_names
	some o in options_for(cert, domain)
	not "HostedZoneId" in object.keys(o)
	msg := sprintf(
		"AWS::CertificateManager::Certificate %q (logical id): the %q DomainValidationOptions entry has no HostedZoneId -- ACM has no hosted zone to write that domain's validation record into",
		[lid, domain],
	)
}

deny contains msg if {
	some lid, cert in certificates
	some domain in validated_domain_names
	some o in options_for(cert, domain)
	"HostedZoneId" in object.keys(o)
	not names_created_zone(o.HostedZoneId)
	not deploy_time_only(o.HostedZoneId)
	msg := sprintf(
		"AWS::CertificateManager::Certificate %q (logical id): the %q DomainValidationOptions entry's HostedZoneId does not reference an AWS::Route53::HostedZone created in this template -- the validation record would land in a zone this configuration does not own",
		[lid, domain],
	)
}

not_verifiable contains msg if {
	some lid, cert in certificates
	some domain in validated_domain_names
	some o in options_for(cert, domain)
	deploy_time_only(o.HostedZoneId)
	msg := sprintf(
		"AWS::CertificateManager::Certificate %q (logical id): the %q DomainValidationOptions entry's HostedZoneId comes from an Fn::ImportValue or a template Parameter, so whether it is the hosted zone this configuration creates cannot be decided from the template alone",
		[lid, domain],
	)
}
