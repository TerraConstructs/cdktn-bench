#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces kms-key-not-referenced: SSE is genuinely
# `aws:kms` (passes sse-is-kms), but the key is
# `kms.Key.fromKeyArn(...)` -- an IMPORTED key, never one this
# configuration actually creates. This nominally satisfies "a KMS key
# that we control" in prose but is not verifiably so from a static
# artifact. Verified directly: this synthesizes ZERO AWS::KMS::Key
# resources and a plain string KMSMasterKeyID (no Fn::GetAtt) --
# sse-kms-references-created-key-cfn's `exists` check on the
# Fn::GetAtt-shaped KMSMasterKeyID fails (a bare string has no such key).
# Must score reward=0.0.
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

    // BUG: imported key literal, not a key this configuration creates.
    const key = kms.Key.fromKeyArn(
      this,
      "ImportedKey",
      "arn:aws:kms:us-east-1:123456789012:key/11111111-1111-1111-1111-111111111111",
    );

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
