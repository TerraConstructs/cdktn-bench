#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-10 CARDINALITY FIX (2026-08-23; DECISIONS.md Amendment 29 §4
# RULING 2). The product half is wired the fully idiomatic way
# (`s3n.LambdaDestination`, which authors a correctly-scoped permission by
# itself), and then a SECOND `AWS::Lambda::Permission` is added by hand
# whose SourceArn is the AUDIT TOPIC's ARN -- an ordinary copy/paste
# defect in a stack that has two ARNs in scope, and one that leaves a
# standing `lambda:InvokeFunction` grant nothing in this template
# constrains to the bucket.
#
# This is the shape cfn-guard structurally could not catch. Its `let`
# bindings flatten SourceArn targets across ALL s3-principal'd permissions
# into one set, so the round-7 rules asked "is SOME permission's SourceArn
# a bucket?" and this template answers yes (the correct permission is still
# there). Verified by execution at round 10 against the retired
# policy.guard: cfn-guard PASS on this exact synthesized template, while
# the hcl_raw counterpart (a correct `aws_lambda_permission` plus a second
# one with `source_arn = aws_sns_topic.audit.arn`) is DENIED by
# policy.rego, which quantifies per plan address. The tier-1 POLICIES
# disagreed across arms on the same defect; the port makes them agree.
#
# HONEST SCOPE NOTE, because overclaiming here would be its own defect.
# Unlike the `Fn::Sub` sibling fixture, this shape was NOT a reward-level
# arm-parity break: tier-0's `lambda-permission-principal-is-s3` uses op
# `eq`, which requires EXACTLY ONE resolved node, so ANY artifact carrying
# two Lambda-permission resources already failed tier-0 -- identically on
# awscdk and on hcl_raw, for reward 0.0 on both. What was broken was the
# tier-1 RULE, which is what Amendment 29 §4 RULING 2 governs and what a
# future change to that tier-0 assert would expose. This fixture exists so
# the per-resource quantification stays falsified: it fails tier-0 AND
# tier-1 here (`tier1_status=FAIL`, denying the AllowS3InvokeLegacy
# permission by logical id), and the tier-1 half is recorded in
# policy.rego's own ROUND-10 verification list. Reward must be 0.0.
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

    // Correct: LambdaDestination scopes its own permission to this bucket.
    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new s3n.LambdaDestination(fn),
    );

    bucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED,
      new s3n.SnsDestination(auditTopic),
    );

    // BUG: a SECOND s3.amazonaws.com invoke grant, scoped to the audit
    // TOPIC's ARN instead of the bucket's. Nothing in this template ties
    // it to the bucket, and an aws:SourceArn naming an SNS topic never
    // matches an S3 invocation -- so the grant is effectively unbounded
    // for its stated purpose while still passing any "at least one
    // permission is scoped to the bucket" check.
    new lambda.CfnPermission(this, "AllowS3InvokeLegacy", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: auditTopic.topicArn,
    });
  }
}
TS

bash tests/static_tiers.sh
