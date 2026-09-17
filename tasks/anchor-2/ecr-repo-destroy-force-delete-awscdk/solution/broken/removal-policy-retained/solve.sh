#!/usr/bin/env bash
# EXTRA NEGATIVE FIXTURE (named after no catch, required to score 0.0 the same
# way): the omission in its DEFAULT form -- neither property set, so CDK's
# default removal policy Retain stands. This is the shape that makes a
# destroy-based verdict unusable on this arm: `cdk destroy --force` deletes the
# stack, exits 0, and LEAVES THE REPOSITORY in the account, so a teardown tier
# reading that run would record `clean`. The tier-0 assert
# `deletion-policy-is-delete` is what catches it, and this fixture is why that
# assert exists. Must score reward 0.0 at tier 0.
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
      lifecycleRules: [{ maxImageCount: 10 }],
    });
  }
}
TS

bash tests/static_tiers.sh
