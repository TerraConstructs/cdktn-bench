#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same tests/static_tiers.sh a real
# trial's verifier runs. Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# The principal is the ISSUER ROLE of the deploying session, reached
# through the `@cdktn/provider-aws` L1 data sources: the L2 has no
# caller-identity construct, and the session ARN itself is not a policy
# principal.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'SRC'
import { DataAwsCallerIdentity } from "@cdktn/provider-aws/lib/data-aws-caller-identity";
import { DataAwsIamSessionContext } from "@cdktn/provider-aws/lib/data-aws-iam-session-context";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, iam, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const caller = new DataAwsCallerIdentity(this, "Deployer", {});
    // The deploying credentials are an STS session, not an identity IAM can
    // name in a policy; this maps that session back to the role that issued it.
    const session = new DataAwsIamSessionContext(this, "DeployerSession", {
      arn: caller.arn,
    });

    const bucket = new storage.Bucket(this, "ReleaseArtifacts", {});

    bucket.addToResourcePolicy(
      new iam.PolicyStatement({
        sid: "PipelineOnly",
        effect: iam.Effect.ALLOW,
        principals: [new iam.ArnPrincipal(session.issuerArn)],
        actions: ["s3:GetObject", "s3:PutObject", "s3:DeleteObject", "s3:ListBucket"],
        resources: [bucket.bucketArn, bucket.arnForObjects("*")],
      }),
    );
  }
}
SRC

bash tests/static_tiers.sh
