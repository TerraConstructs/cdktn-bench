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
STACK_DIR="cdktf.out/stacks/internal-services-network"

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

# Graded-artifact probe: synth+plan a shape and emit the security group node in
# the same artifact shape tests/static_tiers.sh grades.
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

WITH_NODE="$(sg_node_for "$WITH_CBD")"
WITHOUT_NODE="$(sg_node_for "$WITHOUT_CBD")"

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
  npx tsc -p tsconfig.json
  # The positional argument is the STACK id -- main.ts constructs
  # `new ScenarioStack(app, "internal-services-network", ...)`, i.e. the
  # spec's `workspace_id`, not its `id`. This line named the spec id until
  # 2026-08-25 and therefore named a stack that does not exist: this LIVE=1
  # path cannot ever have worked. Found while tracing the deploy commands
  # for workspace_seed.deploy (docs/design/single-step-seed-deploy.md §10).
  # FIXTURE SELF-PROOF (finding M5, adversarial review 2026-08-25). This pair
  # of lines used to be
  #     npx cdktn deploy --auto-approve internal-services-network || true
  #     python3 tests/live_check.py --expect stale
  # and that pair CANNOT tell the catch from a
  # no-op. `--expect stale` requires only `outcome == "fail_stale"`, and
  # live_check.observe() reports fail_stale for ANY unsatisfied assertion --
  # including "the deploy never ran". That is not a hypothetical: this exact
  # line named a NONEXISTENT stack for its entire life (see the stack-id note
  # above, fixed 2026-08-25) and nothing anywhere went red. It is now strictly
  # WORSE than hypothetical, because workspace_seed.deploy has the HARNESS put
  # the old security group in the account before this script starts -- so
  # `fail_stale` is true BY CONSTRUCTION, before the fixture does anything at
  # all.
  #
  # So the fixture proves the SPECIFIC failure it exists to pin, in two parts,
  # before it is allowed to consult the live oracle:
  #   1. the deploy must exit NON-ZERO -- it ran, and it lost;
  #   2. its log must name `DependencyViolation` -- it lost for the reason this
  #      catch is ABOUT (EC2 refusing to delete a security group an interface
  #      endpoint's ENI still holds), not for some unrelated reason such as
  #      expired credentials, a typo'd stack id, or a missing toolchain.
  # Only then does `--expect stale` run, and by that point it is corroboration
  # rather than the whole proof.
  DEPLOY_LOG=/tmp/named-resource-replacement-broken-terraconstructs.log
  set +e
  npx cdktn deploy --auto-approve internal-services-network > "$DEPLOY_LOG" 2>&1
  deploy_rc=$?
  set -e
  cat "$DEPLOY_LOG"
  if [ "$deploy_rc" -eq 0 ]; then
    echo "FIXTURE PROOF FAILED: the deploy SUCCEEDED (exit 0)." >&2
    echo "This fixture exists to pin a rename that CANNOT apply -- the interface" >&2
    echo "VPC endpoint still holds the old security group, so EC2 must refuse the" >&2
    echo "destroy half of the destroy-then-create. A clean exit means the trap did" >&2
    echo "not fire: either the seed is not in the account (workspace_seed.deploy /" >&2
    echo "pre_invoke/pre_invoke.sh), or this catch is no longer real and the spec" >&2
    echo "must be re-tiered." >&2
    exit 1
  fi
  if ! grep -q "DependencyViolation" "$DEPLOY_LOG"; then
    echo "FIXTURE PROOF FAILED: the deploy failed (exit $deploy_rc) but its log" >&2
    echo "never mentions DependencyViolation, so it did NOT fail for the reason this" >&2
    echo "fixture pins. Anything else -- bad credentials, a wrong stack id, a broken" >&2
    echo "toolchain -- would also reach live_check.py's 'fail_stale' and would be" >&2
    echo "laundered into a green '--expect stale'. Log: $DEPLOY_LOG" >&2
    exit 1
  fi
  echo "== deploy failed with DependencyViolation, as this fixture requires =="
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
