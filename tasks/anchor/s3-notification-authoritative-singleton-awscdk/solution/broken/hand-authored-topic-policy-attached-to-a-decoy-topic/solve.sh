#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND 13 (2026-08-23) -- SAME-TYPE / WRONG-INSTANCE, topic half, awscdk
# twin. The sibling
# `hand-authored-topic-policy-attached-to-a-different-topic` attaches the
# policy to a PASTED LITERAL topic ARN naming nothing in this template, so
# it is caught by the "names no AWS::SNS::Topic at all" clause. This one
# attaches to a REAL second topic in the same stack, which every type-only
# rule accepted: `Topics: [{"Ref": "DecoyTopic..."}]` does name an
# AWS::SNS::Topic this template creates.
#
# The audit topic -- the one the Custom::S3BucketNotifications resource
# actually publishes to -- is left with no resource policy at all, so S3
# silently drops every delete notification and the compliance half of the
# ticket never works.
#
# Closed by joining on the notification's own
# `NotificationConfiguration.TopicConfigurations[*].TopicArn` logical id,
# the CFN analogue of the plan-address join the TF-shaped arms' policy.rego
# uses. Mirrored on both sides in the same pass so the closure is not
# one-sided (DECISIONS.md Amendment 29 §4).
#
# Everything else is correct. Tier-0 still passes; reward must be 0.0 from
# tier-1 (sns-topic-policy-allows-s3-publish-cfn) alone.
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

    // A second, real topic in this same stack. Nothing is wrong with it
    // existing -- what is wrong is the policy below attaching to it.
    const decoyTopic = new sns.Topic(this, "DecoyTopic");

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(fn),
    );

    bucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED,
      new BareSnsDestination(auditTopic),
    );

    // BUG: a correctly-scoped statement attached to the DECOY topic. It
    // resolves cleanly to an AWS::SNS::Topic this stack creates -- it is
    // just the WRONG ONE, which is exactly why every type-only rule
    // accepted it. The topic that actually receives the notifications has
    // no policy at all and S3 silently drops every publish.
    new sns.CfnTopicPolicy(this, "AuditTopicPolicy", {
      topics: [decoyTopic.topicArn],
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "AllowS3Publish",
            Effect: "Allow",
            Principal: { Service: "s3.amazonaws.com" },
            Action: "sns:Publish",
            Resource: decoyTopic.topicArn,
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
