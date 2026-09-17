#!/usr/bin/env bash
# NEGATIVE FIXTURE for catch `repository-not-emptied-on-delete`, predicted
# tier "1" on this arm. `removalPolicy: DESTROY` is set -- so the repository is
# deleted with its stack and every tier-0 assert of this spec passes -- and
# `emptyOnDelete` is omitted, so CloudFormation's delete of a repository that
# still holds images fails and the stack delete fails with it. The tier-1 rule
# `repository_empties_on_delete` is what decides this fixture. Must score
# reward 0.0 at tier 1.
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
      removalPolicy: cdk.RemovalPolicy.DESTROY,
      lifecycleRules: [{ maxImageCount: 10 }],
    });
  }
}
TS

bash tests/static_tiers.sh
