#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces subresource-omitted: `versioned` is never set on
# `storage.Bucket` (its implied default is `false`). Every other control
# is wired correctly. Verified directly: with `versioned` omitted,
# `storage.Bucket` synthesizes NO aws_s3_bucket_versioning resource at
# all -- versioning-enabled's `eq "Enabled"` tier-0 check resolves to 0
# nodes and fails outright. Must score reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";
import { s3BucketPublicAccessBlock } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // BUG: `versioned` is never set (subresource-omitted).
    const bucket = new storage.Bucket(this, "DocumentArchive", {
      bucketName: "cdktn-bench-document-archive",
      encryption: storage.BucketEncryption.KMS,
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
