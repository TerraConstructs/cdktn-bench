#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the attribute-definitions-include-non-key-attributes
# catch on the awscdk arm: shippingAddress, lineItems and
# paymentReference are declared as attribute definitions even though none
# of them is a key of the table or of the byCustomer index. This is the
# "declare your schema" reflex the ticket's own item-shape sentence
# invites -- DynamoDB is schemaless for non-key data, so those three
# declarations are invalid, not merely redundant (the identical HCL is
# rejected by `terraform plan`: "all attributes must be indexed. Unused
# attributes: [\"lineItems\" \"paymentReference\" \"shippingAddress\"]").
#
# Added in REPAIR ROUND 4 (2026-08-23), the awscdk tier-1 engine
# migration -- see specs/ddb-gsi-attribute-definitions.yaml's own header
# comment. The catch's description used to call this "structurally
# unreachable on awscdk", which holds for aws-cdk-lib's L2 API
# (registerAttribute() is only ever called from a key-defining path) but
# not for the ARM: it also ships `dynamodb.CfnTable` and
# `Construct.node.defaultChild`. LIVE-VERIFIED at authoring time
# (aws-cdk-lib 2.263.0): `npm run build` compiles and `npx cdk synth`
# EXITS 0 with no warning at all (CloudFormation's own template validator
# only flags the MISSING direction), so nothing in the toolchain rejects
# it and the ORACLE has to.
#
# Caught at TIER 1 (predicted_tier_caught.awscdk: "1") by rule 2 of
# oracles/rego-cfn/ddb-gsi-attribute-definitions/policy.rego -- "every
# declared attribute definition must be used as a key by this table or
# one of its indexes" -- and by that rule ALONE: the KEY attributes are
# still exactly orderId/customerId/createdAt so rule 1 stays silent, and
# every key is still declared so rule 3 stays silent. This fixture is
# therefore what independently falsifies rule 2, the half of the join a
# name allowlist could only ever approximate (the retired cfn-guard rule
# rejected this shape too, but for the wrong reason -- "shippingAddress"
# is not in a hard-coded list of three names -- rather than for the
# defect, which is that it is used by no key).
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

    // Deliberate mistake: the item's non-key attributes are declared as
    // attribute definitions, as if `AttributeDefinitions` were a schema.
    // None of shippingAddress/lineItems/paymentReference is a key of the
    // table or of any of its indexes.
    const cfnTable = table.node.defaultChild as dynamodb.CfnTable;
    cfnTable.addPropertyOverride("AttributeDefinitions", [
      { AttributeName: "orderId", AttributeType: "S" },
      { AttributeName: "customerId", AttributeType: "S" },
      { AttributeName: "createdAt", AttributeType: "S" },
      { AttributeName: "shippingAddress", AttributeType: "S" },
      { AttributeName: "lineItems", AttributeType: "S" },
      { AttributeName: "paymentReference", AttributeType: "S" },
    ]);
  }
}
TS

bash tests/static_tiers.sh
