#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the NEW (round 6) audit-topic-events-cover-a-real-
# delete tier-1 rule: identical to the reference solution except ONE
# argument -- `storage.EventType.LIFECYCLE_EXPIRATION` in place of
# `storage.EventType.OBJECT_REMOVED`. The hand-authored TopicDestination
# still scopes the topic policy correctly (this mistake is about WHICH
# event family is wired, not about scoping), so this fixture passes every
# tier-0 assert and the lambda-permission tier-1 rule -- it fails
# audit_topic_covers_a_real_delete alone: `EventType.LIFECYCLE_EXPIRATION`
# is a first-class terraconstructs 0.2.13 enum member
# (lib/aws/storage/bucket.d.ts, re-verified against the pinned package
# tree), so this is reachable through the SAME idiomatic call site the
# reference solution itself uses, not a fabricated escape hatch.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import {
  AwsStack,
  AwsStackProps,
  compute,
  iam,
  notify,
  storage,
} from "terraconstructs/lib/aws";

// Hand-authored SNS destination -- terraconstructs 0.2.13's own
// `notification-targets/` ships FunctionDestination and QueueDestination
// but no TopicDestination (see this scenario's own reference
// solution/solve.sh for the full explanation).
class TopicDestination implements storage.IBucketNotificationDestination {
  constructor(private readonly topic: notify.ITopic) {}

  bind(
    _scope: Construct,
    bucket: storage.IBucket,
  ): storage.BucketNotificationDestinationConfig {
    this.topic.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("s3.amazonaws.com")],
        actions: ["sns:Publish"],
        resources: [this.topic.topicArn],
        condition: [
          {
            test: "ArnLike",
            variable: "aws:SourceArn",
            values: [bucket.bucketArn],
          },
        ],
      }),
    );

    return {
      arn: this.topic.topicArn,
      type: storage.BucketNotificationDestinationType.TOPIC,
      dependencies: [this.topic],
    };
  }
}

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

    const auditTopic = new notify.Topic(this, "AuditTopic", {
      topicName: "cdktn-bench-media-ingest-audit",
    });

    bucket.addEventNotification(
      storage.EventType.OBJECT_CREATED,
      new storage.targets.FunctionDestination(fn),
      {},
    );

    // BUG: LIFECYCLE_EXPIRATION, not OBJECT_REMOVED -- passes the tier-0
    // whitelist (a member of the six-literal set) but never fires for an
    // ordinary user-initiated delete. The catch this fixture exists to
    // violate.
    bucket.addEventNotification(
      storage.EventType.LIFECYCLE_EXPIRATION,
      new TopicDestination(auditTopic),
      {},
    );
  }
}
TS

bash tests/static_tiers.sh
