#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the lambda-permission-not-scoped-to-bucket catch
# (s3-lambda-log-retention's own scoping catch, reused verbatim): the SNS
# half is fully correct (the reference solution's own hand-authored
# TopicDestination, which always scopes itself); the Lambda half bypasses
# `storage.targets.FunctionDestination` (which always calls
# `fn.addPermission()` -- see this scenario's own spec.yaml catch
# description) with a minimal custom `IBucketNotificationDestination` that
# wires the event WITHOUT ever adding a permission, then separately (and
# deliberately) authors an unscoped `lambdaPermission.LambdaPermission` L1
# resource. Tier-0 still passes (lambda-permission-principal-is-s3 only
# checks the principal); reward must be 0.0 from tier-1
# (lambda-permission-scoped-to-bucket-tf) alone.
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
import { lambdaPermission } from "@cdktn/provider-aws";

// Minimal notification destination that wires the event WITHOUT ever
// adding a Lambda permission -- the permission below is authored
// separately (and deliberately left unscoped), so exactly one
// aws_lambda_permission resource exists in the synthesized plan.
class UnscopedLambdaDestination
  implements storage.IBucketNotificationDestination
{
  constructor(private readonly fn: compute.IFunction) {}
  bind(
    _scope: Construct,
    _bucket: storage.IBucket,
  ): storage.BucketNotificationDestinationConfig {
    return {
      type: storage.BucketNotificationDestinationType.LAMBDA,
      arn: this.fn.functionArn,
    };
  }
}

// Same hand-authored SNS destination as the reference solution -- kept
// correct here since this fixture targets the Lambda-permission scoping
// catch only.
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

    // Deliberately no sourceArn -- grants ANY s3.amazonaws.com-principal'd
    // caller, not just this scenario's bucket. The catch this fixture
    // exists to violate.
    new lambdaPermission.LambdaPermission(this, "AllowS3Invoke", {
      provider: this.provider,
      statementId: "AllowS3Invoke",
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
    });

    bucket.addEventNotification(
      storage.EventType.OBJECT_CREATED,
      new UnscopedLambdaDestination(fn),
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
