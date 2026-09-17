#!/usr/bin/env bash
# NEGATIVE FIXTURE for catch `auto-delete-images-custom-resource` (anti-L2).
# Reaches for aws-cdk-lib's deprecated `autoDeleteImages` instead of the native
# property: the teardown then succeeds, by deploying a Lambda, its role and its
# policy and emptying the repository from a `Custom::ECRAutoDeleteImages` delete
# handler. Every tier-0 assert passes (the prop requires `removalPolicy:
# DESTROY` too), and the tier-1 bundle fails on both of its rules -- the missing
# EmptyOnDelete and the custom resource's presence. Must score reward 0.0 at
# tier 1.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as ecr from "aws-cdk-lib/aws-ecr";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    new ecr.Repository(this, "ServiceImageRegistry", {
      repositoryName: "service-image-registry",
      imageScanOnPush: true,
      autoDeleteImages: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      lifecycleRules: [{ maxImageCount: 10 }],
    });
  }
}
TS

bash tests/static_tiers.sh
