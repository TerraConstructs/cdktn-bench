#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-key-attribute-not-declared catch on the
# awscdk arm: the byCustomer index still RANGES on `createdAt`, but
# `createdAt` has no AttributeDefinitions entry.
#
# THIS IS THE SHAPE THAT CONDEMNED THE RETIRED cfn-guard RULE (REPAIR
# ROUND 4, 2026-08-23 -- see specs/ddb-gsi-attribute-definitions.yaml's
# own header comment and oracles/rego-cfn/ddb-gsi-attribute-definitions/
# policy.rego's). Pre-migration it scored REWARD 1.0 on this arm: all
# five tier-0 asserts pass (not one of them reads AttributeDefinitions)
# and the tier-1 allowlist rule `AttributeName IN [orderId, customerId,
# createdAt]` passed too, because an allowlist cannot see a name that is
# ABSENT. The byte-equivalent hcl_raw mistake is rejected by `terraform
# plan` ("all indexes must match a defined attribute. Unmatched indexes:
# [\"createdAt\"]") for REWARD 0.0 -- a 1.0-vs-0.0 cross-arm split on one
# intent violation, which DECISIONS.md Amendment 29 §4 forbids.
#
# The catch's own description used to call this "structurally unreachable
# on awscdk". That is true of aws-cdk-lib's L2 API -- addGlobalSecondaryIndex()
# calls the private registerAttribute() on its own partitionKey/sortKey --
# but not of the ARM, which also ships `dynamodb.CfnTable` and
# `Construct.node.defaultChild`. One escape hatch on the otherwise
# byte-identical reference solution reaches it, and LIVE-VERIFIED at
# authoring time (aws-cdk-lib 2.263.0): `npm run build` compiles and
# `npx cdk synth` EXITS 0 -- only a `CloudFormation-Validate::E3039`
# WARNING ("GSI KeySchema attribute 'createdAt' is not defined in
# AttributeDefinitions"), never an error -- so the template IS produced
# and IS graded, and the ORACLE, not the toolchain, has to reject it.
#
# Caught at TIER 1 (predicted_tier_caught.awscdk: "1") by rule 3 of
# oracles/rego-cfn/ddb-gsi-attribute-definitions/policy.rego -- "every key
# attribute must have a matching attribute definition on the same table"
# -- and by that rule ALONE: rule 1 stays silent (createdAt is an allowed
# key name) and rule 2 stays silent (nothing is declared-but-unused), so
# this fixture is what independently falsifies rule 3.
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
      nonKeyAttributes: ["status", "totalAmount"],
    });

    // Deliberate mistake: the synthesized attribute-definition set is
    // overridden to drop `createdAt`, which the byCustomer index still
    // uses as its RANGE key. DynamoDB requires every key attribute to
    // have a matching definition; CloudFormation rejects this at deploy
    // time, and `terraform plan` rejects the identical HCL outright.
    const cfnTable = table.node.defaultChild as dynamodb.CfnTable;
    cfnTable.addPropertyOverride("AttributeDefinitions", [
      { AttributeName: "orderId", AttributeType: "S" },
      { AttributeName: "customerId", AttributeType: "S" },
    ]);
  }
}
TS

bash tests/static_tiers.sh
