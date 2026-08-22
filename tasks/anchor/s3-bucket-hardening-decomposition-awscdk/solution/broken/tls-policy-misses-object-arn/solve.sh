#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). THE PLAUSIBLE-WRONG SOLUTION (this scenario's headline catch,
# blueprint §1(c)): a hand-written Deny-on-non-TLS statement naming only
# the bucket ARN (`bucket.bucketArn`), never the object-ARN pattern
# (`bucket.arnForObjects('*')`) `enforceSSL: true` would have derived
# automatically. This fixture reads correctly, has every other control
# wired identically to the reference solution (versioned, KMS encryption,
# all four public-access-block flags), and passes every existence check --
# but protects nothing: every s3:GetObject over plain HTTP against an
# object inside the bucket is still allowed, because IAM policy evaluation
# for an S3 object-level action is scoped by the object ARN, not the
# bucket ARN. Verified directly: the Resource array in the synthesized
# BucketPolicy has exactly 1 element (an Fn::GetAtt node for the bucket
# ARN) -- the tls-deny-covers-objects-too-cfn tier-1 assert (Resource
# array `exists` with >= 2 elements is the intent, and cfn-guard's
# `count(Resource.*) >= 2` rule fails on 1) rejects it. Must score
# reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as kms from "aws-cdk-lib/aws-kms";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const key = new kms.Key(this, "DocumentArchiveKey", {
      enableKeyRotation: true,
    });

    const bucket = new s3.Bucket(this, "DocumentArchive", {
      versioned: true,
      encryption: s3.BucketEncryption.KMS,
      encryptionKey: key,
      blockPublicAccess: s3.BlockPublicAccess.BLOCK_ALL,
      // enforceSSL deliberately NOT used -- a hand-written Deny statement
      // below reproduces the "reads correct, protects nothing" mistake.
    });

    // BUG: Resource names only the bucket ARN itself, never
    // bucket.arnForObjects('*') -- every object-level request over plain
    // HTTP remains allowed.
    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.DENY,
        actions: ["s3:*"],
        principals: [new iam.AnyPrincipal()],
        resources: [bucket.bucketArn],
        conditions: {
          Bool: { "aws:SecureTransport": "false" },
        },
      }),
    );
  }
}
TS

bash tests/static_tiers.sh
