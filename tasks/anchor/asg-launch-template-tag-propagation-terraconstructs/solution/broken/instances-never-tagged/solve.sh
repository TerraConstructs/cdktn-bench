#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instances-never-tagged catch on this arm: an
# explicit LaunchTemplate (bypassing this library's own automatic internal
# LaunchTemplate creation, so the exact tag_specifications shape is fully
# controlled) has ONLY a "volume"-resourceType tag_specifications entry,
# written directly via the L1 `putTagSpecifications` escape hatch --
# deliberately bypassing Tags.of() (which would also reach the "instance"
# resourceType) and never touching the ASG's own `tag` blocks at all.
# Every tier-0 fact this scenario declares still passes (ASG exists,
# capacity, launch template exists, both volume-tag values, instance type,
# AMI); reward must be 0.0 via the tier-1 Rego policy's
# instance_tag_reaches OR-check, which finds neither mechanism for either
# required key.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute } from "terraconstructs/lib/aws";

// See this scenario's own reference solve.sh header comment
// ("NoOpUserData") for why this exists -- unrelated to this fixture's own
// mistake, just required to synth+plan offline at all.
class NoOpUserData extends compute.UserData {
  readonly content = "";
  readonly contentType = undefined;
  readonly filename = undefined;
  addCommands(): void {}
  addOnExitCommands(): void {}
  render(): string {
    return "";
  }
  addS3DownloadCommand(): string {
    return "";
  }
  addExecuteFileCommand(): void {}
}

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

    const launchTemplate = new compute.LaunchTemplate(this, "WorkerLaunchTemplate", {
      instanceType: new compute.InstanceType("t3.small"),
      machineImage: compute.MachineImage.genericLinux(
        { "us-east-1": "ami-0c55b159cbfafe1f0" },
        { userData: new NoOpUserData() },
      ),
    });

    // THE MISTAKE: L1 escape hatch, volume-only -- no "instance"
    // resourceType entry, and Tags.of()/the ASG's own tag blocks are never
    // used at all, so neither accepted instance-reaching mechanism exists.
    launchTemplate.resource.putTagSpecifications([
      {
        resourceType: "volume",
        tags: { CostCenter: "platform-42", Environment: "prod" },
      },
    ]);

    new compute.autoscaling.AutoScalingGroup(this, "WorkerFleet", {
      vpc,
      vpcSubnets: { subnetType: compute.SubnetType.PRIVATE_ISOLATED },
      launchTemplate,
      minCapacity: 2,
      maxCapacity: 6,
    });
  }
}
TS

bash tests/static_tiers.sh
