#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces bpa-partially-set: the hand-wired L1
# S3BucketPublicAccessBlock only sets `blockPublicAcls`/
# `blockPublicPolicy` true; `ignorePublicAcls`/`restrictPublicBuckets` are
# left `false`. Every other control is wired correctly. Verified
# directly: the provider schema resolves the two false flags to a
# present, explicit `false` in `.planned_values` -- the
# bpa-ignore-public-acls / bpa-restrict-public-buckets tier-0 `eq true`
# checks fail (present, wrong value). Must score reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";
import { s3BucketPublicAccessBlock } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new storage.Bucket(this, "DocumentArchive", {
      bucketName: "cdktn-bench-document-archive",
      versioned: true,
      encryption: storage.BucketEncryption.KMS,
      enforceSSL: true,
    });

    // BUG: only 2 of the 4 flags are true.
    new s3BucketPublicAccessBlock.S3BucketPublicAccessBlock(this, "PublicAccessBlock", {
      bucket: bucket.bucketName,
      blockPublicAcls: true,
      blockPublicPolicy: true,
      ignorePublicAcls: false,
      restrictPublicBuckets: false,
    });
  }
}
TS

bash tests/static_tiers.sh
