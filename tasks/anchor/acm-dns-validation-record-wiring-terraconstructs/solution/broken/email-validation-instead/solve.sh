#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the email-validation-instead catch: `validation` is
# explicitly set to EMAIL. (CORRECTION, 2026-08-21, made while verifying
# this fixture directly against a real `node main.js` synth run: an
# EARLIER draft of this fixture simply OMITTED `validation` entirely,
# reasoning from `PublicCertificate`'s own documented default-to-EMAIL
# behavior -- but with a SAN present (this ticket always has one, the
# `www` alias), omitting `validation` does not silently reach a green
# EMAIL plan at all. `renderDomainValidation`'s EMAIL branch requires a
# `validationDomains` entry for EVERY domain name, and the constructor's
# own auto-default only ever populates the PRIMARY domain name's entry
# (certificate.js: `validationDomains: { [props.domainName]:
# props.domainName }`) -- so omission actually THROWS at synth
# (`Error: When using email for validation, 'validationDomains' needs to
# be supplied`), verified directly. Reward is still 0.0 either way (a
# thrown synth is a toolchain failure, tier 0 never even runs), but the
# THROW is not the same falsifying mechanism the spec's own
# email-validation-instead description claims -- an explicit EMAIL choice
# is the fixture that actually demonstrates "typed, valid enum member,
# plan-green, caught only by validation-method-is-dns". This fixture
# supplies `validationDomains` for both names so the certificate SANs stay
# correct and EMAIL alone is what's being tested.)
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, edge } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new edge.DnsZone(this, "StorefrontZone", {
      zoneName: "storefront.example.com",
    });

    // THE MISTAKE: EMAIL validation, not DNS.
    new edge.PublicCertificate(this, "StorefrontCertificate", {
      domainName: "storefront.example.com",
      subjectAlternativeNames: ["www.storefront.example.com"],
      validation: {
        method: edge.ValidationMethod.EMAIL,
        validationDomains: {
          "storefront.example.com": "storefront.example.com",
          "www.storefront.example.com": "storefront.example.com",
        },
      },
    });
  }
}
TS

bash tests/static_tiers.sh
