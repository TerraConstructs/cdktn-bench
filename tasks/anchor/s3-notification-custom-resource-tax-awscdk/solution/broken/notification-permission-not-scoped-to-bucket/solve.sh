#!/usr/bin/env bash
# Broken fixture for catch: notification-permission-not-scoped-to-bucket
# (graph-dependency, all arms; REUSED VERBATIM mechanism from
# s3-lambda-log-retention's own s3-lambda-invoke-permission-scoped catch).
# Reproduces exactly ONE mistake relative to solution/solve.sh: the
# hand-wired Lambda permission grants s3.amazonaws.com with NO SourceArn
# at all (account-wide, not scoped to this specific bucket) -- everything
# else (the notification's own target, the event type) stays exactly as
# the reference solution.
#
# Expected: reward 0.0. Caught at tier 1
# (lambda-permission-scoped-to-bucket-cfn's own cfn-guard rule,
# `permission_source_arn_resolves_via_getatt`): SourceArn is entirely
# absent -- 0 resolved nodes. Every tier-0 assert still passes (principal
# is still exactly s3.amazonaws.com; the notification still targets the
# real Processor function).
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

    // MISTAKE: no sourceArn at all -- grants ANY s3.amazonaws.com-
    // principal'd call account-wide, not just this scenario's bucket.
    fn.addPermission("AllowClaimsBucketInvoke", {
      principal: new iam.ServicePrincipal("s3.amazonaws.com"),
    });

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
