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
# only `attribute-definitions-are-exactly-the-key-attributes` (tier 1)
# catches this. As of REPAIR ROUND 4 (2026-08-23, the awscdk tier-1
# engine migration -- see specs/ddb-gsi-attribute-definitions.yaml's own
# header comment) that fact is graded on THIS arm by
# oracles/rego-cfn/ddb-gsi-attribute-definitions/policy.rego, not by the
# now-deleted oracles/cfn-guard/.../policy.guard, and it is rule 1 of
# that file -- "every attribute used as a KEY is one of
# orderId/customerId/createdAt" -- that fires here, on `status` being a
# real RANGE key it may not be. Rule 2 (declared => used as a key) and
# rule 3 (used as a key => declared) both stay silent, `status` being
# both declared and genuinely used, so this fixture is what
# independently falsifies rule 1. On the TF-shaped arms the same fact is
# graded by oracles/rego/ddb-gsi-attribute-definitions/policy.rego's own
# allowlist rule, over the resolved attribute set {orderId, status,
# customerId, createdAt}.
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
