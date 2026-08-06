#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED, extra non-catch-named
# fixture (mirroring toy-ssm-parameter's own
# policy-scoped-to-parameter-alt-shape convention: gates/oracle_falsifiability.py
# auto-discovers any solution/broken/<dir>/ not matching a declared catch
# name and requires reward 0.0 from it too, same as a named catch).
#
# WHY THIS FIXTURE EXISTS: the swappiness-requires-maxswap/solve.sh fixture
# (the NATURAL "forgot maxSwap" mistake, via the typed LinuxParameters prop)
# is caught at tier 0 -- CDK's own silent-drop logic means Swappiness never
# even reaches the synthesized template, so the tier-1 cfn-guard rule
# (oracles/cfn-guard/ecs-swappiness/policy.guard's
# swappiness_requires_maxswap) is never actually exercised by that fixture.
# Without a SEPARATE fixture that forces Swappiness into the template
# without MaxSwap (the only way this shape can occur on awscdk, per the
# catch's own description), that cfn-guard rule would ship with ZERO
# coverage from the checked-in falsifiability suite -- only from an
# ad hoc hand-crafted template.json at spec-authoring time, not from
# anything `make falsifiability`/`make grading-proof` actually re-runs.
# This fixture closes that gap: it bypasses the typed LinuxParameters
# construct entirely via a raw property override, landing
# `LinuxParameters: { Swappiness: 42 }` (no MaxSwap key at all) directly in
# the synthesized template -- tier 0 (swappiness-value-correct) PASSES
# this (Swappiness IS present, correctly nested, equal to 42); only the
# tier-1 cfn-guard rule catches it.
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
      // No linuxParameters here -- the typed construct's own silent-drop
      // logic would erase Swappiness the moment maxSwap is unset, which is
      // exactly the shape the OTHER swappiness-requires-maxswap fixture
      // already covers at tier 0. This fixture instead forces the raw
      // property in directly below, bypassing that logic entirely.
    });

    // Force Swappiness into the template with NO MaxSwap alongside it --
    // the shape the typed API can never itself produce.
    const cfnTaskDef = taskDefinition.node.defaultChild as ecs.CfnTaskDefinition;
    cfnTaskDef.addOverride("Properties.ContainerDefinitions.0.LinuxParameters", {
      Swappiness: 42,
    });
  }
}
TS

bash tests/static_tiers.sh
