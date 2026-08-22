#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the missing-certificate-validation-resource catch on
# this arm's own L1 escape hatch (the L2 `edge.PublicCertificate` cannot
# produce this mistake at all -- see this catch's applies_to in the spec):
# both DNS validation records are authored correctly (one per domain,
# correctly zone-scoped), but no
# `acmCertificateValidation.AcmCertificateValidation` resource exists.
# Plan-green in full, and validation-records-one-per-domain itself PASSES
# (count is exactly 2). Reward must be 0.0 from tier-1 alone --
# validation-waits-for-records fires on zero
# aws_acm_certificate_validation resources existing anywhere.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, edge } from "terraconstructs/lib/aws";
import { acmCertificate, route53Record } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const zone = new edge.DnsZone(this, "StorefrontZone", {
      zoneName: "storefront.example.com",
    });

    const cert = new acmCertificate.AcmCertificate(this, "StorefrontCertificate", {
      domainName: "storefront.example.com",
      subjectAlternativeNames: ["www.storefront.example.com"],
      validationMethod: "DNS",
    });

    new route53Record.Route53Record(this, "ValidationRecordApex", {
      zoneId: zone.zoneId,
      name: cert.domainValidationOptions.get(0).resourceRecordName,
      type: cert.domainValidationOptions.get(0).resourceRecordType,
      records: [cert.domainValidationOptions.get(0).resourceRecordValue],
      ttl: 60,
      allowOverwrite: true,
    });

    new route53Record.Route53Record(this, "ValidationRecordWww", {
      zoneId: zone.zoneId,
      name: cert.domainValidationOptions.get(1).resourceRecordName,
      type: cert.domainValidationOptions.get(1).resourceRecordType,
      records: [cert.domainValidationOptions.get(1).resourceRecordValue],
      ttl: 60,
      allowOverwrite: true,
    });

    // THE MISTAKE: no AcmCertificateValidation -- nothing ever waits for
    // the two records above to be observed by ACM.
  }
}
TS

bash tests/static_tiers.sh
