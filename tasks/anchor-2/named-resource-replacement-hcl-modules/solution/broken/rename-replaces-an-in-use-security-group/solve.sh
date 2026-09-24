#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `rename-replaces-an-in-use-security-group`, whose predicted_tier_caught is
# "live" on this arm as on hcl_raw.
#
# THE MISTAKE: the plausible, competent-looking answer. It makes exactly the
# change the prompt asks for -- the root security group the seed's endpoint call
# consumes is renamed to `platform-internal-services-ssm-endpoint` -- and
# nothing else. It initialises, validates, plans, satisfies every tier-0 assert
# and the tier-1 policy, and is statically indistinguishable from the reference.
#
# And on a real account it fails: `name` is ForceNew, so this is a replacement;
# Terraform's default order is destroy-then-create; the group is attached to the
# SSM interface endpoint's ENI, so EC2 answers `DependencyViolation`, the apply
# aborts, and the rename is left half-applied. Re-running retries the same
# destroy.
#
# The module composition changes nothing about that. Composing the endpoint
# through `vpc//modules/vpc-endpoints` would have -- that submodule writes
# `create_before_destroy = true` into the group it creates itself -- but the
# group here is a ROOT resource, which is why this arm's seed puts it there.
#
# WHAT THIS FIXTURE MUST PROVE, AND HOW
# =====================================
# A "live"-tier catch is only falsified if its offline run MECHANICALLY
# DEMONSTRATES the static-indistinguishability property it claims, rather than
# asserting it in a comment (gates/oracle_falsifiability.py's `live` branch,
# LIVE_ONLY_CONFIRMED_MARKER; SCHEMA.md §3). So, offline, with no credentials
# and no account, this script:
#
#   1. plans the REFERENCE shape (with `lifecycle { create_before_destroy =
#      true }`) and extracts the security group's node from the GRADED artifact
#      -- `terraform show -json`'s `.configuration.root_module.resources[]`;
#   2. plans THIS shape (no lifecycle block at all) and extracts the same node;
#   3. requires the two to be BYTE-IDENTICAL.
#
# If they are, no assert, policy or jq path over the graded artifact can tell
# the two apart -- which is the claim -- and the marker is printed. If a future
# terraform release starts emitting `lifecycle` in the JSON plan
# representation, step 3 fails, the marker is not printed, `make falsifiability`
# turns red, and this catch gets re-tiered instead of silently continuing to
# claim invisibility it no longer has.
#
# The probe runs `terraform init` in a scratch directory, so it resolves the two
# module calls from the same registry this workspace does -- the sidecar in the
# arm image, the loopback responder under the host gates (gates/tf_registry.py).
# A probe that could not resolve them would print no marker and fail loudly
# rather than pass quietly.
#
# Expected verdict: reward 1.0 (the static tiers genuinely cannot see this) AND
# the marker on stdout. Both are required; either alone is not falsification.
set -euo pipefail

MARKER="CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
WORK="$(pwd)"
PROBE_DIR="${TMPDIR:-/tmp}/nrr-modules-live-only-probe.$$"

write_common() {
  # $1 -- the security group's lifecycle block (empty for THIS fixture's shape)
  cat > main.tf <<TF
module "internal_services" {
  source  = "terraform-aws-modules/vpc/aws"
  version = "6.7.3"

  name = "internal-services"
  cidr = "10.20.0.0/16"

  azs                  = ["us-east-1a"]
  private_subnets      = ["10.20.1.0/24"]
  private_subnet_names = ["internal-services-a"]

  enable_dns_support   = true
  enable_dns_hostnames = true
}

resource "aws_security_group" "ssm_endpoint" {
  name        = "platform-internal-services-ssm-endpoint"
  description = "HTTPS from the internal services subnet to the SSM interface endpoint"
  vpc_id      = module.internal_services.vpc_id

  ingress {
    description = "HTTPS from the internal services VPC"
    from_port   = 443
    to_port     = 443
    protocol    = "tcp"
    cidr_blocks = ["10.20.0.0/16"]
  }

  egress {
    from_port   = 0
    to_port     = 0
    protocol    = "-1"
    cidr_blocks = ["0.0.0.0/0"]
  }

  tags = {
    Name = "platform-internal-services-ssm-endpoint"
  }
${1}
}

module "ssm_endpoint" {
  source  = "terraform-aws-modules/vpc/aws//modules/vpc-endpoints"
  version = "6.7.3"

  region = "us-east-1"

  vpc_id             = module.internal_services.vpc_id
  subnet_ids         = module.internal_services.private_subnets
  security_group_ids = [aws_security_group.ssm_endpoint.id]

  endpoints = {
    ssm = {
      service_endpoint    = "com.amazonaws.us-east-1.ssm"
      private_dns_enabled = true
      tags = {
        Name = "internal-services-ssm"
      }
    }
  }
}
TF
}

WITH_CBD='
  lifecycle {
    create_before_destroy = true
  }'
WITHOUT_CBD=''

