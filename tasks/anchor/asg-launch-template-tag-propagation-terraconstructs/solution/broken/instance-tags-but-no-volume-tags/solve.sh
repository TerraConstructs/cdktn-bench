#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the instance-tags-but-no-volume-tags catch on this
# arm. This library's AutoScalingGroup always builds an internal
# LaunchTemplate child construct (see this scenario's own solve.sh header
# comment), and a stack-wide/ASG-scoped Tags.of() call would normally
# reach that child's tag_specifications for BOTH "instance" and "volume"
# resourceTypes at once -- to reproduce ONLY the "instance but no volume"
# mistake despite that, this fixture bypasses Tags.of() entirely and
# writes the ASG's own `tag` blocks directly via the L1 escape hatch,
# leaving the internally-created launch template completely untouched (no
# tag_specifications of any resourceType at all). Reward must be 0.0 via
# volume-tag-costcenter-present / volume-tag-environment-present (tier 0):
# both resolve to zero nodes.
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

    const fleet = new compute.autoscaling.AutoScalingGroup(this, "WorkerFleet", {
      vpc,
      vpcSubnets: { subnetType: compute.SubnetType.PRIVATE_ISOLATED },
      instanceType: new compute.InstanceType("t3.small"),
      machineImage: compute.MachineImage.genericLinux(
        { "us-east-1": "ami-0c55b159cbfafe1f0" },
        { userData: new NoOpUserData() },
      ),
      minCapacity: 2,
      maxCapacity: 6,
    });

    // THE MISTAKE: tags only the ASG's own `tag` blocks (L1 escape hatch
    // via the public `.resource` field, deliberately bypassing Tags.of()
    // so the internally-created launch template's tag_specifications
    // stays completely untouched -- no "volume" resourceType entry
    // anywhere).
    fleet.resource.putTag([
      { key: "CostCenter", value: "platform-42", propagateAtLaunch: true },
      { key: "Environment", value: "prod", propagateAtLaunch: true },
    ]);
  }
}
TS

bash tests/static_tiers.sh
