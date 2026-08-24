#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-11 (2026-08-23). The awscdk twin of hcl_raw's
# `sns-topic-policy-attached-to-a-different-topic` extra fixture, and the
# falsification of the ATTACHMENT clause of the new
# `sns-topic-policy-allows-s3-publish-cfn` rules in
# oracles/rego-cfn/s3-notification-authoritative-singleton/policy.rego
# (see the sibling `hand-authored-topic-policy-not-scoped-to-bucket`
# fixture's header for the arm-parity finding both close).
#
# The policy DOCUMENT here is correct -- it scopes sns:Publish to this
# stack's own bucket through an aws:SourceArn condition -- so the
# bucket-scoping clause stays silent and this fixture isolates the
# attachment clause. Tier-0 passes (an AWS::SNS::TopicPolicy does exist);
# reward must be 0.0 from tier-1 alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

class BareSnsDestination implements s3.IBucketNotificationDestination {
  constructor(private readonly topic: sns.ITopic) {}
  bind(_scope: Construct, _bucket: s3.IBucket): s3.BucketNotificationDestinationConfig {
    return {
      type: s3.BucketNotificationDestinationType.TOPIC,
      arn: this.topic.topicArn,
    };
  }
}

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const bucket = new s3.Bucket(this, "MediaBucket");

    const fn = new lambda.Function(this, "IngestHandler", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline("exports.handler = async () => {};"),
    });

    const auditTopic = new sns.Topic(this, "AuditTopic");

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(fn),
    );

    bucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED,
      new BareSnsDestination(auditTopic),
    );

    // BUG: correctly-scoped statement, attached to a PASTED literal topic
    // ARN this stack does not create -- so the topic that actually
    // receives the notifications has no policy at all and S3 silently
    // drops every publish.
    new sns.CfnTopicPolicy(this, "AuditTopicPolicy", {
      topics: ["arn:aws:sns:us-east-1:123456789012:some-other-topic"],
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "AllowS3Publish",
            Effect: "Allow",
            Principal: { Service: "s3.amazonaws.com" },
            Action: "sns:Publish",
            Resource: "arn:aws:sns:us-east-1:123456789012:some-other-topic",
            Condition: {
              ArnLike: { "aws:SourceArn": bucket.bucketArn },
            },
          },
        ],
      },
    });
  }
}
TS

bash tests/static_tiers.sh
