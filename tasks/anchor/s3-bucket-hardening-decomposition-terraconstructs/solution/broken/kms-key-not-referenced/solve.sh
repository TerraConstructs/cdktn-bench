#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces kms-key-not-referenced: SSE is genuinely
# `aws:kms` (passes sse-is-kms), but `encryptionKey` is
# `encryption.Key.fromKeyArn(...)` -- an IMPORTED key, never one this
# configuration actually creates. Every other control is wired correctly.
# Verified directly: this synthesizes ZERO aws_kms_key resources, and
# `kms_master_key_id`'s expression holds only a `.constant_value`
# (the literal ARN string), never a `.references` entry matching
# `^aws_kms_key\.` -- sse-kms-references-created-key-tf denies it. Must
# score reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage, encryption } from "terraconstructs/lib/aws";
import { s3BucketPublicAccessBlock } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // BUG: imported key literal, not a key this configuration creates.
    const key = encryption.Key.fromKeyArn(
      this,
      "ImportedKey",
      "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111",
    );

    const bucket = new storage.Bucket(this, "DocumentArchive", {
      bucketName: "cdktn-bench-document-archive",
      versioned: true,
      encryption: storage.BucketEncryption.KMS,
      encryptionKey: key,
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
