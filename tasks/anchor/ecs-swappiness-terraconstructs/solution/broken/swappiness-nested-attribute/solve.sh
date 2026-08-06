#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the swappiness-nested-attribute catch: `swappiness` is
# placed as a sibling of the container's own top-level fields instead of
# nested inside `linuxParameters`. terraconstructs' typed compute.ecs
# LinuxParameters construct has no way to express this mistake directly
# (same as awscdk -- that IS the catch), so this fixture bypasses the L2
# entirely and authors the underlying `aws_ecs_task_definition` resource
# via its L1 binding (@cdktn/provider-aws), producing the identical
# mis-nested JSON shape hcl_raw's own negative fixture does (both arms are
# graded against the same `terraform show -json` plan shape). maxSwap is
# correctly nested (no swappiness) so this fixture isolates the
# nested-attribute catch from the maxSwap-dependency catch -- it must fail
# via swappiness-value-correct (tier 0), not via the tier-1 rego rule.
#
# `provider: this.provider` is required on this L1 construct (unlike the
# typed L2, which wires it internally) -- verified: omitting it fails synth
# outright ("Found resources without a matching provider construct"),
# before any plan/oracle check ever runs, same as toy-ssm-parameter's own
# L1 usage.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { ecsTaskDefinition } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    new ecsTaskDefinition.EcsTaskDefinition(this, "TaskDef", {
      provider: this.provider,
      family: "ecs-swappiness",
      requiresCompatibilities: ["EC2"],
      networkMode: "bridge",
      containerDefinitions: JSON.stringify([
        {
          name: "app",
          image: "public.ecr.aws/docker/library/nginx:latest",
          memory: 256,
          essential: true,
          swappiness: 42,
          linuxParameters: {
            maxSwap: 256,
          },
        },
      ]),
    });
  }
}
TS

bash tests/static_tiers.sh
