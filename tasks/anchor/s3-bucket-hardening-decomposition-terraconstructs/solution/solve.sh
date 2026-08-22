#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape verified directly against the pinned terraconstructs 0.2.13
# (installed copy read at authoring time, this arm's own package.json
# pin):
#   - `storage.Bucket` with `versioned`/`encryption`/`encryptionKey`/
#     `enforceSSL` covers 3 of this scenario's 4 controls at the L2 --
#     `lib/aws/storage/bucket.js` synthesizes them exactly like
#     awscdk's `s3.Bucket` (same `enforceSSLStatement()` mechanism,
#     `resources: [this.resource.arn, this.arnForObjects('*')]` --
#     `lib/aws/storage/bucket.js:914-920` -- BOTH the bucket ARN and the
#     object-ARN pattern, automatically).
#   - `encryption: storage.BucketEncryption.KMS` with NO explicit
#     `encryptionKey` auto-creates a same-configuration `encryption.Key`
#     (`lib/aws/storage/bucket.js`'s `parseEncryption()`,
#     `kmsMasterKeyId: encryptionKey.keyArn` -- a real Terraform
#     reference, never a literal), satisfying the
#     sse-kms-references-created-key catch's requirement without any
#     extra code.
#   - `storage.Bucket`'s own `BucketProps` (`lib/aws/storage/bucket.d.ts`)
#     has NO `blockPublicAccess` prop at all -- the only
#     `S3BucketPublicAccessBlock` call anywhere in `bucket.js` (line 726)
#     is inside the `public: true` branch and unconditionally sets all
#     four flags to `false`, the opposite of this scenario's requirement
#     (arms.terraconstructs.reason in specs/s3-bucket-hardening-
#     decomposition.yaml). This is the escape-hatch tax the spec
#     predicts: the 4th control is wired by hand, one L1
#     `@cdktn/provider-aws` `s3BucketPublicAccessBlock.
#     S3BucketPublicAccessBlock` construct pointed at the L2 bucket's own
#     public `bucketName` accessor (`get bucketName() { return
#     this.resource.bucket; }` -- a genuine Terraform reference to the
#     created bucket, not a string echo).
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

    // Escape-hatch tax (this file's own header comment): storage.Bucket
    // has no blockPublicAccess prop on this pinned version, so the fourth
    // control is a separate, hand-wired L1 resource pointed at the L2
    // bucket's own bucketName reference.
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
