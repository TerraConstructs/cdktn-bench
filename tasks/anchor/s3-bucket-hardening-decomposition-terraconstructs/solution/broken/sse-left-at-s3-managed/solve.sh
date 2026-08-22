#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces sse-left-at-s3-managed (anti-L2 taxonomy):
# `storage.BucketEncryption.S3_MANAGED` -- a typed, valid, autocompleted
# enum member exactly as easy to pick as `.KMS` -- which silently
# violates "a KMS key that we control". Every other control is wired
# correctly. Verified directly: the synthesized SSEAlgorithm is "AES256",
# not "aws:kms" -- the sse-is-kms tier-0 `eq "aws:kms"` check fails at
# the cheapest tier. Must score reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";
import { s3BucketPublicAccessBlock } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // BUG: S3_MANAGED, not KMS -- "a key we control" is silently
    // violated.
    const bucket = new storage.Bucket(this, "DocumentArchive", {
      bucketName: "cdktn-bench-document-archive",
      versioned: true,
      encryption: storage.BucketEncryption.S3_MANAGED,
      enforceSSL: true,
    });

    new s3BucketPublicAccessBlock.S3BucketPublicAccessBlock(this, "PublicAccessBlock", {
      bucket: bucket.bucketName,
      blockPublicAcls: true,
      blockPublicPolicy: true,
      ignorePublicAcls: true,
      restrictPublicBuckets: true,
    });
  }
}
TS

bash tests/static_tiers.sh
