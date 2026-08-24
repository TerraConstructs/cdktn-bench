#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# terraconstructs 0.2.13's own `notification-targets/` directory ships
# `FunctionDestination` and `QueueDestination` but NO `TopicDestination`
# (verified directly against the pinned package at authoring time -- see
# this scenario's own spec.yaml header comment and
# arms.terraconstructs.reason). This reference solution hand-authors a
# small `IBucketNotificationDestination` for `notify.Topic`, mirroring
# `QueueDestination.bind()`'s own SQS-side pattern in the SAME package
# (call the target's own resource-policy method, return the arn/type/
# dependencies triple) -- a real, if partial, L2 surface, not an L1
# escape hatch. `bucket.addEventNotification` calls
# `BucketNotifications.addNotification()`
# (lib/aws/storage/bucket-notifications.js), which lazily creates ONE
# `aws_s3_bucket_notification` resource via `createResourceOnce()` no
# matter how many times it is called -- this scenario's own singleton
# catch is structurally unreachable here.
#
# CARRIED OVER FROM s3-lambda-log-retention (same library version, same
# bug): `addNotification` only registers a target INSIDE its `for (const
# filter of filters)` loop -- calling `addEventNotification` with ZERO
# filter args silently registers NOTHING. Both calls below pass one
# all-optional-fields filter object (`{}`) for this reason.
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
// but no TopicDestination (verified directly, see this file's own header
// comment). Mirrors QueueDestination.bind()'s own shape one file over in
// the same package: grant the S3 service principal publish rights,
// scoped to this bucket, then return the arn/type/dependencies triple
// `BucketNotifications.addNotification()` expects.
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

    // ONE bucket, TWO addEventNotification calls -- both accumulate into
    // the SAME authoritative aws_s3_bucket_notification resource
    // (createResourceOnce(), this file's own header comment). The `{}`
    // filter arg is required -- see this file's own header comment.
    bucket.addEventNotification(
      storage.EventType.OBJECT_CREATED,
      new storage.targets.FunctionDestination(fn),
      {},
    );

    bucket.addEventNotification(
      storage.EventType.OBJECT_REMOVED,
      new TopicDestination(auditTopic),
      {},
    );
  }
}
TS

bash tests/static_tiers.sh
