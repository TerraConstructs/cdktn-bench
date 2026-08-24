#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md 8.2
# point 8). EXTRA (non-catch-named) negative fixture, required to score
# reward 0.0 by gates/oracle_falsifiability.py.
#
# ROUND-17 REGRESSION FIXTURE -- THE VALUE-LIST LAUNDER, awscdk half.
# `hand-authored-topic-policy-not-scoped-to-bucket` with an aws:SourceArn
# condition ADDED whose value list is
#   [{"Fn::GetAtt": ["MediaBucket...","Arn"]}, "arn:aws:s3:::*"]
#
# Round 16's CFN rule flattened every value of every condition position into
# one name->Type map and accepted on `some` name in it, so this template and
# its correctly-scoped twin BOTH returned `deny []` -- EXECUTED against
# oracles/rego-cfn/.../policy.rego with opa 1.19.0. The TF-shaped arms
# carried the identical defect and it is fixed in the same round; this
# fixture is the cross-arm proof that the closure holds rather than being
# asserted. Its twins on hcl_raw are
# `sns-topic-policy-source-arn-ored-with-a-wildcard`,
# `sns-topic-policy-source-arn-ored-with-a-decoy-bucket`,
# `inline-sns-topic-policy-source-arn-ored-with-a-wildcard` and
# `iam-policy-document-source-arn-ored-with-a-wildcard`.
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

    // BUG: the aws:SourceArn condition's VALUE LIST holds the wired
    // bucket beside a wildcard. Attachment is correct and the condition is
    // present, so every pre-round-17 check passed -- but the values inside
    // one condition position are OR-ed, so any bucket in any account can
    // still publish to the audit topic.
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
            // BUG: the aws:SourceArn condition names the wired bucket AND a
            // wildcard. IAM OR-s the values inside ONE condition position,
            // so this is satisfied by any S3 bucket in any account -- the
            // grant is as unconditioned as the twin fixture's, dressed as
            // scoped.
            Condition: {
              ArnLike: {
                "aws:SourceArn": [bucket.bucketArn, "arn:aws:s3:::*"],
              },
            },
          },
        ],
      },
    });
  }
}
TS

bash tests/static_tiers.sh
