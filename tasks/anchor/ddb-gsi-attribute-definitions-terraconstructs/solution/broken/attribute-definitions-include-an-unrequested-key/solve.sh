#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the attribute-definitions-include-an-unrequested-key
# catch: gives the table its own sort key on `status`, in addition to the
# requested byCustomer GSI. terraconstructs 0.2.13's `storage.Table`
# exposes the identical `sortKey?: Attribute` prop on `TableOptions`
# (lib/aws/storage/table.d.ts:26, local pnpm-store clone, verified
# directly at authoring time) rendered through the SAME
# `registerAttribute()` this scenario's own reference solution documents
# -- `npx cdktn synth` succeeds cleanly, `attribute` gets a fourth entry
# for `status`. Every OTHER structural_assert in this scenario still
# passes -- only `attribute-definitions-are-exactly-the-key-attributes`
# (tier 1, oracles/rego/ddb-gsi-attribute-definitions/policy.rego, graded
# against this arm's own `terraform show -json` plan, same as hcl_raw)
# catches this: the resolved attribute set is {orderId, status,
# customerId, createdAt}, and `status` is not IN the allowlist.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    // Deliberate mistake: the table is given its own sort key on
    // `status` -- a real key, not a dangling attribute -- that no ticket
    // text asked for ("each order is identified by orderId" names the
    // table's own key as orderId alone).
    const table = new storage.Table(this, "OrdersTable", {
      partitionKey: { name: "orderId", type: storage.AttributeType.STRING },
      sortKey: { name: "status", type: storage.AttributeType.STRING },
    });

    table.addGlobalSecondaryIndex({
      indexName: "byCustomer",
      partitionKey: { name: "customerId", type: storage.AttributeType.STRING },
      sortKey: { name: "createdAt", type: storage.AttributeType.STRING },
      projectionType: storage.ProjectionType.INCLUDE,
      nonKeyAttributes: ["status", "totalAmount"],
    });
  }
}
TS

bash tests/static_tiers.sh
