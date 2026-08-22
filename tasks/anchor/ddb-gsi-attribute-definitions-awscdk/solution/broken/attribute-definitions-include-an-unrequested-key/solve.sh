#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the attribute-definitions-include-an-unrequested-key
# catch: gives the table its own sort key on `status`, in addition to the
# requested byCustomer GSI. This is a REAL, always-available primary-key
# shape -- `new dynamodb.Table(..., { partitionKey, sortKey })` -- so
# nothing rejects it: `npm run build` compiles fine and `cdk synth`
# succeeds cleanly (verified directly at authoring time, aws-cdk-lib
# 2.263.0: no `ValidationError`, `AttributeDefinitions` gets a fourth
# entry for `status`). Every OTHER structural_assert in this scenario
# still passes (table HASH key is still orderId; there is still exactly
# one GSI, still customerId/createdAt/INCLUDE/[status,totalAmount]) --
# only `attribute-definitions-are-exactly-the-key-attributes` (tier 1,
# oracles/rego+cfn-guard/ddb-gsi-attribute-definitions) catches this: the
# resolved attribute set is {orderId, status, customerId, createdAt}, and
# `status` is not IN the allowlist.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Deliberate mistake: the table is given its own sort key on
    // `status` -- a real key, not a dangling attribute -- that no ticket
    // text asked for ("each order is identified by orderId" names the
    // table's own key as orderId alone).
    const table = new dynamodb.Table(this, "OrdersTable", {
      partitionKey: { name: "orderId", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "status", type: dynamodb.AttributeType.STRING },
    });

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
