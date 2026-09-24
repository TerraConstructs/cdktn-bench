#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces the subresource-omitted catch: `versioned` is never
# set (its implied default is `false`), while every other control
# (encryption, blockPublicAccess, enforceSSL) is still correctly wired.
# Verified directly: with `versioned` omitted, `s3.Bucket` synthesizes NO
# VersioningConfiguration key at all -- `versioning-enabled`'s
# `eq "Enabled"` tier-0 check resolves to 0 nodes and fails outright.
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

    const key = new kms.Key(this, "DocumentArchiveKey", {
      enableKeyRotation: true,
    });

    // BUG: `versioned` is never set (subresource-omitted).
    new s3.Bucket(this, "DocumentArchive", {
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: key,
      enforceSSL: true,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
    });
  }
}
TS

bash tests/static_tiers.sh
