#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts, then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# REWRITTEN (2026-08-06, benchmark-integrity review finding
# "s3-lambda-log-retention / terraconstructs — graph-dependency catch does
# not exercise the L2 mechanism it claims"): this used to build bucket,
# function, permission AND notification entirely at the L1
# (`@cdktn/provider-aws`) level, forced there because
# `compute.Code.fromInline` needed the `hashicorp/archive` Terraform
# provider, which this arm's offline provider mirror did not carry. That
# gap is now closed (arms/terraconstructs/environment/mirror-src/main.tf
# now mirrors `hashicorp/archive` 2.8.0 -- see that fix's own commentary),
# so this scenario now uses the SAME L2 surface its own
# arms.terraconstructs.reason in specs/s3-lambda-log-retention.yaml cites:
# `storage.Bucket` + `storage.Bucket.addEventNotification(EventType.
# OBJECT_CREATED, new storage.targets.FunctionDestination(fn))` (verified
# directly against terraconstructs 0.2.13's own
# lib/aws/storage/bucket-notifications.js: the LAMBDA destination path
# calls `fn.addPermission(...)`, the exact mechanism this scenario's
# s3-lambda-invoke-permission-scoped catch depends on being STRUCTURALLY
# UNREACHABLE-TO-FORGET at this arm's L2 -- see that catch's own
# description) + `compute.LambdaFunction` + `compute.Code.fromInline`
# (which now resolves offline via the mirrored archive provider) +
# `cloudwatch.LogGroup` (unchanged -- this was already L2 before this fix).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import {
  AwsStack,
  AwsStackProps,
  RetentionDays,
  cloudwatch,
  compute,
  storage,
} from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const bucket = new storage.Bucket(this, "UploadBucket", {
      bucketName: "cdktn-bench-s3-lambda-log-retention-upload",
    });

    const fn = new compute.LambdaFunction(this, "Handler", {
      functionName: "cdktn-bench-s3-lambda-log-retention-handler",
      runtime: compute.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: compute.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200 });",
      ),
    });

    new cloudwatch.LogGroup(this, "HandlerLogGroup", {
      logGroupName: `/aws/lambda/${fn.functionName}`,
      retention: RetentionDays.TWO_WEEKS,
    });

    // L2 notification wiring: addEventNotification's LAMBDA destination
    // path (storage.targets.FunctionDestination) calls fn.addPermission()
    // automatically -- the same mechanism aws-cdk-lib's own
    // aws-s3-notifications LambdaDestination uses -- so a correctly-scoped
    // aws_lambda_permission is structurally guaranteed here, never a step
    // a solution author can forget (unlike hand-written HCL, which must
    // author both the notification AND the permission resources
    // separately). This is this scenario's own s3-lambda-invoke-permission-
    // scoped catch's L2-vs-HCL discriminating mechanism, now genuinely
    // exercised on this arm.
    // NOTE: terraconstructs 0.2.13's own BucketNotifications.addNotification
    // (lib/aws/storage/bucket-notifications.js) only registers a target
    // INSIDE its `for (const filter of filters)` loop -- calling
    // addEventNotification with ZERO filter args therefore silently
    // registers NOTHING (no lambda_function entry on the
    // aws_s3_bucket_notification resource, and critically fn.addPermission()
    // -- called from inside FunctionDestination.bind(), itself only invoked
    // from inside that same loop -- never runs either). Verified directly
    // against a real `cdktn synth` + `terraform plan` run. Passing one
    // all-optional-fields filter object (`{}` -- no prefix/suffix, i.e. "no
    // filtering") is the workaround: it makes the loop iterate exactly
    // once, which is what actually triggers the L2 registration (and the
    // addPermission() call) this scenario's catch depends on.
    bucket.addEventNotification(
      storage.EventType.OBJECT_CREATED_PUT,
      new storage.targets.FunctionDestination(fn),
      {},
    );
  }
}
TS

bash tests/static_tiers.sh
