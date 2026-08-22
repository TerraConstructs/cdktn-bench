#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the include-projection-without-non-key-attributes
# catch: sets `projectionType: INCLUDE` and omits `nonKeyAttributes`.
# Reward must be 0.0 from the toolchain step itself (`npm run build`
# compiles fine -- `nonKeyAttributes` is an optional TS prop -- but
# `cdk synth` fails): `addGlobalSecondaryIndex()`'s projection validation
# (aws-cdk-lib 2.263.0, aws-dynamodb/lib/table.ts:1760-1762) throws
# `ValidationError` synchronously -- "non-key attributes should be
# specified when using INCLUDE projection type" -- verified directly
# against the local clone at authoring time. No structural_assert or
# policy is ever reached; cdk.out/ScenarioStack.template.json is never
# even produced.
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
      projectionType: dynamodb.ProjectionType.INCLUDE,
      // nonKeyAttributes deliberately omitted -- this catch's own mistake
    });
  }
}
TS

bash tests/static_tiers.sh
