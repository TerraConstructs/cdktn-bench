#!/usr/bin/env bash
# NEGATIVE FIXTURE for catch `lifecycle-policy-keeps-wrong-count` -- the
# reference solution keeping 100 images instead of 10. The typed prop accepts
# any positive count, so the mistake reaches the plan intact and only the
# decoded-path tier-0 assert `lifecycle-policy-keeps-ten` sees it. Must score
# reward 0.0 at tier 0.
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
      lifecycleRules: [{ maxImageCount: 100 }],
    });
  }
}
TS

bash tests/static_tiers.sh
