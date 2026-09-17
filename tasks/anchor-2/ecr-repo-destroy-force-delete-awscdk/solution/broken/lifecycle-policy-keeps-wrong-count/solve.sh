#!/usr/bin/env bash
# NEGATIVE FIXTURE for catch `lifecycle-policy-keeps-wrong-count` -- the
# reference solution keeping 100 images instead of 10. The typed prop accepts
# any positive count, so the mistake reaches the template intact and only the
# decoded-path tier-0 assert `lifecycle-policy-keeps-ten` sees it. Must score
# reward 0.0 at tier 0.
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
      emptyOnDelete: true,
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      lifecycleRules: [{ maxImageCount: 100 }],
    });
  }
}
TS

bash tests/static_tiers.sh
