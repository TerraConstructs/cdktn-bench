#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instances-never-tagged catch on this arm: neither
# accepted instance-reaching mechanism is present at all -- no Tags.of()
# call reaches the ASG (no PropagateAtLaunch=true tags) or the launch
# template's own "instance"-resourceType TagSpecifications. The volume
# half is still correctly present, via a hand-authored L1 escape hatch
# (`addPropertyOverride`) that writes ONLY a "volume"-resourceType
# TagSpecifications entry directly onto the underlying
# AWS::EC2::LaunchTemplate, deliberately bypassing Tags.of() (which would
# also reach the "instance" resourceType and defeat this fixture's own
# point). Every tier-0 fact this scenario declares still passes (ASG
# exists, capacity, launch template exists, both volume-tag values,
# instance type, AMI); reward must be 0.0 via the tier-1 cfn-guard
# policy's instance_tag_costcenter_reaches / instance_tag_environment_reaches
# rules, which find neither mechanism for either required key.
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

    new autoscaling.AutoScalingGroup(this, "WorkerFleet", {
      vpc,
      vpcSubnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      launchTemplate,
      minCapacity: 2,
      maxCapacity: 6,
      // THE MISTAKE: no Tags.of() call reaches the ASG or the launch
      // template's instance resourceType at all -- nothing below tags
      // launched instances via either accepted mechanism.
    });

    // Hand-authored L1 escape hatch: gives the underlying
    // AWS::EC2::LaunchTemplate a volume-only TagSpecifications entry
    // directly, WITHOUT going through Tags.of() (which would also reach
    // the "instance" resourceType and defeat this fixture's own point).
    const cfnLaunchTemplate = launchTemplate.node.defaultChild as ec2.CfnLaunchTemplate;
    cfnLaunchTemplate.addPropertyOverride("LaunchTemplateData.TagSpecifications", [
      {
        ResourceType: "volume",
        Tags: [
          { Key: "CostCenter", Value: "platform-42" },
          { Key: "Environment", Value: "prod" },
        ],
      },
    ]);
  }
}
TS

bash tests/static_tiers.sh
