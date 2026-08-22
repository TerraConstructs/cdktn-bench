#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Idiomatic, no escape hatch needed on this arm (unlike awscdk -- see this
# scenario's own arms.terraconstructs.reason / header comment): this
# package's own `storage.Bucket.addEventNotification` ->
# `BucketNotifications.createResourceOnce()` backs the wiring with a
# genuine `aws_s3_bucket_notification` Terraform resource
# (`@cdktn/provider-aws`'s `s3BucketNotification.S3BucketNotification` L1
# binding), re-verified DIRECTLY this spec's own authoring pass by
# extracting and reading the real pinned 0.2.13 tarball -- never a custom
# resource, never an extra Lambda function or IAM role. The L2 notification
# path stays fully idiomatic throughout.
#
# `storage.targets.FunctionDestination.bind()` (same pinned tarball,
# lib/aws/storage/notification-targets/function.js) calls `fn.addPermission
# (...)` with `principal: iam.ServicePrincipal("s3.amazonaws.com")`,
# `sourceArn: bucket.bucketArn` as a side effect -- structurally
# unreachable to forget, exactly like s3-lambda-log-retention's own
# terraconstructs reference solution already exploits for its own
# permission-scoping catch.
#
# NOTE (same quirk s3-lambda-log-retention-terraconstructs's own reference
# solution documents, re-verified present in this exact pinned tarball):
# `BucketNotifications.addNotification` only registers a target INSIDE its
# `for (const filter of filters)` loop, so calling `addEventNotification`
# with ZERO filter args silently registers nothing at all (no notification
# target, and critically no `fn.addPermission()` call either, since that
# call also lives inside the loop via `FunctionDestination.bind()`).
# Passing one all-optional-fields filter object (`{}` -- no prefix/suffix,
# i.e. "no filtering") is the workaround: it makes the loop iterate exactly
# once, which is what actually triggers the L2 registration.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import {
  AwsStack,
  AwsStackProps,
  compute,
  storage,
} from "terraconstructs/lib/aws";

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

    // L2 notification wiring stays idiomatic on this arm (no escape hatch
    // needed -- see this file's own header comment): the LAMBDA
    // destination path calls fn.addPermission() automatically, so a
    // correctly-scoped aws_lambda_permission is structurally guaranteed,
    // never a step a solution author can forget.
    //
    // The lone `{}` filter argument is required -- see this file's own
    // header comment for why zero filter args silently registers nothing.
    bucket.addEventNotification(
      storage.EventType.OBJECT_CREATED_PUT,
      new storage.targets.FunctionDestination(fn),
      {},
    );
  }
}
TS

bash tests/static_tiers.sh
