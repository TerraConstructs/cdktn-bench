#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md 8.2
# point 8). EXTRA (non-catch-named) negative fixture, required to score
# reward 0.0 by gates/oracle_falsifiability.py.
#
# ROUND-16 REGRESSION FIXTURE -- THE `Sid` LAUNDER, awscdk half. This is
# `hand-authored-topic-policy-not-scoped-to-bucket` with ONE line changed:
# the statement's `Sid` interpolates `bucket.bucketArn`, which synthesizes
# to an `Fn::Join` naming the bucket's logical id inside the `Sid` string.
#
# The grant is UNCHANGED and still unconditioned: `s3.amazonaws.com` gets
# `sns:Publish` on the audit topic with NO `aws:SourceArn` condition, so
# any S3 bucket in any account can publish to it.
#
# Until round 16 `policy_document_names_a_bucket` ran `expr_names` over the
# WHOLE `Properties.PolicyDocument` and accepted if ANY name it found was
# the wired bucket -- no position requirement at all, the CloudFormation
# spelling of the same defect the TF-shaped arms had. On the TF side the
# equivalent one-line edit was EXECUTED from REWARD 0.0 to REWARD 1.0. The
# CFN rule is now POSITIONAL (every statement granting s3.amazonaws.com
# sns:Publish must carry an aws:SourceArn condition naming a wired
# bucket), and this fixture is the cross-arm proof that the closure holds
# rather than being asserted. Its twins on hcl_raw are
# `sns-topic-policy-bucket-named-only-in-the-sid` and
# `inline-sns-topic-policy-bucket-named-only-in-the-sid`.
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
            // THE LAUNDER: the bucket is named HERE, in the Sid, and
            // nowhere else. It scopes nothing.
            Sid: `AllowS3Publish${bucket.bucketArn}`,
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
