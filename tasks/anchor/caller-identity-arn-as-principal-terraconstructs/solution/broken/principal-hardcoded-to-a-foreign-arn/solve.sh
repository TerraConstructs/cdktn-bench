#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces exactly one mistake from this arm's reference
# solution and nothing else.
#
# The principal is a hand-typed role ARN that nothing in this plan
# creates and nothing ties to the deploying identity.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'SRC'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, iam, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new storage.Bucket(this, "ReleaseArtifacts", {});

    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "PipelineOnly",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ArnPrincipal("arn:aws:iam::210987654321:role/delivery-pipeline")],
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        resources: [bucket.bucketArn, bucket.arnForObjects("*")],
      }),
    );
  }
}
SRC

bash tests/static_tiers.sh
