#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# CloudFormation has no data source for the deploying identity, so the
# pipeline role is declared here and the bucket policy names it by
# `Fn::GetAtt` -- the one principal shape this arm can tie to the stack.
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
        principals: [new iam.ArnPrincipal(pipelineRole.roleArn)],
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        resources: [bucket.bucketArn, bucket.arnForObjects("*")],
      }),
    );
  }
}
SRC

bash tests/static_tiers.sh
