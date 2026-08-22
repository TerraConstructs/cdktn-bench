#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the tags-only-on-the-asg-resource catch on this arm:
# an inline `tags: {...}` object literal passed to AutoScalingGroupProps,
# which declares no such field (verified directly against the pinned
# terraconstructs 0.2.13 typings, same as aws-cdk-lib -- see
# auto-scaling-group.d.ts). Reward must be 0.0 from this arm's own
# unconditionally-injected `npx tsc -p tsconfig.json` toolchain step
# (TS2353, excess-property check on a fresh object literal), before
# `cdktn synth` ever runs. No structural_assert or tier-1 policy is ever
# reached; cdktf.out is never even produced.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const vpc = new compute.Vpc(this, "WorkerVpc", {
      availabilityZones: ["us-east-1a", "us-east-1b"],
      natGateways: 0,
      subnetConfiguration: [
        {
          name: "Private",
          subnetType: compute.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    // THE MISTAKE: AutoScalingGroupProps has no `tags` field at all --
    // rejected by tsc's excess-property check on this fresh object
    // literal, before synth ever runs.
    new compute.autoscaling.AutoScalingGroup(this, "WorkerFleet", {
      vpc,
      vpcSubnets: { subnetType: compute.SubnetType.PRIVATE_ISOLATED },
      instanceType: new compute.InstanceType("t3.small"),
      machineImage: compute.MachineImage.genericLinux({
        "us-east-1": "ami-0c55b159cbfafe1f0",
      }),
      minCapacity: 2,
      maxCapacity: 6,
      tags: {
        CostCenter: "platform-42",
        Environment: "prod",
      },
    });
  }
}
TS

bash tests/static_tiers.sh
