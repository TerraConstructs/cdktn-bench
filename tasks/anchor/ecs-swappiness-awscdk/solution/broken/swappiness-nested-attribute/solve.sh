#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-nested-attribute catch: Swappiness is
# injected as a SIBLING of the container's own top-level fields (Name,
# Image, Memory) instead of nested inside LinuxParameters. The typed L2
# LinuxParameters API has no way to express this mistake directly (that IS
# the catch -- see the spec's own description), so this fixture reaches it
# via the same CfnResource.addOverride() escape hatch a real agent would
# have to use to reproduce it on this arm. LinuxParameters itself is
# correctly populated with maxSwap ONLY (no swappiness) so this fixture
# isolates the nested-attribute catch from the maxSwap-dependency catch --
# it must fail via swappiness-value-correct (tier 0), not via the tier-1
# maxswap rule.
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
        maxSwap: cdk.Size.mebibytes(256),
      }),
    });

    // Mis-nested on purpose: Swappiness as a sibling of Name/Image/Memory,
    // not inside LinuxParameters.
    const cfnTaskDef = taskDefinition.node.defaultChild as ecs.CfnTaskDefinition;
    cfnTaskDef.addOverride("Properties.ContainerDefinitions.0.Swappiness", 42);
  }
}
TS

bash tests/static_tiers.sh
