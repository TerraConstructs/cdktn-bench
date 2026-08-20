#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `rename-replaces-an-in-use-security-group`, whose predicted_tier_caught is
# "live" on this arm.
#
# THE MISTAKE: the idiomatic L2 answer. `securityGroupName` is changed to the
# new value and nothing else -- which is the only change the L2's own surface
# invites, since it has no `lifecycle` prop to reach for (see this arm's
# reference solution for the escape hatch the correct answer needs). It
# compiles, synthesizes, plans, and satisfies every static tier.
#
# On a real account it fails exactly as hand-written HCL does: `name` is
# ForceNew, Terraform's default replacement order is destroy-then-create, the
# group is attached to the SSM interface endpoint's ENI, EC2 answers
# `DependencyViolation`, and the apply aborts with the rename half-applied.
#
# WHAT THIS FIXTURE MUST PROVE, AND HOW
# =====================================
# A "live"-tier catch is only falsified if its offline run MECHANICALLY
# DEMONSTRATES its static-indistinguishability claim rather than asserting it
# (gates/oracle_falsifiability.py's `live` branch, LIVE_ONLY_CONFIRMED_MARKER).
#
# There is an arm-specific subtlety worth stating, because it is the opposite of
# what one would guess: on THIS arm the lifecycle meta-argument IS visible in
# the SYNTH output -- `cdktf.out/stacks/<id>/cdk.tf.json` carries a literal
# `"lifecycle": {"create_before_destroy": true}`. It is the PLAN step that
# destroys the information: this arm is graded on
# `cdktf.out/stacks/<id>/plan.json` (`terraform show -json`, so both TF-shaped
# arms are graded in the same artifact shape -- SCHEMA.md §2.4), and that
# representation emits no `lifecycle` key at all. So the proof below is run
# against the GRADED artifact, not against the synth output:
#
#   1. synth+plan the REFERENCE shape (escape hatch set) and extract the
#      security group's `.configuration.root_module.resources[]` node;
#   2. synth+plan THIS shape and extract the same node;
#   3. require the two to be BYTE-IDENTICAL.
#
# If a future terraform release starts emitting `lifecycle` in the JSON plan
# representation, step 3 fails, the marker is not printed, `make falsifiability`
# turns red, and the catch gets re-tiered instead of silently continuing to
# claim an invisibility it no longer has.
#
# Expected verdict: reward 1.0 AND the marker on stdout. Both are required.
set -euo pipefail

MARKER="CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
STACK_DIR="cdktf.out/stacks/named-resource-replacement"
MOCK_STS_PORT=17771

write_stack() {
  # $1 -- the create_before_destroy escape hatch (empty for THIS fixture's shape)
  cat > lib/scenario-stack.ts <<TS
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
${1}
    new InterfaceVpcEndpoint(this, "SsmEndpoint", {
      vpc,
      service: InterfaceVpcEndpointAwsService.SSM,
      subnets: { subnetType: SubnetType.PRIVATE_ISOLATED },
      securityGroups: [ssmEndpointSg],
      privateDnsEnabled: true,
      open: false,
    });

    // keep the import referenced in both shapes so tsconfig's unused-import
    // handling cannot make the two variants differ for a reason unrelated to
    // the meta-argument under test
    void (undefined as unknown as TerraformResource);
  }
}
TS
}

WITH_CBD='
    (ssmEndpointSg.node.defaultChild as TerraformResource).lifecycle = {
      createBeforeDestroy: true,
    };
'
WITHOUT_CBD=''

# Graded-artifact probe. The mock STS responder is the same loopback fixture
# tests/static_tiers.sh starts around its own tf-plan step (main.ts's
# providerConfig.endpoints.sts points at it) -- AwsStack lazily creates a
# `data "aws_caller_identity"` that would otherwise 403 offline.
sg_node_for() {
  write_stack "$1" >/dev/null
  npx tsc -p tsconfig.json >/dev/null
  npx cdktn synth >/dev/null 2>&1
  ( cd "$STACK_DIR" \
    && terraform init -input=false >/dev/null \
    && terraform plan -input=false -refresh=false -out=probe.tfplan >/dev/null \
    && terraform show -json probe.tfplan \
       | jq -S '.configuration.root_module.resources[] | select(.type == "aws_security_group")' )
}

# ./mock-sts.js, never /app/project/mock-sts.js: cwd is the project root both
# inside the container AND inside the host sandbox the offline gates prepare
# (gates/oracle_falsifiability.py copies environment/app/ to a scratch dir and
# runs solve.sh with cwd=that dir). An absolute /app/project path silently does
# not exist host-side, the responder never starts, and `terraform plan` then
# fails against a refused connection -- which is broken TEST INFRASTRUCTURE,
# indistinguishable in the logs from a real toolchain failure. Readiness is
# polled and a timeout is FATAL here for the same reason.
node ./mock-sts.js "$MOCK_STS_PORT" > /tmp/nrr-probe-mock-sts.log 2>&1 &
MOCK_STS_PID=$!
trap 'kill "$MOCK_STS_PID" >/dev/null 2>&1 || true' EXIT
MOCK_STS_READY=0
for _ in $(seq 1 50); do
  if (exec 3<>"/dev/tcp/127.0.0.1/$MOCK_STS_PORT") 2>/dev/null; then
    exec 3<&- 3>&- 2>/dev/null
    MOCK_STS_READY=1
    break
  fi
  sleep 0.1
done
if [ "$MOCK_STS_READY" != "1" ]; then
  echo "mock-sts.js never opened 127.0.0.1:$MOCK_STS_PORT -- the" >&2
  echo "static-indistinguishability probe cannot run offline without it." >&2
  echo "See /tmp/nrr-probe-mock-sts.log." >&2
  exit 1
fi

WITH_NODE="$(sg_node_for "$WITH_CBD")"
WITHOUT_NODE="$(sg_node_for "$WITHOUT_CBD")"

kill "$MOCK_STS_PID" >/dev/null 2>&1 || true
wait "$MOCK_STS_PID" 2>/dev/null || true
trap - EXIT

echo "== static-indistinguishability probe: graded artifact, security group node =="
if [ "$WITH_NODE" = "$WITHOUT_NODE" ]; then
  echo "$MARKER: 'terraform show -json' emits an IDENTICAL"
  echo "  .configuration.root_module.resources[aws_security_group] node with and"
  echo "  without the create_before_destroy escape hatch, even though the SYNTH"
  echo "  output (cdk.tf.json) does carry it. This arm is graded on plan.json, so"
  echo "  no tier-0 assert or Rego rule over the graded artifact can distinguish"
  echo "  the reference solution from this fixture. Live-only by construction."
else
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the graded artifact DOES differ" >&2
  echo "between the create_before_destroy and no-create_before_destroy shapes." >&2
  echo "This catch is no longer 'live'-tier -- re-tier it in the spec and add a" >&2
  echo "real static assert. Diff:" >&2
  diff <(echo "$WITH_NODE") <(echo "$WITHOUT_NODE") >&2 || true
fi

# The fixture itself: the naive rename, left in place for grading.
write_stack "$WITHOUT_CBD"
rm -rf "$STACK_DIR/probe.tfplan"

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: this deploy is EXPECTED to fail with DependencyViolation =="
  export CDKTN_BENCH_LIVE=1
  npx tsc -p tsconfig.json
  npx cdktn deploy --auto-approve named-resource-replacement || true
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
