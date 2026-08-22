#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces bpa-partially-set: `blockPublicAccess` is
# constructed with only `blockPublicAcls`/`blockPublicPolicy`, leaving
# `ignorePublicAcls`/`restrictPublicBuckets` unset (their BlockPublicAccess
# constructor default is `false`). Every other control is wired correctly.
# Verified directly: the two omitted flags never appear in the synthesized
# PublicAccessBlockConfiguration at all (0 resolved nodes) -- the
# bpa-ignore-public-acls / bpa-restrict-public-buckets tier-0 `eq true`
# checks fail. Must score reward=0.0.
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
      // BUG: only 2 of the 4 flags are set -- ignorePublicAcls and
      // restrictPublicBuckets never appear at all.
      blockPublicAccess: new s3.BlockPublicAccess({
        blockPublicAcls: true,
        blockPublicPolicy: true,
      }),
    });
  }
}
TS

bash tests/static_tiers.sh
