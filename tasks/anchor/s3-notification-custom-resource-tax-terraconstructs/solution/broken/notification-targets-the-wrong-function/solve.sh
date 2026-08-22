#!/usr/bin/env bash
# Broken fixture for catch: notification-targets-the-wrong-function
# (graph-dependency, all arms). Reproduces exactly ONE mistake relative to
# solution/solve.sh: the notification's lambda_function_arn is a
# hardcoded, unrelated ARN literal instead of a reference to the Processor
# function this configuration creates -- everything else (the permission,
# its scoping, the event type) stays exactly as the reference solution.
#
# Bypasses the L2's own `addEventNotification` (which, bound to `fn` via
# `storage.targets.FunctionDestination`, could only ever reference the
# function it was actually given -- there is no L2 call shape that
# produces this mistake) and instead constructs the underlying
# `@cdktn/provider-aws` `s3BucketNotification.S3BucketNotification` L1
# resource directly -- the exact resource the L2 itself wraps (re-verified
# against the pinned 0.2.13 tarball, this scenario's own
# arms.terraconstructs.reason). The permission is still hand-wired
# correctly (mirroring what `FunctionDestination.bind()` would have done),
# so only the ONE mistake this catch targets is reproduced.
#
# Expected: reward 0.0. Caught at tier 1 (Rego's
# `notification-targets-created-function-tf`): the notification's
# `lambda_function[0].lambda_function_arn` expression has only a
# `.constant_value`, no `.references` entry matching
# `^aws_lambda_function\.`. Every tier-0 assert still passes.
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

    // Hand-wired, correctly-scoped permission -- mirrors exactly what
    // storage.targets.FunctionDestination.bind() does internally
    // (lib/aws/storage/notification-targets/function.js, re-verified
    // against the pinned 0.2.13 tarball). Left untouched by this fixture's
    // one mistake below.
    fn.addPermission("AllowClaimsBucketInvoke", {
      principal: new iam.ServicePrincipal("s3.amazonaws.com"),
      sourceArn: bucket.bucketArn,
    });

    // MISTAKE, constructed at the L1 directly (bypassing the L2's
    // addEventNotification, which has no call shape that could produce
    // this): hardcoded, unrelated ARN literal -- not a reference to `fn`,
    // the function this configuration actually creates.
    new s3BucketNotification.S3BucketNotification(this, "Notification", {
      bucket: bucket.bucketName,
      lambdaFunction: [
        {
          lambdaFunctionArn:
            "arn:aws:lambda:us-east-1:123456789012:function:some-other-function",
          events: ["s3:ObjectCreated:Put"],
        },
      ],
    });
  }
}
TS

bash tests/static_tiers.sh
