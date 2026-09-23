#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8), scenario
# `named-resource-replacement` (the first BROWNFIELD scenario, SCHEMA.md §2.7 /
# DECISIONS.md Amendment 28). Regenerating this scenario will NOT overwrite
# this file (destructive-safe rule).
#
# THIS WORKSPACE DOES NOT START EMPTY. `lib/scenario-stack.ts` already holds the
# deployed configuration for a small internal-service network. The task is ONE
# change: rename the security group to `platform-internal-services-ssm-endpoint`
# and roll it out.
#
# THIS ARM'S CORRECT ANSWER IS THE ONE-LINE EDIT, AND THAT IS THE MEASUREMENT.
# ===========================================================================
# Read the two TF-shaped arms' reference solutions next to this one. Both need
# an extra, non-obvious change -- `lifecycle { create_before_destroy = true }`
# (terraconstructs: through an escape hatch, since its L2 exposes no lifecycle
# passthrough) -- because Terraform's default replacement order is
# destroy-then-create and the group is attached to the interface endpoint's ENI,
# so the destroy is refused with `DependencyViolation`.
#
# CloudFormation's engine differs: a changed `GroupName` is
# Update-requires-Replacement, and CFN's replacement path is
# create-new-then-delete-old. The new group is created (its name differs from
# the old one, so no `InvalidGroup.Duplicate`), the endpoint is updated to point
# at it, and the old group is deleted during cleanup, by which time nothing
# holds it. The naive edit converges here.
#
# That asymmetry is NOT a gap in this scenario -- it is what the scenario
# measures. Do not "even it up" by planting an artificial obstacle on this arm
# (specs/named-resource-replacement.yaml's own header, and the design memo §5.2).
# It is also why `catches[].applies_to` for
# `rename-replaces-an-in-use-security-group` excludes awscdk: there is no
# broken/ fixture for it here because the mistake is not reproducible here.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally run a real `cdk deploy` and assert the live oracle. This
# arm's bin/app.ts always uses ambient credentials, so there is no offline/live
# switch to export (unlike the TF-shaped arms' provider bootstrap).
set -euo pipefail

LIVE="${LIVE:-0}"

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
TS

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real cdk deploy against this account =="
  npm run build
  npx cdk deploy --require-approval never ScenarioStack
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
