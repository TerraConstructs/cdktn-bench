#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape verified directly against aws-cdk-lib 2.263.0's own source
# (packages/aws-cdk-lib/aws-dynamodb/lib/table.ts, local clone) at
# authoring time: `Table.addGlobalSecondaryIndex()` calls the private
# `registerAttribute()` on `partitionKey`/`sortKey` as a side effect
# (:1749/:1789), so orderId/customerId/createdAt all land in
# AttributeDefinitions automatically -- no separate attribute-declaration
# step exists to get wrong. `ProjectionType.INCLUDE` + `nonKeyAttributes`
# renders Projection.{ProjectionType,NonKeyAttributes} exactly as given.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const table = new dynamodb.Table(this, "OrdersTable", {
      partitionKey: { name: "orderId", type: dynamodb.AttributeType.STRING },
    });

    // registerAttribute() (called internally for partitionKey/sortKey)
    // is the ONLY writer of the table's AttributeDefinitions set on this
    // construct -- there is no public API to declare an attribute that
    // isn't a key, so shippingAddress/lineItems/paymentReference (real
    // item attributes, never table/index keys) simply never appear here.
    table.addGlobalSecondaryIndex({
      indexName: "byCustomer",
      partitionKey: { name: "customerId", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "createdAt", type: dynamodb.AttributeType.STRING },
      projectionType: dynamodb.ProjectionType.INCLUDE,
      nonKeyAttributes: ["status", "totalAmount"],
    });
  }
}
TS

bash tests/static_tiers.sh
