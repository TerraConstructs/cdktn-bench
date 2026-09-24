#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape verified directly against the pinned aws-cdk-lib 2.263.0 (this
# arm's own package.json pin, installed copy read at authoring time):
#   - `versioned: true` -> VersioningConfiguration.Status = "Enabled".
#   - `encryption: BucketEncryption.KMS` + an explicit `encryptionKey`
#     (a same-stack `kms.Key`) -> BucketEncryption.SSEAlgorithm = "aws:kms",
#     KMSMasterKeyID = Fn::GetAtt on that key (never a literal/imported ARN
#     -- this scenario's own kms-key-not-referenced catch).
#   - `blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL` -> all four
#     PublicAccessBlockConfiguration flags true.
#   - `enforceSSL: true` -> aws-s3/lib/bucket.ts's own enforceSSL path
#     derives a Deny statement whose Resource array is
#     `[this.bucketArn, this.arnForObjects('*')]` (bucket.ts:2689-2704) --
#     BOTH the bucket ARN and the object-ARN pattern, automatically. This
#     is the exact mechanism this scenario's headline catch
#     (tls-policy-misses-object-arn, a hand-written Deny naming only the
#     bucket ARN) is structurally unreachable through, on this arm.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as kms from "aws-cdk-lib/aws-kms";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const key = new kms.Key(this, "DocumentArchiveKey", {
      enableKeyRotation: true,
    });

    new s3.Bucket(this, "DocumentArchive", {
      versioned: true,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: key,
      enforceSSL: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });
  }
}
TS

bash tests/static_tiers.sh
