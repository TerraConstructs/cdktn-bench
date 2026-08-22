#!/usr/bin/env bash
# Broken fixture for catch: notification-targets-the-wrong-function
# (graph-dependency, all arms). Reproduces exactly ONE mistake relative to
# solution/solve.sh: the notification's Function is a hardcoded, unrelated
# ARN literal instead of a reference to the Processor function this
# configuration creates -- everything else (the permission, its scoping,
# the event type) stays exactly as the reference solution.
#
# Expected: reward 0.0. Caught at tier 1
# (notification-targets-created-function-cfn's own cfn-guard rule,
# `notification_targets_created_function`): the LambdaConfigurations
# entry's Function has no 'Fn::GetAtt' key at all -- it is a plain string.
# Every tier-0 assert still passes (a notification exists; its event type
# is s3:ObjectCreated:Put; exactly one Lambda function exists; the
# permission's principal is s3.amazonaws.com and its SourceArn is still
# correctly an Fn::GetAtt to the bucket) -- this fixture reproduces only
# the ONE mistake this catch targets.
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

    fn.addPermission("AllowClaimsBucketInvoke", {
      principal: new iam.ServicePrincipal("s3.amazonaws.com"),
      sourceArn: bucket.bucketArn,
    });

    const cfnBucket = bucket.node.defaultChild as s3.CfnBucket;
    cfnBucket.notificationConfiguration = {
      lambdaConfigurations: [
        {
          event: "s3:ObjectCreated:Put",
          // MISTAKE: hardcoded, unrelated ARN literal -- not a reference
          // to `fn`, the function this configuration actually creates.
          function:
            "arn:aws:lambda:us-east-1:123456789012:function:some-other-function",
        },
      ],
    };
  }
}
TS

bash tests/static_tiers.sh
