#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the email-validation-instead catch: `validation` is
# explicitly set to `CertificateValidation.fromEmail()`. (This arm's own
# SILENT reachability path -- simply omitting `validation` entirely also
# reaches EMAIL here, verified directly against a real `cdk synth`; see
# the spec's own catch description and header comment for the full
# awscdk-vs-terraconstructs divergence. Written explicitly here for
# fixture clarity/stability rather than relying on the implicit default.)
# Plan-green in full (zone, domain, SAN, DomainValidationOptions are all
# still correct -- only ValidationMethod is wrong). Reward must be 0.0
# from tier-0's own validation-method-is-dns check alone.
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

    new route53.PublicHostedZone(this, "StorefrontZone", {
      zoneName: "storefront.example.com",
    });

    // THE MISTAKE: EMAIL validation, not DNS.
    new acm.Certificate(this, "StorefrontCertificate", {
      domainName: "storefront.example.com",
      subjectAlternativeNames: ["www.storefront.example.com"],
      validation: acm.CertificateValidation.fromEmail(),
    });
  }
}
TS

bash tests/static_tiers.sh
