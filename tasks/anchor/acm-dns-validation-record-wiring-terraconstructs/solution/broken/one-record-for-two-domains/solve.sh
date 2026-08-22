#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the one-record-for-two-domains catch on this arm's
# own L1 escape hatch (the L2 `edge.PublicCertificate` cannot produce this
# mistake at all -- see this catch's applies_to in the spec): builds the
# certificate at the L1, then authors exactly ONE
# `route53Record.Route53Record`, reused as the sole input to
# `acmCertificateValidation.AcmCertificateValidation`. Plan-green in full.
# Reward must be 0.0 from tier-1 alone -- validation-records-one-per-domain
# fires on count 1 != 2.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, edge } from "terraconstructs/lib/aws";
import {
  acmCertificate,
  acmCertificateValidation,
  route53Record,
} from "@cdktn/provider-aws";

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

    // THE MISTAKE: one record, reused for "the" validation -- never a
    // second one for the other SAN. `.domainValidationOptions.get(0)` is
    // the same complex-list-token accessor edge.PublicCertificate's own
    // constructor uses (lib/aws/edge/certificate.js) -- indexing into a
    // provider-computed, plan-time-unknown list is normal cdktf idiom, not
    // a mistake by itself; the mistake is stopping at ONE record.
    const record = new route53Record.Route53Record(this, "ValidationRecord", {
      zoneId: zone.zoneId,
      name: cert.domainValidationOptions.get(0).resourceRecordName,
      type: cert.domainValidationOptions.get(0).resourceRecordType,
      records: [cert.domainValidationOptions.get(0).resourceRecordValue],
      ttl: 60,
      allowOverwrite: true,
    });

    new acmCertificateValidation.AcmCertificateValidation(this, "Validation", {
      certificateArn: cert.arn,
      validationRecordFqdns: [record.fqdn],
    });
  }
}
TS

bash tests/static_tiers.sh
