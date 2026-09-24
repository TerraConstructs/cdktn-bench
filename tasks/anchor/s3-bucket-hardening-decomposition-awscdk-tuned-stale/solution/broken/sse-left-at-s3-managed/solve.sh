#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces sse-left-at-s3-managed (anti-L2 taxonomy): uses
# `s3.BucketEncryption.S3_MANAGED` -- a typed, valid, autocompleted enum
# member exactly as easy to pick as `.KMS` -- which silently violates "a
# KMS key that we control" (S3-managed encryption uses a key S3 itself
# owns). Every other control is wired correctly. Verified directly: the
# synthesized SSEAlgorithm is "AES256", not "aws:kms" -- the sse-is-kms
# tier-0 `eq "aws:kms"` check fails at the cheapest tier. Must score
# reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // BUG: S3_MANAGED, not KMS -- "a key we control" is silently violated.
    new s3.Bucket(this, "DocumentArchive", {
      versioned: true,
      encryption: s3.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });
  }
}
TS

bash tests/static_tiers.sh
