#!/usr/bin/env bash
# Reference solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). Writes an
# oracle-CORRECT lib/scenario-stack.ts (verified against a real `cdk synth`
# run -- generator/tests/fixtures/s3-lambda-log-retention/awscdk/lib/
# scenario-stack.ts is byte-identical to it), then runs the same
# tests/static_tiers.sh a real trial's verifier runs. Regenerating this
# scenario will NOT overwrite this file (destructive-safe rule).
#
# Shape verified directly against cdktn-bench/awscdk:dev at authoring time:
# exactly one AWS::Lambda::Permission (Principal s3.amazonaws.com, SourceArn
# = Fn::GetAtt bucket.Arn), one Custom::S3BucketNotifications (Events
# includes s3:ObjectCreated:Put), one AWS::Logs::LogGroup
# (RetentionInDays=14, named /aws/lambda/<function's Ref>).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as logs from "aws-cdk-lib/aws-logs";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const bucket = new s3.Bucket(this, "UploadBucket");

    const fn = new lambda.Function(this, "Handler", {
      runtime: lambda.Runtime.NODEJS_22_X,
      handler: "index.handler",
      code: lambda.Code.fromInline("exports.handler = async () => {};"),
    });

    // Standalone LogGroup, named to match Lambda's own default log group
    // (/aws/lambda/<function-name>) -- no logGroup:/logRetention: prop
    // link needed; Lambda writes to whichever log group already exists
    // under that name. Retention picked from the valid RetentionDays enum
    // nearest the instruction's "10 days" (7 or 14; see the spec's
    // log-retention-not-a-valid-enum-value catch for why no exact 10
    // exists).
    new logs.LogGroup(this, "HandlerLogGroup", {
      logGroupName: `/aws/lambda/${fn.functionName}`,
      retention: logs.RetentionDays.TWO_WEEKS,
    });

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED_PUT,
      new s3n.LambdaDestination(fn),
    );
  }
}
TS

bash tests/static_tiers.sh
