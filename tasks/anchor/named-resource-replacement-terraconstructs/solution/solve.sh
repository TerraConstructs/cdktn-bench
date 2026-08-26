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
# WHY THIS ARM'S CORRECT ANSWER NEEDS AN ESCAPE HATCH -- an anti-L2 finding
# ========================================================================
# The pitfall is Terraform's, so it applies here exactly as it does on hcl-raw:
# `name` is ForceNew, the default replacement order is destroy-then-create, and
# the group is attached to the interface endpoint's ENI, so the destroy is
# refused with `DependencyViolation`.
#
# But the fix is NOT reachable through the L2 surface. Source-verified against
# terraconstructs 0.2.13 (this arm's pinned version):
#   * `SecurityGroupProps` has no `lifecycle` member, and none of the props
#     bags above it (`AwsConstructProps`) do either;
#   * the L2's underlying L1 is `private readonly securityGroup` -- not exposed.
# So the only way to express `create_before_destroy` is the standard CDK escape
# hatch: reach the default child and set the meta-argument on it directly.
# `TerraformResource.lifecycle` is a public, mutable property on cdktn's own
# base class, so this is a supported escape hatch and not a hack.
#
# This is the shape of an anti-L2 finding worth recording: raw HCL exposes the
# knob that fixes the problem as a first-class two-line block; the L2 hides it
# behind construct-tree archaeology. Compare `../../named-resource-replacement-
# hcl-raw/solution/solve.sh`.
#
# One more arm-specific fact, load-bearing and easy to lose: the L2 `Vpc` emits
# a `data "aws_availability_zones"` lookup unless `availabilityZones` is given
# explicitly, and that lookup cannot resolve under this arm's offline
# dummy-credential provider config. The seed pins the AZ for that reason; this
# solution must keep it pinned or the graded `terraform plan` step fails for a
# reason unrelated to the change.
#
# --- OFFLINE vs. LIVE ------------------------------------------------------
# Default (LIVE unset/0): write the file, run the same tests/static_tiers.sh a
# real trial's verifier runs. No AWS call of any kind.
# LIVE=1: additionally export CDKTN_BENCH_LIVE=1 so the SEEDED, non-agent-owned
# ./main.ts switches from its offline dummy-credential/mock-STS fixture to real
# ambient credentials, run a real deploy, and assert the live oracle. This
# script never writes or edits main.ts -- exactly the constraint a real agent
# solving this scenario is under.
set -euo pipefail

LIVE="${LIVE:-0}"

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
TS

if [ "$LIVE" = "1" ]; then
  echo "== LIVE: real cdktn deploy against this account =="
  export CDKTN_BENCH_LIVE=1
  npx tsc -p tsconfig.json
  # The positional argument is the STACK id -- main.ts constructs
  # `new ScenarioStack(app, "internal-services-network", ...)`, i.e. the
  # spec's `workspace_id`, not its `id`. This line named the spec id until
  # 2026-08-25 and therefore named a stack that does not exist: this LIVE=1
  # path cannot ever have worked. Found while tracing the deploy commands
  # for workspace_seed.deploy (docs/design/single-step-seed-deploy.md §10).
  npx cdktn deploy --auto-approve internal-services-network
  python3 tests/live_check.py --expect ok
fi

exec bash tests/static_tiers.sh
