#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts using terraconstructs' typed
# compute.ecs L2 (Ec2TaskDefinition / LinuxParameters -- confirmed
# byte-for-byte port of aws-cdk-lib's own construct at spec-authoring time,
# see specs/ecs-swappiness.yaml's arms.terraconstructs.reason), then runs
# the same tests/static_tiers.sh a real trial's verifier runs. Regenerating
# this scenario will NOT overwrite this file (destructive-safe rule).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";
import { Size } from "terraconstructs";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const taskDefinition = new compute.ecs.Ec2TaskDefinition(this, "TaskDef");

    taskDefinition.addContainer("App", {
      image: compute.ecs.ContainerImage.fromRegistry("public.ecr.aws/docker/library/nginx:latest"),
      memoryLimitMiB: 256,
      linuxParameters: new compute.ecs.LinuxParameters(this, "LinuxParams", {
        maxSwap: Size.mebibytes(256),
        swappiness: 42,
      }),
    });
  }
}
TS

bash tests/static_tiers.sh
