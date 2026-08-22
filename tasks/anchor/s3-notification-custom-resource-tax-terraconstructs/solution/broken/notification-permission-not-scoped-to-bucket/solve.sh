#!/usr/bin/env bash
# Broken fixture for catch: notification-permission-not-scoped-to-bucket
# (graph-dependency, all arms; REUSED VERBATIM mechanism from
# s3-lambda-log-retention's own s3-lambda-invoke-permission-scoped catch).
# Reproduces exactly ONE mistake relative to solution/solve.sh: bypasses
# the L2's own `addEventNotification` (whose `FunctionDestination.bind()`
# always scopes the permission correctly, structurally unreachable to
# mis-scope through ordinary use -- see solution/solve.sh's own header
# comment) and instead constructs the notification AND permission by
# hand, with the permission's sourceArn a hardcoded, unrelated ARN literal
# -- everything else (the notification's own target, the event type)
# stays exactly as the reference solution.
#
# Expected: reward 0.0. Caught at tier 1 (Rego's
# `lambda-permission-scoped-to-bucket-tf`): the permission's `source_arn`
# expression has only a `.constant_value`, no `.references` entry matching
# `^aws_s3_bucket\.`. Every tier-0 assert still passes.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import {
  AwsStack,
  AwsStackProps,
  compute,
  iam,
  storage,
} from "terraconstructs/lib/aws";
import { s3BucketNotification } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new storage.Bucket(this, "ClaimsBucket", {
      bucketName: "cdktn-bench-s3-notification-custom-resource-tax-claims",
    });

    const fn = new compute.LambdaFunction(this, "Processor", {
      functionName: "cdktn-bench-s3-notification-custom-resource-tax-processor",
      runtime: compute.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200 });",
      ),
    });

    // MISTAKE: hardcoded, unrelated ARN literal -- not scoped to
    // `bucket`, the bucket this configuration actually creates. Bypasses
    // the L2's own FunctionDestination (which cannot produce this
    // mistake -- see this file's own header comment).
    fn.addPermission("AllowClaimsBucketInvoke", {
      principal: new iam.ServicePrincipal("s3.amazonaws.com"),
      sourceArn: "arn:aws:s3:::some-totally-unrelated-bucket",
    });

    new s3BucketNotification.S3BucketNotification(this, "Notification", {
      bucket: bucket.bucketName,
      lambdaFunction: [
        {
          lambdaFunctionArn: fn.functionArn,
          events: ["s3:ObjectCreated:Put"],
        },
      ],
    });
  }
}
TS

bash tests/static_tiers.sh
