#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `rename-replaces-an-in-use-security-group`, whose predicted_tier_caught is
# "live" on this arm.
#
# THE MISTAKE: the plausible, competent-looking answer. It makes exactly the
# change the prompt asks for -- the security group is renamed to
# `platform-internal-services-ssm-endpoint` -- and nothing else. It builds. It
# validates. It plans. It satisfies every tier-0 assert and the tier-1 policy.
# It is, statically, indistinguishable from the reference solution.
#
# And on a real account it fails: `name` is ForceNew, so this is a replacement;
# Terraform's default order is destroy-then-create; the group is attached to the
# SSM interface endpoint's ENI, so EC2 answers `DependencyViolation`, the apply
# aborts, and the rename is left half-applied. Re-running retries the same
# destroy.
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
# If they are, no assert, policy or jq path over the graded artifact can ever
# tell the two apart -- which is the claim -- and the marker is printed. If a
# future terraform release starts emitting `lifecycle` in the JSON plan
# representation, step 3 fails, the marker is not printed, `make falsifiability`
# turns red, and this scenario's catch gets re-tiered from "live" to "0" instead
# of silently continuing to claim invisibility it no longer has.
#
# Expected verdict: reward 1.0 (the static tiers genuinely cannot see this) AND
# the marker on stdout. Both are required; either alone is not falsification.
set -euo pipefail

MARKER="CDKTN_BENCH_LIVE_ONLY_CONFIRMED"
WORK="$(pwd)"
PROBE_DIR="${TMPDIR:-/tmp}/nrr-live-only-probe.$$"

write_common() {
  # $1 -- the security group's lifecycle block (empty for THIS fixture's shape)
  cat > main.tf <<TF
resource "aws_vpc" "internal_services" {
  cidr_block           = "10.20.0.0/16"
  enable_dns_support   = true
  enable_dns_hostnames = true

  tags = {
    Name = "internal-services"
  }
}

resource "aws_subnet" "internal_services_a" {
  vpc_id            = aws_vpc.internal_services.id
  cidr_block        = "10.20.1.0/24"
  availability_zone = "us-east-1a"

  tags = {
    Name = "internal-services-a"
  }
}

resource "aws_security_group" "ssm_endpoint" {
  name        = "platform-internal-services-ssm-endpoint"
  description = "HTTPS from the internal services subnet to the SSM interface endpoint"
  vpc_id      = aws_vpc.internal_services.id

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

resource "aws_vpc_endpoint" "ssm" {
  vpc_id              = aws_vpc.internal_services.id
  service_name        = "com.amazonaws.us-east-1.ssm"
  vpc_endpoint_type   = "Interface"
  subnet_ids          = [aws_subnet.internal_services_a.id]
  security_group_ids  = [aws_security_group.ssm_endpoint.id]
  private_dns_enabled = true

  tags = {
    Name = "internal-services-ssm"
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

# `write_common` is defined in this shell; make it visible to the subshell above
# by simply calling it there (same process tree, no export needed).
WITH_NODE="$(sg_node_for "$WITH_CBD")"
WITHOUT_NODE="$(sg_node_for "$WITHOUT_CBD")"

echo "== static-indistinguishability probe: graded artifact, security group node =="
if [ "$WITH_NODE" = "$WITHOUT_NODE" ]; then
  echo "$MARKER: 'terraform show -json' emits an IDENTICAL"
  echo "  .configuration.root_module.resources[aws_security_group] node with and"
  echo "  without 'lifecycle { create_before_destroy = true }'. No tier-0 assert,"
  echo "  Rego rule or cfn-guard rule over the graded artifact can distinguish the"
  echo "  reference solution from this fixture. The catch is live-only by"
  echo "  construction, not by oracle weakness."
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
  export TF_VAR_cdktn_bench_live=1
  terraform init -input=false
  terraform apply -input=false -auto-approve || true
  python3 tests/live_check.py --expect stale
fi

exec bash tests/static_tiers.sh
