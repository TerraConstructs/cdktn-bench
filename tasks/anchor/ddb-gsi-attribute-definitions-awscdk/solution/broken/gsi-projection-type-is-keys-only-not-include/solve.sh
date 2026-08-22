#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-projection-type-is-keys-only-not-include
# catch: sets the GSI's projection to KEYS_ONLY instead of INCLUDE. This
# is a complete, valid projection on its own -- `cdk synth` succeeds
# cleanly, no `ValidationError` (verified directly at authoring time) --
# so nothing here is toolchain-caught. Caught by the two tier-0 asserts
# already in this scenario: `gsi-projection-is-include` (expected
# "INCLUDE", resolved "KEYS_ONLY") and
# `gsi-projects-exactly-status-and-total` (expected {status, totalAmount},
# resolved [] -- KEYS_ONLY has no NonKeyAttributes at all).
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

    table.addGlobalSecondaryIndex({
      indexName: "byCustomer",
      partitionKey: { name: "customerId", type: dynamodb.AttributeType.STRING },
      sortKey: { name: "createdAt", type: dynamodb.AttributeType.STRING },
      // Deliberate mistake: KEYS_ONLY instead of INCLUDE -- the listing
      // needs status/totalAmount without a second read, which KEYS_ONLY
      // does not provide.
      projectionType: dynamodb.ProjectionType.KEYS_ONLY,
    });
  }
}
TS

bash tests/static_tiers.sh
