#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-11 ARM-PARITY FIX (2026-08-23). The awscdk expression of the
# `sns-topic-policy-not-scoped-to-bucket` catch. Until round 11 nothing on
# this arm graded SNS topic-policy scoping at ANY tier -- the rego-cfn
# bundle said so in its own header ("NO SNS RULE LIVES HERE"), on the
# argument that `s3n.SnsDestination.bind()` always authors a
# correctly-scoped statement so the defect has no ordinary-use path here.
# An adversarial verifier PROVED that argument does not cover the artifact
# below: bind the topic through a destination that authors NO policy, add
# the topic policy by hand with no `aws:SourceArn` condition at all, and
# the result is functionally the exact defect the TF arms grade -- any
# bucket in any account may publish to the audit topic -- while scoring
# reward 1.0 (all 7 tier-0 asserts PASS, `sns-topic-policy-exists-cfn`
# included, and tier-1 emitted no deny).
#
# CLOSED at round 11 by the new `sns-topic-policy-allows-s3-publish-cfn`
# rules in oracles/rego-cfn/s3-notification-authoritative-singleton/
# policy.rego, the CFN mirror of `sns-topic-policy-allows-s3-publish-tf`.
# This fixture is the falsification of its BUCKET-SCOPING clause.
#
# The Lambda half is fully correct (idiomatic `s3n.LambdaDestination`, so
# the invoke permission is authored and scoped by the L2), and the topic
# policy IS attached to this stack's own topic -- so this fixture isolates
# the one clause it exists to violate. Tier-0 passes; reward must be 0.0
# from tier-1 alone.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

// Minimal topic destination that wires the event WITHOUT calling
// `topic.addToResourcePolicy(...)` -- the same shape of escape hatch the
// Lambda-side fixtures on this arm already use, so the topic policy below
// is the ONLY one in the synthesized template.
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

    // BUG: grants sns:Publish to the S3 service with NO aws:SourceArn
    // condition -- nothing scopes it to this stack's bucket, so any
    // bucket in any account can publish to the audit topic. Attachment is
    // correct (Topics names this stack's own topic); only the scoping is
    // missing.
    new sns.CfnTopicPolicy(this, "AuditTopicPolicy", {
      topics: [auditTopic.topicArn],
      policyDocument: {
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "AllowS3Publish",
            Effect: "Allow",
            Principal: { Service: "s3.amazonaws.com" },
            Action: "sns:Publish",
            Resource: auditTopic.topicArn,
          },
        ],
      },
    });
  }
}
TS

bash tests/static_tiers.sh
