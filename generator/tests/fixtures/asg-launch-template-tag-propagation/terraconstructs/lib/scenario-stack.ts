import { Construct } from "constructs";
import { AwsStack, AwsStackProps, Tags, compute } from "terraconstructs/lib/aws";

// See this file's own header comment ("NoOpUserData") for why this exists:
// every built-in UserData implementation renders through an offline-
// unmirrored Terraform provider (hashicorp/cloudinit). This scenario's own
// prompt never asks for instance bootstrap content, so an empty render()
// is a correct answer, not a stand-in for one.
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

    // Explicit availabilityZones: compute.Vpc's default AZ resolution
    // creates an unmockable `data "aws_availability_zones"` lookup
    // offline (this scenario's own header comment) -- literal AZs in this
    // arm's pinned region (us-east-1, arms/terraconstructs/environment/
    // app/main.ts) avoid it entirely.
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

    // No explicit launchTemplate: this library's AutoScalingGroup
    // unconditionally builds one internally as a child construct from
    // instanceType/machineImage (see this file's own header comment) --
    // unlike awscdk, an explicit LaunchTemplate construction step is not
    // needed to reach the volume half here.
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

    // ONE aspect call, scoped to the ASG construct, reaches the ASG's own
    // tag-propagation blocks AND the internally-created launch template's
    // instance+volume tag_specifications -- see this file's own header
    // comment for the source-verified mechanism.
    Tags.of(fleet).add("CostCenter", "platform-42");
    Tags.of(fleet).add("Environment", "prod");
  }
}
