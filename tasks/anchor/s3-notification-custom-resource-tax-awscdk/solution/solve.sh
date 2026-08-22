#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# THE ESCAPE HATCH this scenario exists to measure: the idiomatic, L2
# `bucket.addEventNotification(EventType.OBJECT_CREATED_PUT, new
# s3n.LambdaDestination(fn))` -- what s3-lambda-log-retention.yaml's own
# awscdk reference solution uses -- lazily provisions aws-cdk-lib's
# stack-wide `Custom::S3BucketNotifications` handler function plus its
# execution role (aws-s3/lib/notifications-resource/
# notifications-resource.ts, re-verified against the pinned 2.263.0 clone
# at this spec's own authoring time). This scenario's own platform
# constraint ("no helpers, no deployment-time functions") forbids exactly
# that, so this solution bypasses the L2's notification path entirely and
# sets `notificationConfiguration` directly on the bucket's own underlying
# `CfnBucket` (`bucket.node.defaultChild as s3.CfnBucket`) -- the L1
# escape hatch. Because `addEventNotification` is never called, the
# custom-resource singleton is never lazily created at all: zero extra
# functions, zero extra roles, zero Custom::* resources.
#
# Consequence of bypassing the L2: `s3n.LambdaDestination`'s own
# `fn.addPermission(...)` side effect (the mechanism
# s3-lambda-log-retention's own catch depends on) never runs either --
# this solution wires the resource-based Lambda permission by hand,
# scoped to this specific bucket's ARN.
#
# Property shape verified directly against the live CloudFormation
# Template Reference (docs.aws.amazon.com/AWSCloudFormation/latest/
# TemplateReference/aws-properties-s3-bucket-lambdaconfiguration.html,
# read this authoring pass): AWS::S3::Bucket.NotificationConfiguration.
# LambdaConfigurations[].{Event, Function} -- singular "Event", NOT the
# custom resource's own S3-API-mirroring "Events"/plural shape (this
# scenario's own header comment, "THE SHARP EDGE INSIDE THE SHARP EDGE").
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const bucket = new s3.Bucket(this, "ClaimsBucket");

    const fn = new lambda.Function(this, "Processor", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline("exports.handler = async () => {};"),
    });

    // Hand-wired resource-based permission -- the L2's own
    // s3n.LambdaDestination would do this automatically, but calling it
    // would also provision the forbidden Custom::S3BucketNotifications
    // handler as a side effect, so this bypasses that API entirely (see
    // this file's own header comment).
    fn.addPermission("AllowClaimsBucketInvoke", {
      principal: new iam.ServicePrincipal("s3.amazonaws.com"),
      sourceArn: bucket.bucketArn,
    });

    // L1 escape hatch: set NotificationConfiguration directly on the
    // bucket's own underlying CfnBucket instead of calling the L2's
    // addEventNotification (which would lazily provision the forbidden
    // custom-resource handler function -- see this file's own header
    // comment for the full mechanism).
    const cfnBucket = bucket.node.defaultChild as s3.CfnBucket;
    cfnBucket.notificationConfiguration = {
      lambdaConfigurations: [
        {
          event: "s3:ObjectCreated:Put",
          function: fn.functionArn,
        },
      ],
    };
  }
}
TS

bash tests/static_tiers.sh
