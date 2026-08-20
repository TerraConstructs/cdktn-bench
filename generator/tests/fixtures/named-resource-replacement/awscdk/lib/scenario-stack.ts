import * as cdk from "aws-cdk-lib";
import * as ec2 from "aws-cdk-lib/aws-ec2";
import { Construct } from "constructs";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const vpc = new ec2.Vpc(this, "InternalServices", {
      ipAddresses: ec2.IpAddresses.cidr("10.20.0.0/16"),
      maxAzs: 1,
      natGateways: 0,
      restrictDefaultSecurityGroup: false,
      subnetConfiguration: [
        {
          name: "isolated",
          subnetType: ec2.SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    const ssmEndpointSg = new ec2.SecurityGroup(this, "SsmEndpointSg", {
      vpc,
      securityGroupName: "platform-internal-services-ssm-endpoint",
      description:
        "HTTPS from the internal services subnet to the SSM interface endpoint",
      allowAllOutbound: true,
    });
    ssmEndpointSg.addIngressRule(
      ec2.Peer.ipv4("10.20.0.0/16"),
      ec2.Port.tcp(443),
      "HTTPS from the internal services VPC",
    );

    new ec2.InterfaceVpcEndpoint(this, "SsmEndpoint", {
      vpc,
      service: ec2.InterfaceVpcEndpointAwsService.SSM,
      subnets: { subnetType: ec2.SubnetType.PRIVATE_ISOLATED },
      securityGroups: [ssmEndpointSg],
      privateDnsEnabled: true,
      open: false,
    });
  }
}
