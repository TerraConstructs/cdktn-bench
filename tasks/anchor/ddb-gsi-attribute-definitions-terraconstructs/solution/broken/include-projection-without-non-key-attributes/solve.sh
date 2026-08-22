#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the include-projection-without-non-key-attributes
# catch: sets `projectionType: INCLUDE` and omits `nonKeyAttributes`.
# Reward must be 0.0 from the toolchain step itself (`npx cdktn synth`):
# `buildIndexProjection()` (terraconstructs 0.2.13,
# lib/aws/storage/table.js:1047-1050) throws `ValidationError`
# synchronously -- "Non-key attributes should be specified when using
# INCLUDE projection type" -- verified directly against the local
# pnpm-store clone at authoring time. No structural_assert or policy is
# ever reached; cdktf.out/stacks/orders-table/plan.json is never even
# produced.
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
      projectionType: storage.ProjectionType.INCLUDE,
      // nonKeyAttributes deliberately omitted -- this catch's own mistake
    });
  }
}
TS

bash tests/static_tiers.sh
