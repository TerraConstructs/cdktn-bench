#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# BOTH properties are required and neither is optional here: aws-cdk-lib
# 2.263.0 throws at synth for `emptyOnDelete` without `removalPolicy: DESTROY`
# ("Cannot use 'emptyOnDelete' property on a repository without setting removal
# policy to 'DESTROY'"), and the default policy is Retain -- under which the
# destroy succeeds while leaving the repository in the account.
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
      lifecycleRules: [{ maxImageCount: 10 }],
    });
  }
}
TS

bash tests/static_tiers.sh
