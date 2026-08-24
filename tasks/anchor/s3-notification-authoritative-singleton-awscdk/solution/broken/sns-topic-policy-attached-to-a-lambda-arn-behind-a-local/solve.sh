#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-12 CROSS-ARM CONTROL (2026-08-23). The awscdk twin of the hcl_raw
# fixture `sns-topic-policy-attached-to-a-lambda-arn-behind-a-local`: the
# hand-authored topic policy is attached to a const-hoisted ARN that holds
# the LAMBDA's ARN, so the audit topic ends up with no resource policy at
# all. It is the arm this pair compares AGAINST -- it scored 0.0 here all
# along (the synthesized template still carries the Fn::GetAtt, and the
# CFN-side attachment clause joins on the referenced logical id's Type),
# while its hcl_raw twin scored 1.0 until round 12 added the CORROBORATION
# clause to `policy.rego`'s `references_this_topic`.
#
# The policy DOCUMENT here is correct -- it scopes sns:Publish to this
# stack's own bucket through an aws:SourceArn condition -- so the
# bucket-scoping clause stays silent and this fixture isolates the
# attachment clause on BOTH arms. Tier-0 passes (an AWS::SNS::TopicPolicy
# does exist); reward must be 0.0 from tier-1 alone.
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

    // BUG: correctly-scoped statement, attached to a const-hoisted ARN
    // that holds the LAMBDA's ARN rather than the audit topic's -- the
    // awscdk twin of the hcl_raw fixture's `arn = local.ingest_fn_arn`.
    // The topic that actually receives the notifications has no policy at
    // all and S3 silently drops every publish.
    const auditTopicArn = fn.functionArn;

    new sns.CfnTopicPolicy(this, "AuditTopicPolicy", {
      topics: [auditTopicArn],
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "AllowS3Publish",
            Effect: "Allow",
            Principal: { Service: "s3.amazonaws.com" },
            Action: "sns:Publish",
            Resource: auditTopicArn,
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
