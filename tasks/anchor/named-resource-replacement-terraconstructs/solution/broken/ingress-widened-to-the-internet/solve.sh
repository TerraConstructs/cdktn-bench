#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `ingress-widened-to-the-internet`, predicted_tier_caught "1" on every arm.
#
# THE MISTAKE: the rename is done correctly AND the create_before_destroy
# escape hatch is kept -- this would deploy cleanly -- but the 443 ingress is
# "simplified" from the VPC CIDR to `Peer.anyIpv4()`, putting the SSM interface
# endpoint on the public internet.
#
# Expected verdict: reward 0.0, caught at TIER 1 (the Rego policy family in
# oracles/rego/named-resource-replacement/policy.rego), NOT at tier 0. Tier 0
# passes here on purpose, so this fixture genuinely exercises the tier-1 chain.
set -euo pipefail

cat > lib/scenario-stack.ts <<'TS'
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
    ssmEndpointSg.addIngressRule(Peer.anyIpv4(), Port.tcp(443), "HTTPS");

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
TS

exec bash tests/static_tiers.sh
