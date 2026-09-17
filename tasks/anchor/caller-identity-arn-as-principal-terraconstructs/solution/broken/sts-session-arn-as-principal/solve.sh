#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Reproduces exactly one mistake from this arm's reference
# solution and nothing else.
#
# The principal is the deploying session's own ARN, straight off the
# caller-identity data source -- an `arn:aws:sts::…:assumed-role/…/…`
# session identity, which is not a policy principal.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'SRC'
import { DataAwsCallerIdentity } from "@cdktn/provider-aws/lib/data-aws-caller-identity";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, iam, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const caller = new DataAwsCallerIdentity(this, "Deployer", {});
    const bucket = new storage.Bucket(this, "ReleaseArtifacts", {});

    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "PipelineOnly",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ArnPrincipal(caller.arn)],
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        resources: [bucket.bucketArn, bucket.arnForObjects("*")],
      }),
    );
  }
}
SRC

bash tests/static_tiers.sh
