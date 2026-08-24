#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the sns-topic-policy-not-scoped-to-bucket catch (the
# SNS-side mirror of lambda-permission-not-scoped-to-bucket): the Lambda
# half is fully correct (storage.targets.FunctionDestination); the SNS
# half's custom destination DOES call `topic.addToResourcePolicy()` (so
# sns-topic-policy-exists, tier 0, passes) but with NO `condition` at all
# -- grants s3.amazonaws.com sns:Publish unconditionally, never scoped to
# this scenario's bucket. Reward must be 0.0 from tier-1
# (sns-topic-policy-allows-s3-publish-tf) alone.
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

// BUG: no `condition` at all -- grants s3.amazonaws.com sns:Publish
// unconditionally, never scoped to this scenario's bucket (or any bucket
// in particular). The catch this fixture exists to violate.
class UnscopedTopicDestination
  implements storage.IBucketNotificationDestination
{
  constructor(private readonly topic: notify.ITopic) {}
  bind(
    _scope: Construct,
    _bucket: storage.IBucket,
  ): storage.BucketNotificationDestinationConfig {
    this.topic.addToResourcePolicy(
      new iam.PolicyStatement({
        principals: [new iam.ServicePrincipal("s3.amazonaws.com")],
        actions: ["sns:Publish"],
        resources: [this.topic.topicArn],
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

    bucket.addEventNotification(
      storage.EventType.OBJECT_REMOVED,
      new UnscopedTopicDestination(auditTopic),
      {},
    );
  }
}
TS

bash tests/static_tiers.sh
