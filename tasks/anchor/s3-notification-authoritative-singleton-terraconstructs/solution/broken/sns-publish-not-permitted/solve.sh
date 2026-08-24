#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the sns-publish-not-permitted catch: the Lambda half
# is fully correct (storage.targets.FunctionDestination, which always
# grants the permission automatically); the SNS half wires the topic
# notification via a custom destination that returns the arn/type/
# dependencies triple WITHOUT ever calling `topic.addToResourcePolicy()`
# -- so the topic exists and is wired into the notification config, but no
# `aws_sns_topic_policy` resource exists anywhere. Tier-0 must fail at
# sns-topic-policy-exists (0 resolved nodes); reward must be 0.0 from
# tier-0 alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import {
  AwsStack,
  AwsStackProps,
  compute,
  notify,
  storage,
} from "terraconstructs/lib/aws";

// BUG: wires the event but never grants S3 publish rights on the topic --
// the catch this fixture exists to violate.
class UnpermittedTopicDestination
  implements storage.IBucketNotificationDestination
{
  constructor(private readonly topic: notify.ITopic) {}
  bind(
    _scope: Construct,
    _bucket: storage.IBucket,
  ): storage.BucketNotificationDestinationConfig {
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

    bucket.addEventNotification(
      storage.EventType.OBJECT_REMOVED,
      new UnpermittedTopicDestination(auditTopic),
      {},
    );
  }
}
TS

bash tests/static_tiers.sh
