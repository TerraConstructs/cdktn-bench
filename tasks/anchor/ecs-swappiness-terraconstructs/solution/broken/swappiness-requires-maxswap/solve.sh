#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-requires-maxswap catch: sets
# swappiness without maxSwap via terraconstructs' typed compute.ecs
# LinuxParameters -- the natural "forgot maxSwap" mistake. Verified against
# the pinned terraconstructs@0.2.13 package source
# (lib/aws/compute/ecs/linux-parameters.js:55): `this.swappiness =
# props.maxSwap ? props.swappiness : undefined;`, byte-for-byte identical
# to aws-cdk-lib's own silent-drop logic. So this fixture's synthesized
# plan has NO swappiness key at all, caught by the EXISTING tier-0
# swappiness-value-correct structural_assert -- matching the spec's
# terraconstructs_override: "0" for this catch (diverging from hcl_raw's
# tier "1", NOT from awscdk's tier "0").
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const taskDefinition = new compute.ecs.Ec2TaskDefinition(this, "TaskDef");

    taskDefinition.addContainer("App", {
      image: compute.ecs.ContainerImage.fromRegistry("public.ecr.aws/docker/library/nginx:latest"),
      memoryLimitMiB: 256,
      linuxParameters: new compute.ecs.LinuxParameters(this, "LinuxParams", {
        swappiness: 42,
        // maxSwap intentionally omitted -- terraconstructs silently drops
        // swappiness without it, same as aws-cdk-lib.
      }),
    });
  }
}
TS

bash tests/static_tiers.sh
