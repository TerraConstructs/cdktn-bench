#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the tags-only-on-the-asg-resource catch on this arm:
# an inline `tags: {...}` object literal passed to
# AutoScalingGroupProps, which declares no such field. Reward must be 0.0
# from the toolchain step itself (`npm run build` -> tsc) -- verified
# directly at authoring time against the pinned aws-cdk-lib 2.263.0 typings
# (CommonAutoScalingGroupProps/AutoScalingGroupProps have no `tags` member)
# and TypeScript's excess-property check on a fresh object literal
# (TS2353 "Object literal may only specify known properties"). No
# structural_assert or tier-1 policy is ever reached; cdk.out is never
# even produced.
set -euo pipefail

cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import * as autoscaling from "aws-cdk-lib/aws-autoscaling";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, "WorkerVpc", {
      maxAzs: 2,
      natGateways: 0,
      subnetConfiguration: [
        {
          name: "Private",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    const launchTemplate = new ec2.LaunchTemplate(this, "WorkerLaunchTemplate", {
      instanceType: new ec2.InstanceType("t3.small"),
      machineImage: ec2.MachineImage.genericLinux({
        "us-east-1": "ami-0c55b159cbfafe1f0",
      }),
    });

    // THE MISTAKE: AutoScalingGroupProps has no `tags` field at all --
    // rejected by tsc's excess-property check on this fresh object
    // literal, before synth ever runs.
    new autoscaling.AutoScalingGroup(this, "WorkerFleet", {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      launchTemplate,
      minCapacity: 2,
      maxCapacity: 6,
      // THE MISTAKE, left uncommented on purpose: `tags` is not a member
      // of AutoScalingGroupProps, so tsc must reject this literal --
      // suppressing it (e.g. with @ts-expect-error) would defeat the
      // whole point of this fixture, which is to reach reward 0.0 via a
      // real compile failure.
      tags: {
        CostCenter: "platform-42",
        Environment: "prod",
      },
    });
  }
}
TS

bash tests/static_tiers.sh
