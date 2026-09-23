#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `ingress-widened-to-the-internet`, predicted_tier_caught "1" on every arm.
#
# THE MISTAKE: the rename is done correctly, but the 443 ingress rule is
# "simplified" from the VPC CIDR to `ec2.Peer.anyIpv4()`, putting the SSM
# interface endpoint on the public internet.
#
# Expected verdict: reward 0.0, caught at TIER 1 (cfn-guard, via
# oracles/cfn-guard/named-resource-replacement/policy.guard), NOT at tier 0.
# Tier 0 passes here on purpose -- the group carries the new name, the endpoint
# exists and still references the group -- so this fixture genuinely exercises
# this arm's cfn-guard chain rather than being rejected by a cheaper check
# first. gates/oracle_falsifiability.py checks the OBSERVED tier, so a
# regression that moved this to tier 0 would show up as a tier-attribution
# mismatch rather than passing quietly.
set -euo pipefail

cat > lib/scenario-stack.ts <<'TS'
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
    ssmEndpointSg.addIngressRule(ec2.Peer.anyIpv4(), ec2.Port.tcp(443), "HTTPS");

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
TS

exec bash tests/static_tiers.sh
