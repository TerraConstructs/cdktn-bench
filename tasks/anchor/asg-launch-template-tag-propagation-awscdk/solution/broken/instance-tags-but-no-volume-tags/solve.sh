#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instance-tags-but-no-volume-tags catch on this
# arm: tags the ASG (reaches instances via PropagateAtLaunch) but never
# tags the launch template at all, so its TagSpecifications carries
# neither an "instance" nor a "volume" resourceType entry -- every
# attached EBS volume launches untagged. Reward must be 0.0 via
# volume-tag-costcenter-present / volume-tag-environment-present (tier 0):
# both resolve to zero nodes.
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

    const fleet = new autoscaling.AutoScalingGroup(this, "WorkerFleet", {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      launchTemplate,
      minCapacity: 2,
      maxCapacity: 6,
    });

    // THE MISTAKE: only the ASG is tagged. launchTemplate is never
    // touched, so its TagSpecifications never gets an "instance" OR
    // "volume" entry -- every attached EBS volume stays untagged.
    cdk.Tags.of(fleet).add("CostCenter", "platform-42");
    cdk.Tags.of(fleet).add("Environment", "prod");
  }
}
TS

bash tests/static_tiers.sh
