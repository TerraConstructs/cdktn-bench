#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-missing-entirely catch: writes only the
# table's own primary key and never calls addGlobalSecondaryIndex() at
# all. `npx cdktn synth` succeeds cleanly (terraconstructs 0.2.13's
# storage.Table has no required-GSI validation) and the resulting plan
# JSON has no global_secondary_index at all on the table resource.
#
# CAUGHT AT TIER 1 (REPAIR ROUND 3, 2026-08-22 -- corrected from this
# fixture's original tier-0 mechanism, see below): `gsi-hash-key-is-
# customerId`/`gsi-range-key-is-createdAt`/`gsi-projection-is-include`/
# `gsi-projects-exactly-status-and-total` are now `applies_to: [awscdk]`
# only (the TERRACONSTRUCTS TOLERANCE FIX in
# oracles/rego/ddb-gsi-attribute-definitions/policy.rego's own header
# comment -- terraconstructs's workspace can ALSO produce a standalone
# `aws_dynamodb_global_secondary_index` resource via `@cdktn/provider-
# aws`'s L1 binding, which those four tier-0 jsonpaths cannot see, so
# terraconstructs is graded on those facts at tier 1 now, same as
# hcl_raw). This fixture is caught by the tier-1 existence `deny` rule
# instead: `table_gsis(table)` resolves to the empty list (no inline
# `global_secondary_index` block AND no standalone
# `aws_dynamodb_global_secondary_index` resource at all), which the
# existence rule rejects unconditionally -- see policy.rego's own header
# comment, section "EXISTENCE + TOTAL-PROJECTION FIX", for the full
# argument and live, offline reproduction (that rule already ran against
# terraconstructs's own `terraform show -json` plan output before this
# round; only this catch's OWN capturing mechanism moved, not the rule
# itself).
#
# ORIGINAL (tier-0) mechanism, for the record: before this round,
# `gsi-hash-key-is-customerId` et al. stayed `applies_to: [awscdk,
# terraconstructs]`, and each tf_jsonpath resolved to zero nodes against
# this plan -- zero resolved nodes against `op: eq`/`op: set_eq` is a hard
# tier-0 failure by this whole toolchain's own convention. `npx cdktn
# synth` succeeds cleanly either way (terraconstructs 0.2.13's
# storage.Table has no required-GSI validation) and the resulting plan
# JSON has no global_secondary_index at all on the table resource.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // Deliberate mistake: the byCustomer index is never added at all.
    new storage.Table(this, "OrdersTable", {
      partitionKey: { name: "orderId", type: storage.AttributeType.STRING },
    });
  }
}
TS

bash tests/static_tiers.sh
