#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# `bucket.addEventNotification` (aws-s3/lib/bucket.ts's own
# `withNotifications()`, re-verified directly against the pinned
# aws-cdk-lib 2.263.0 at this scenario's authoring time) lazily creates
# ONE `BucketNotifications` construct per bucket regardless of how many
# times it is called -- this scenario's own singleton catch is
# structurally unreachable here. `s3n.LambdaDestination` always scopes the
# Lambda permission to this exact bucket
# (aws-s3-notifications/lib/lambda.ts); `s3n.SnsDestination` always
# authors a correctly-scoped topic-publish statement
# (aws-s3-notifications/lib/sns.ts, `addToResourcePolicy` called
# unconditionally) -- both catches this scenario's own tier-1/existence
# checks target are equally unreachable through this idiomatic API.
#
# ROUND-11 NOTE (2026-08-23): "unreachable through this idiomatic API" is
# a statement about ORDINARY USE, not about what is graded. Since round 11
# the awscdk tier-1 DOES grade SNS topic-policy scoping and attachment
# (`sns-topic-policy-allows-s3-publish-cfn`, oracles/rego-cfn/.../
# policy.rego), because an adversarial verifier proved the defect IS
# expressible here -- bind the topic through a destination that authors no
# policy, then hand-author an unconditioned `AWS::SNS::TopicPolicy` -- and
# scored reward 1.0 doing it. This file is unchanged: the statement the L2
# authors for it passes both new clauses (its `aws:SourceArn` condition is
# an `Fn::GetAtt` on the bucket, its `Topics` a `Ref` to the topic), which
# `make falsifiability` re-proves on every run.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

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

    // ONE bucket, TWO addEventNotification calls -- both accumulate into
    // the SAME authoritative Custom::S3BucketNotifications resource
    // (BucketNotifications.createResourceOnce(), this file's own header
    // comment).
    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(fn),
    );

    bucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED,
      new s3n.SnsDestination(auditTopic),
    );
  }
}
TS

bash tests/static_tiers.sh
