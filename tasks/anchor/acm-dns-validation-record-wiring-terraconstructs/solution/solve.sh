#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Verified directly at authoring time (2026-08-21) against the pinned
# 0.2.13 package (terraconstructs 0.2.13, cdktn 0.23.0,
# @cdktn/provider-aws 24.8.0): a real `npx tsc && node main.js` (synth) then
# `terraform init && terraform plan` against this exact shape produces
# `aws_route53_zone` + `aws_acm_certificate` + two `aws_route53_record`
# (one per validated domain, each `zone_id`-referencing the zone) + one
# `aws_acm_certificate_validation` referencing both records' `.fqdn` --
# `edge.PublicCertificate`'s own constructor does the wiring (lib/aws/edge/
# certificate.js, source-verified in this spec's own header comment); the
# agent only has to name the hosted zone via `validation.hostedZone`.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, edge } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const zone = new edge.DnsZone(this, "StorefrontZone", {
      zoneName: "storefront.example.com",
    });

    // edge.PublicCertificate does the DNS-validation wiring itself once
    // told which hosted zone to write the challenge records into: one
    // Route53 record per validated domain name, plus the
    // AcmCertificateValidation resource that waits on them. No further
    // agent-authored resource is required or accepted as evidence here.
    new edge.PublicCertificate(this, "StorefrontCertificate", {
      domainName: "storefront.example.com",
      subjectAlternativeNames: ["www.storefront.example.com"],
      validation: {
        method: edge.ValidationMethod.DNS,
        hostedZone: zone,
      },
    });
  }
}
TS

bash tests/static_tiers.sh
