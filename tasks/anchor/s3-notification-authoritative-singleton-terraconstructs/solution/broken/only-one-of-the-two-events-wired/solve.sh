#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the only-one-of-the-two-events-wired catch: wires the
# Product half only (upload -> transcode, correctly scoped via
# storage.targets.FunctionDestination) and never creates the SNS topic or
# any ObjectRemoved wiring at all -- the Compliance half of the ticket is
# dropped entirely. Reward must be 0.0 from tier-0 alone (sns-topic-exists
# and object-removed-notification-targets-a-topic both resolve 0 nodes).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, compute, storage } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new storage.Bucket(this, "MediaBucket", {
      bucketName: "cdktn-bench-media-ingest-media",
    });

    const fn = new compute.LambdaFunction(this, "IngestHandler", {
      functionName: "cdktn-bench-media-ingest-transcode",
      runtime: compute.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200 });",
      ),
    });

    // BUG: no SNS topic, no ObjectRemoved wiring -- the Compliance ask
    // was never attempted.
    bucket.addEventNotification(
      storage.EventType.OBJECT_CREATED,
      new storage.targets.FunctionDestination(fn),
      {},
    );
  }
}
TS

bash tests/static_tiers.sh
