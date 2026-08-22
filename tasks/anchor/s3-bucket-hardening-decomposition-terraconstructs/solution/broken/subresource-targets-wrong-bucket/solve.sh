#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces subresource-targets-wrong-bucket: the hand-wired
# L1 S3BucketPublicAccessBlock's `bucket` argument is a hardcoded literal
# bucket name, never `bucket.bucketName` (a reference to the L2 bucket
# this configuration creates). The subresource still exists (every
# tier-0 existence check for it still passes -- its own literal flags are
# all `true`) but it silently controls a bucket this configuration does
# not create, leaving the real `document-archive` bucket unprotected by
# this specific control. Every other control is wired correctly.
# Verified directly: `.configuration...aws_s3_bucket_public_access_block.
# expressions.bucket` has only a `.constant_value`, no `.references`
# entry matching `^aws_s3_bucket\.` -- every-subresource-targets-this-
# bucket-tf denies it. Must score reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";
import { s3BucketPublicAccessBlock } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new storage.Bucket(this, "DocumentArchive", {
      bucketName: "cdktn-bench-document-archive",
      versioned: true,
      encryption: storage.BucketEncryption.KMS,
      enforceSSL: true,
    });

    // BUG: hardcoded literal bucket name -- never bucket.bucketName.
    // Copy-pasted from another example and never repointed.
    new s3BucketPublicAccessBlock.S3BucketPublicAccessBlock(this, "PublicAccessBlock", {
      bucket: "some-other-bucket-entirely",
      blockPublicAcls: true,
      blockPublicPolicy: true,
      ignorePublicAcls: true,
      restrictPublicBuckets: true,
    });
  }
}
TS

bash tests/static_tiers.sh
