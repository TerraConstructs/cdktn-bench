#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Verified directly at authoring time (2026-08-21) against a real
# `npm run build && cdk synth --no-lookups` (aws-cdk-lib 2.263.0's own
# certificate.ts / route53 L2s): synthesizes exactly
# AWS::Route53::HostedZone + AWS::CertificateManager::Certificate (plus
# CDK's own CDKMetadata) -- NO AWS::Route53::RecordSet is ever synthesized;
# CloudFormation/ACM create and clean up the DNS validation records
# themselves once DomainValidationOptions names the hosted zone for each
# validated domain name. `SubjectAlternativeNames` on this arm is exactly
# `["www.storefront.example.com"]` -- unlike the TF-shaped arms, CFN never
# folds `domain_name` into it (see the spec's own
# certificate-san-includes-www-cfn / certificate-san-includes-both-names-tf
# comment for the full cross-arm evidence).
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

    const zone = new route53.PublicHostedZone(this, "StorefrontZone", {
      zoneName: "storefront.example.com",
    });

    // CertificateValidation.fromDns(zone) makes CloudFormation/ACM create
    // and clean up the DNS validation records themselves -- no
    // agent-authored Route53 record resource exists, or is needed, on
    // this arm.
    new acm.Certificate(this, "StorefrontCertificate", {
      domainName: "storefront.example.com",
      subjectAlternativeNames: ["www.storefront.example.com"],
      validation: acm.CertificateValidation.fromDns(zone),
    });
  }
}
TS

bash tests/static_tiers.sh
