#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces exactly one mistake from this arm's reference
# solution and nothing else.
#
# The principal is a hand-typed role ARN that this stack does not create
# and that nothing ties to the deploying identity.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'SRC'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as iam from "aws-cdk-lib/aws-iam";
import * as s3 from "aws-cdk-lib/aws-s3";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const pipelineRole = new iam.Role(this, "PipelineRole", {
      assumedBy: new iam.ServicePrincipal("codebuild.amazonaws.com"),
    });

    const bucket = new s3.Bucket(this, "ReleaseArtifacts");

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
