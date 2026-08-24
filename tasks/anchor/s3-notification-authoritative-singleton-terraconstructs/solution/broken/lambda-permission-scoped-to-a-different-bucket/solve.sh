#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-7 ARM-PARITY FIX (2026-08-22). This is the SECOND spelling of the
# lambda-permission-not-scoped-to-bucket catch: not an OMITTED sourceArn
# (that is the sibling fixture next to this one) but a HARDCODED literal
# one naming a different, unrelated bucket. It ships on all three arms so
# the cross-arm claim can be re-proved by execution rather than asserted:
# the awscdk-side rule used to be a bare `Properties.SourceArn EXISTS`
# presence check, so this exact defect scored 1.0 there and 0.0 on the
# TF-shaped arms. The awscdk rule is now a graph-edge mirror of this arm's
# `references_bucket` and all three arms score 0.0 on this shape. (ROUND
# 10, 2026-08-23: that mirror moved off cfn-guard onto OPA/Rego --
# oracles/rego-cfn/s3-notification-authoritative-singleton/policy.rego --
# because cfn-guard could express neither the `Fn::Sub` spelling of this
# same defect nor a per-permission join.)
#
# Everything else is correct (one authoritative notification resource,
# both event types wired, SNS half fully correct including its topic
# policy). Tier-0 still passes (lambda-permission-principal-is-s3 only
# reads the principal, which is right here); reward must be 0.0 from
# tier-1 (lambda-permission-scoped-to-bucket-tf) alone.
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

    // Deliberately a HARDCODED literal ARN naming a bucket this stack does
    // not create -- the grant is not tied to this stack's bucket at all
    // (the expression references nothing, so it has no graph edge to the
    // aws_s3_bucket resource). The catch this fixture exists to violate.
    new lambdaPermission.LambdaPermission(this, "AllowS3Invoke", {
      provider: this.provider,
      statementId: "AllowS3Invoke",
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: "arn:aws:s3:::some-totally-unrelated-bucket",
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
