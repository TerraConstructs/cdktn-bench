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

    // Built explicitly (not passed as instanceType/machineImage directly to
    // AutoScalingGroup) so the fleet gets a real AWS::EC2::LaunchTemplate --
    // the only reachable path to volume tag_specifications on this arm.
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

    // Stack-wide Tags aspect: reaches the ASG's own tag-propagation blocks
    // (PropagateAtLaunch=true on every tag) AND the launch template's own
    // TagSpecifications for BOTH "instance" and "volume" resourceTypes --
    // fleet is tagged for the instance half, launchTemplate is tagged
    // (redundantly for instances, and load-bearingly for volumes) for the
    // volume half.
    cdk.Tags.of(fleet).add("CostCenter", "platform-42");
    cdk.Tags.of(fleet).add("Environment", "prod");
    cdk.Tags.of(launchTemplate).add("CostCenter", "platform-42");
    cdk.Tags.of(launchTemplate).add("Environment", "prod");
  }
}
