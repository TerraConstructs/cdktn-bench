#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). THE PLAUSIBLE-WRONG SOLUTION (this scenario's headline catch,
# blueprint §1(c)): `enforceSSL` deliberately NOT used; a hand-written
# Deny-on-non-TLS statement is added via `addToResourcePolicy` naming only
# `bucket.bucketArn`, never `bucket.arnForObjects('*')`. Every other
# control is wired identically to the reference solution. Verified
# directly: same G2 contagion as the correct fixture (the bucket policy's
# encoded value is opaque), so tier-1 grading is the graph-edge check --
# this fixture's `data.aws_iam_policy_document.*`'s own
# `.expressions.statement[*].resources.references` resolves to exactly
# ONE `.arn`-suffixed reference to the bucket, not two --
# oracles/rego/s3-bucket-hardening-decomposition/policy.rego's
# arn_ref_count() < 2 rule denies it. Must score reward=0.0.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage, iam } from "terraconstructs/lib/aws";
import { s3BucketPublicAccessBlock } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new storage.Bucket(this, "DocumentArchive", {
      bucketName: "cdktn-bench-document-archive",
      versioned: true,
      encryption: storage.BucketEncryption.KMS,
      // enforceSSL deliberately NOT used -- a hand-written Deny statement
      // below reproduces the "reads correct, protects nothing" mistake.
    });

    new s3BucketPublicAccessBlock.S3BucketPublicAccessBlock(this, "PublicAccessBlock", {
      bucket: bucket.bucketName,
      blockPublicAcls: true,
      blockPublicPolicy: true,
      ignorePublicAcls: true,
      restrictPublicBuckets: true,
    });

    // BUG: Resource names only the bucket ARN itself -- the object-ARN
    // pattern is never added, so every object-level request over plain
    // HTTP remains allowed.
    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        effect: iam.Effect.DENY,
        actions: ["s3:*"],
        principals: [new iam.AnyPrincipal()],
        resources: [bucket.bucketArn],
        condition: [
          {
            test: "Bool",
            variable: "aws:SecureTransport",
            values: ["false"],
          },
        ],
      }),
    );
  }
}
TS

bash tests/static_tiers.sh
