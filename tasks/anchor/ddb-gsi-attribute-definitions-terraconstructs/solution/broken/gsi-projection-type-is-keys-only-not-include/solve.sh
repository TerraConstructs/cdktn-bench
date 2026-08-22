#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-projection-type-is-keys-only-not-include
# catch: sets the GSI's projection to KEYS_ONLY instead of INCLUDE. This
# is a complete, valid projection on its own -- `npx cdktn synth` succeeds
# cleanly, no thrown validation error (verified directly at authoring
# time) -- so nothing here is toolchain-caught. Caught by the two facts
# `gsi-projection-is-include` (expected "INCLUDE", resolved "KEYS_ONLY")
# and `gsi-projects-exactly-status-and-total` (expected {status,
# totalAmount}, resolved [] -- KEYS_ONLY has no non_key_attributes at
# all) encode.
#
# TERRACONSTRUCTS TOLERANCE FIX (REPAIR ROUND 3, 2026-08-22): these two
# facts are now graded at TIER 1, not tier 0, for terraconstructs too --
# `gsi-projection-is-include`/`gsi-projects-exactly-status-and-total` are
# now `applies_to: [awscdk]` only (terraconstructs's workspace can ALSO
# produce a standalone `aws_dynamodb_global_secondary_index` resource via
# `@cdktn/provider-aws`'s L1 binding, which those tier-0 jsonpaths cannot
# see -- see oracles/rego/ddb-gsi-attribute-definitions/policy.rego's own
# header comment, section "TERRACONSTRUCTS TOLERANCE FIX"). The same
# shape-tolerant `resolved_projection_type`/`resolved_non_key_attributes`
# rules hcl_raw uses now grade this fixture's plan too -- unchanged
# mechanism, only which arm's plan JSON it runs against.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const table = new storage.Table(this, "OrdersTable", {
      partitionKey: { name: "orderId", type: storage.AttributeType.STRING },
    });

    table.addGlobalSecondaryIndex({
      indexName: "byCustomer",
      partitionKey: { name: "customerId", type: storage.AttributeType.STRING },
      sortKey: { name: "createdAt", type: storage.AttributeType.STRING },
      // Deliberate mistake: KEYS_ONLY instead of INCLUDE -- the listing
      // needs status/totalAmount without a second read, which KEYS_ONLY
      // does not provide.
      projectionType: storage.ProjectionType.KEYS_ONLY,
    });
  }
}
TS

bash tests/static_tiers.sh