# --- the mechanical static-indistinguishability proof -----------------------
# Run in a scratch copy so the probe's own plan files never pollute the graded
# working tree.
mkdir -p "$PROBE_DIR"
trap 'rm -rf "$PROBE_DIR"' EXIT
cp provider.tf "$PROBE_DIR/provider.tf"

sg_node_for() {
  # $1 -- lifecycle block; echoes the graded artifact's security-group node
  ( cd "$PROBE_DIR" \
    && write_common "$1" \
    && terraform init -input=false >/dev/null \
    && terraform plan -input=false -out=probe.tfplan >/dev/null \
    && terraform show -json probe.tfplan \
       | jq -S '.configuration.root_module.resources[] | select(.type == "aws_security_group")' )
}

WITH_NODE="$(sg_node_for "$WITH_CBD")"
WITHOUT_NODE="$(sg_node_for "$WITHOUT_CBD")"

echo "== static-indistinguishability probe: graded artifact, security group node =="
if [ -z "$WITH_NODE" ] || [ -z "$WITHOUT_NODE" ]; then
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the probe produced no security" >&2
  echo "group node at all, so it compared nothing. Two shapes that both plan to" >&2
  echo "nothing are trivially identical and prove nothing about this catch --" >&2
  echo "check that the probe's own 'terraform init' resolved both module calls." >&2
  exit 1
fi
if [ "$WITH_NODE" = "$WITHOUT_NODE" ]; then
  echo "$MARKER: 'terraform show -json' emits an IDENTICAL"
  echo "  .configuration.root_module.resources[aws_security_group] node with and"
  echo "  without 'lifecycle { create_before_destroy = true }', on a plan whose"
  echo "  VPC and endpoint come from module calls. No tier-0 assert and no Rego"
  echo "  rule over the graded artifact can distinguish the reference solution"
  echo "  from this fixture. The catch is live-only by construction, not by"
  echo "  oracle weakness."
else
  echo "STATIC-INDISTINGUISHABILITY PROOF FAILED: the graded artifact DOES differ" >&2
  echo "between the create_before_destroy and no-create_before_destroy shapes." >&2
  echo "This catch is no longer 'live'-tier -- re-tier it in the spec and add a" >&2
  echo "real static assert. Diff:" >&2
  diff <(echo "$WITH_NODE") <(echo "$WITHOUT_NODE") >&2 || true
fi

# --- the fixture itself: the naive rename, left in place for grading ---------
cd "$WORK"
write_common "$WITHOUT_CBD"

if [ "${LIVE:-0}" = "1" ]; then
  echo "== LIVE: this apply is EXPECTED to fail with DependencyViolation =="
  terraform init -input=false
  # FIXTURE SELF-PROOF. `--expect stale` alone cannot tell this catch from a
  # no-op: live_check.observe() reports fail_stale for ANY unsatisfied
  # assertion, and workspace_seed.deploy has the HARNESS put the old security
  # group in the account before this script starts, so `fail_stale` is true BY
  # CONSTRUCTION before the fixture does anything. So the fixture proves the
  # SPECIFIC failure it exists to pin, in two parts, before consulting the live
  # oracle:
  #   1. the apply must exit NON-ZERO -- it ran, and it lost;
  #   2. its log must name `DependencyViolation` -- it lost for the reason this
  #      catch is ABOUT, not for expired credentials or a broken toolchain.
  DEPLOY_LOG=/tmp/named-resource-replacement-broken-hcl-modules.log
  set +e
  terraform apply -input=false -auto-approve > "$DEPLOY_LOG" 2>&1
  deploy_rc=$?
  set -e
  cat "$DEPLOY_LOG"
  if [ "$deploy_rc" -eq 0 ]; then
    echo "FIXTURE PROOF FAILED: the apply SUCCEEDED (exit 0)." >&2
    echo "This fixture exists to pin a rename that CANNOT apply -- the interface" >&2
    echo "VPC endpoint still holds the old security group, so EC2 must refuse the" >&2
    echo "destroy half of the destroy-then-create. A clean exit means the trap did" >&2
    echo "not fire: either the seed is not in the account (workspace_seed.deploy /" >&2
    echo "pre_invoke/pre_invoke.sh), or this catch is no longer real and the spec" >&2
    echo "must be re-tiered." >&2
    exit 1
  fi
  if ! grep -q "DependencyViolation" "$DEPLOY_LOG"; then
    echo "FIXTURE PROOF FAILED: the apply failed (exit $deploy_rc) but its log" >&2
    echo "never mentions DependencyViolation, so it did NOT fail for the reason this" >&2
    echo "fixture pins. Anything else -- bad credentials, a broken toolchain -- would" >&2
    echo "also reach live_check.py's 'fail_stale' and would be laundered into a green" >&2
    echo "'--expect stale'. Log: $DEPLOY_LOG" >&2
    exit 1
  fi
  echo "== apply failed with DependencyViolation, as this fixture requires =="
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
