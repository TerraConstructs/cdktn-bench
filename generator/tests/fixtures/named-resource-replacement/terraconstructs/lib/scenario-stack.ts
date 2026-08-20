import { TerraformResource } from "cdktn";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import {
  InterfaceVpcEndpoint,
  InterfaceVpcEndpointAwsService,
  IpAddresses,
  Peer,
  Port,
  SecurityGroup,
  SubnetType,
  Vpc,
} from "terraconstructs/lib/aws/compute";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const vpc = new Vpc(this, "InternalServices", {
      ipAddresses: IpAddresses.cidr("10.20.0.0/16"),
      availabilityZones: ["us-east-1a"],
      natGateways: 0,
      subnetConfiguration: [
        {
          name: "isolated",
          subnetType: SubnetType.PRIVATE_ISOLATED,
          cidrMask: 24,
        },
      ],
    });

    const ssmEndpointSg = new SecurityGroup(this, "SsmEndpointSg", {
      vpc,
      securityGroupName: "platform-internal-services-ssm-endpoint",
      description:
        "HTTPS from the internal services subnet to the SSM interface endpoint",
      allowAllOutbound: true,
    });
    ssmEndpointSg.addIngressRule(
      Peer.ipv4("10.20.0.0/16"),
      Port.tcp(443),
      "HTTPS from the internal services VPC",
    );

    // Renaming this group forces a replacement, and it is attached to the
    // interface endpoint's ENI: the default destroy-then-create order cannot
    // delete it while the endpoint holds it. The L2 exposes no `lifecycle`
    // prop, so set the meta-argument on the underlying resource directly.
    (ssmEndpointSg.node.defaultChild as TerraformResource).lifecycle = {
      createBeforeDestroy: true,
    };

    new InterfaceVpcEndpoint(this, "SsmEndpoint", {
      vpc,
      service: InterfaceVpcEndpointAwsService.SSM,
      subnets: { subnetType: SubnetType.PRIVATE_ISOLATED },
      securityGroups: [ssmEndpointSg],
      privateDnsEnabled: true,
      open: false,
    });
  }
}
