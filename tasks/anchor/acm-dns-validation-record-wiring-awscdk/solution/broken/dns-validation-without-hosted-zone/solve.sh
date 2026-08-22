#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the dns-validation-without-hosted-zone catch:
# `CertificateValidation.fromDns()` is called with NO hosted-zone argument.
# The hosted zone IS created in this fixture (so `hosted-zone-exists`
# still passes) -- the mistake is that it is never threaded into the
# certificate's own validation config, i.e. the awscdk-side sibling of
# `no-validation-records-at-all` (that catch's own TF-shaped mistake is
# "no record was created at all"; this arm has no agent-authored record to
# omit, so the equivalent mistake is "the certificate's own reference to
# the zone was never wired").
#
# Source-verified directly (2026-08-21) against aws-cdk-lib 2.263.0's own
# aws-certificatemanager/lib/certificate.ts, `renderDomainValidation`'s DNS
# branch: for each domain name it reads
# `validation.props.hostedZones?.[domainName] ?? validation.props.hostedZone`
# and only pushes a `{domainName, hostedZoneId}` entry `if (hostedZone)`.
# With neither `hostedZone` nor `hostedZones` supplied, that condition is
# false for every domain, so the accumulator stays empty and the function
# returns `undefined` -- `DomainValidationOptions` is entirely ABSENT from
# the synthesized template, not merely missing a `HostedZoneId` on one
# entry. `cdk synth --no-lookups` still succeeds (no throw): plan-green
# through tier 0 (ValidationMethod is still "DNS", zone/domain/SAN are all
# still correct). Verified directly: real `cdk synth --no-lookups` +
# `cfn-guard` against this exact fixture reports
# `MissingProperty = DomainValidationOptions` on both
# `validation_option_covers_apex` and `validation_option_covers_www` --
# tier0_pass=1, tier1_status=FAIL, reward 0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as route53 from "aws-cdk-lib/aws-route53";
import * as acm from "aws-cdk-lib/aws-certificatemanager";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // The zone IS created ... but never passed into the certificate's own
    // validation config below.
    new route53.PublicHostedZone(this, "StorefrontZone", {
      zoneName: "storefront.example.com",
    });

    // THE MISTAKE: fromDns() with no hosted-zone argument. DNS validation
    // method is correctly chosen, but nothing tells ACM/CloudFormation
    // which hosted zone to write the challenge records into.
    new acm.Certificate(this, "StorefrontCertificate", {
      domainName: "storefront.example.com",
      subjectAlternativeNames: ["www.storefront.example.com"],
      validation: acm.CertificateValidation.fromDns(),
    });
  }
}
TS

bash tests/static_tiers.sh
