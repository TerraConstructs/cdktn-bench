#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the no-validation-records-at-all catch on the L2
# construct's own escape hatch: builds the certificate at the L1
# (`@cdktn/provider-aws` `acmCertificate.AcmCertificate`) instead of the L2
# `edge.PublicCertificate`, which is the one shape that can omit the
# wiring `PublicCertificate`'s own constructor otherwise guarantees. The
# zone and certificate are created, and nothing else -- no
# aws_route53_record, no aws_acm_certificate_validation. Plan-green in
# full (tier 0 passes: zone exists, certificate exists with the right
# domain/SAN/validation method). Reward must be 0.0 from tier-1
# (policy.rego) alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, edge } from "terraconstructs/lib/aws";
import { acmCertificate } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new edge.DnsZone(this, "StorefrontZone", {
      zoneName: "storefront.example.com",
    });

    // THE MISTAKE: dropping to the L1 certificate resource directly --
    // no DNS validation records, no wait resource, nothing wiring this to
    // the zone above at all.
    new acmCertificate.AcmCertificate(this, "StorefrontCertificate", {
      domainName: "storefront.example.com",
      subjectAlternativeNames: ["www.storefront.example.com"],
      validationMethod: "DNS",
    });
  }
}
TS

bash tests/static_tiers.sh
