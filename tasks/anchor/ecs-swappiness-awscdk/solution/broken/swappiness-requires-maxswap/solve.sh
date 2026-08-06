#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-requires-maxswap catch: sets
# swappiness without maxSwap -- the natural "forgot maxSwap" mistake.
# aws-cdk-lib's own LinuxParameters construct (aws-ecs/lib/
# linux-parameters.ts:116) silently drops `swappiness` to `undefined`
# whenever `maxSwap` is unset, so this fixture's synthesized template has
# NO Swappiness property at all -- caught by the EXISTING tier-0
# swappiness-value-correct structural_assert (predicted_tier_caught.awscdk:
# "0" in the spec), not by the tier-1 policy.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as ecs from "aws-cdk-lib/aws-ecs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const taskDefinition = new ecs.Ec2TaskDefinition(this, "TaskDef");

    taskDefinition.addContainer("App", {
      image: ecs.ContainerImage.fromRegistry("public.ecr.aws/docker/library/nginx:latest"),
      memoryLimitMiB: 256,
      linuxParameters: new ecs.LinuxParameters(this, "LinuxParams", {
        swappiness: 42,
        // maxSwap intentionally omitted -- CDK silently drops swappiness
        // without it.
      }),
    });
  }
}
TS

bash tests/static_tiers.sh
