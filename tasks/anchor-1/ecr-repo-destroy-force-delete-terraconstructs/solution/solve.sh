#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts using terraconstructs' typed
# storage.Repository, then runs the same tests/static_tiers.sh a real trial's
# verifier runs. Regenerating this scenario will NOT overwrite this file.
#
# `emptyOnDelete: true` is the typed prop this arm's construct maps straight
# onto the provider's `forceDelete` (terraconstructs 0.2.13,
# lib/aws/storage/ecr-repository.js:391). Unlike aws-cdk-lib it needs no
# removal-policy companion: nothing on this arm retains a resource by default.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new storage.Repository(this, "ServiceImageRegistry", {
      repositoryName: "service-image-registry",
      imageScanOnPush: true,
      emptyOnDelete: true,
      lifecycleRules: [{ maxImageCount: 10 }],
    });
  }
}
TS

bash tests/static_tiers.sh
