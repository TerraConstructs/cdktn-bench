#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape verified directly against terraconstructs 0.2.13's own source
# (lib/aws/storage/table.js, local pnpm-store clone) at authoring time:
# `Table.addGlobalSecondaryIndex()` calls the private `registerAttribute()`
# on `partitionKey`/`sortKey` as a side effect (:783-784), the SAME
# mechanism aws-cdk-lib's Table class uses -- so orderId/customerId/
# createdAt all land in the rendered `attribute` list automatically, with
# no separate attribute-declaration step to get wrong.
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

    // registerAttribute() (called internally for partitionKey/sortKey)
    // is the ONLY writer of the table's attribute-definition set on this
    // construct -- there is no public API to declare an attribute that
    // isn't a key, so shippingAddress/lineItems/paymentReference (real
    // item attributes, never table/index keys) simply never appear here.
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
