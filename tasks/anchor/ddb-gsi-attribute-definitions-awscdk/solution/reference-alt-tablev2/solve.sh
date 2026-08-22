#!/usr/bin/env bash
# SECOND, alternate-shape reference solution -- HAND-AUTHORED, proving the
# TableV2 tolerance fix documented in specs/ddb-gsi-attribute-
# definitions.yaml's own "ALTERNATIVE-SHAPE FIX" header comment. NOT
# auto-discovered by gates/oracle_falsifiability.py or
# gates/grading_proof.py -- both walk `solution/solve.sh` (the canonical
# `dynamodb.Table`-shaped reference) and `solution/broken/*` (required to
# score 0.0) only; the harness has no third slot for "a second, equally
# CORRECT shape", so this fixture is a manually-run, additional proof, not
# part of the automated gate chain. Run it exactly like the canonical
# solve.sh is run (copy this arm's environment/workspace, write
# lib/scenario-stack.ts, run tests/static_tiers.sh) to reproduce.
#
# `dynamodb.TableV2` -- aws-cdk-lib 2.263.0's own aws-dynamodb/README.md
# calls it "the preferred construct for all use cases, including creating
# a single table" -- synthesizes AWS::DynamoDB::GlobalTable, not
# AWS::DynamoDB::Table. REPRODUCED directly at authoring time: this exact
# shape synths a template whose Properties are byte-identical in shape to
# AWS::DynamoDB::Table's (AttributeDefinitions/KeySchema/
# GlobalSecondaryIndexes[*].KeySchema/.Projection.{ProjectionType,
# NonKeyAttributes} all present at the same paths -- the only additions
# are a top-level Replicas array and a per-GSI-replica stanza, neither of
# which any structural_assert touches), and every one of this scenario's
# six structural_asserts (widened to accept
# `@.Type=='AWS::DynamoDB::GlobalTable'` alongside
# `@.Type=='AWS::DynamoDB::Table'`) resolves and passes against it, scoring
# reward 1.0 end-to-end via the real tests/static_tiers.sh -- verified
# directly by running it.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    new dynamodb.TableV2(this, "OrdersTable", {
      partitionKey: { name: "orderId", type: dynamodb.AttributeType.STRING },
      globalSecondaryIndexes: [
        {
          indexName: "byCustomer",
          partitionKey: { name: "customerId", type: dynamodb.AttributeType.STRING },
          sortKey: { name: "createdAt", type: dynamodb.AttributeType.STRING },
          projectionType: dynamodb.ProjectionType.INCLUDE,
          nonKeyAttributes: ["status", "totalAmount"],
        },
      ],
    });
  }
}
TS

bash tests/static_tiers.sh
