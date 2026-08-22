#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the gsi-missing-entirely catch: writes only the
# table's own primary key and never calls addGlobalSecondaryIndex() at
# all. This compiles and `cdk synth` succeeds cleanly (verified directly
# at authoring time, aws-cdk-lib 2.263.0: no ValidationError, the
# synthesized template simply has no GlobalSecondaryIndexes property).
#
# Caught at tier 0 by the EXISTING gsi-hash-key-is-customerId /
# gsi-range-key-is-createdAt / gsi-projection-is-include /
# gsi-projects-exactly-status-and-total structural_asserts (unchanged,
# still applies_to: [awscdk, terraconstructs]): each cfn_jsonpath resolves
# to zero nodes against a template with no GlobalSecondaryIndexes at all,
# and zero resolved nodes against `op: eq`/`op: set_eq` is a hard tier-0
# failure by this whole toolchain's own convention -- this fixture is not
# new toolchain behavior, only a newly-required fixture proving the
# existing tier-0 asserts really do reject it (added alongside the
# hcl_raw-specific existence fix in the adversarial-verification repair
# round -- see specs/ddb-gsi-attribute-definitions.yaml's own header
# comment, section "EXISTENCE + TOTAL-PROJECTION FIX").
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as dynamodb from "aws-cdk-lib/aws-dynamodb";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    // Deliberate mistake: the byCustomer index is never added at all.
    new dynamodb.Table(this, "OrdersTable", {
      partitionKey: { name: "orderId", type: dynamodb.AttributeType.STRING },
    });
  }
}
TS

bash tests/static_tiers.sh
