#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). EXTRA (non-catch-named) negative fixture, discovered and
# required to score reward 0.0 by gates/oracle_falsifiability.py's own
# "extra broken/ fixture" loop.
#
# ROUND-12 CROSS-ARM CONTROL (2026-08-23). The awscdk twin of the hcl_raw
# fixture of the same name: the invoke permission is scoped to the LAMBDA's
# OWN ARN, reached through the same DRY const-hoist an author would
# naturally write on this arm. It is the arm this pair compares AGAINST --
# it scored 0.0 here all along, while its hcl_raw twin scored 1.0 until
# round 12 made that arm's `local.`/`var.` acceptance POSITIVE (the plan's
# own `relevant_attributes` must show the configuration depending on some
# aws_s3_bucket's `arn` at all). Shipping both keeps the agreement
# falsified by `make falsifiability` on every run instead of asserted once
# in a header.
#
# On this arm the const disappears at synth time and the template still
# carries `SourceArn: {"Fn::GetAtt": [<IngestHandler logical id>, "Arn"]}`,
# so oracles/rego-cfn/s3-notification-authoritative-singleton/policy.rego
# resolves it to an AWS::Lambda::Function and denies -- quoting that
# logical id and its Type rather than asserting a diagnosis (Amendment 29
# §6 RULING 3).
#
# ONE deny fires here where the hcl_raw twin emits two: on that arm the
# same local also feeds the hand-written topic policy's aws:SourceArn
# condition, while here `s3n.SnsDestination` authors that condition itself
# from the bucket. Same verdict (0.0, isolated at tier 1) for the same
# defect, which is what this pair exists to show.
#
# Everything else is correct. Tier-0 still passes
# (lambda-permission-principal-is-s3 reads only the principal, which is
# right here); reward must be 0.0 from tier-1
# (lambda-permission-scoped-to-bucket-cfn) alone.
#
# ROUND-13 CORRECTION (2026-08-23). The header above describes the ROUND-12
# mechanism, and that mechanism no longer exists. `config_reaches_arn_of`,
# `relevant_attributes`-based positive evidence, `slot_is_plan_time_unknown`,
# `bucket_denoting_indirections`, `topic_target_indirections` and
# `deepest_refs` were all DELETED from
# oracles/rego/s3-notification-authoritative-singleton/policy.rego. The
# hcl_raw arm now parses the agent's own `.tf` with `hcl2json` and merges it
# into the oracle input (`oracle.hcl_traversal`, specs/SCHEMA.md sect 4.6),
# so a `local.` symbol is RESOLVED to the resource attribute it names rather
# than reasoned about circumstantially. THIS FIXTURE STILL SCORES 0.0 and
# still isolates at tier 1 -- what changed is the reason quoted in the deny
# message, which now states the referent. Read policy.rego's ROUND 13 block
# for what replaced the machinery this header names.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as s3 from "aws-cdk-lib/aws-s3";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as sns from "aws-cdk-lib/aws-sns";
import * as s3n from "aws-cdk-lib/aws-s3-notifications";

// Minimal notification destination that wires the event WITHOUT ever
// adding a Lambda permission -- the permission below is authored
// separately (and deliberately mis-scoped), so exactly one
// AWS::Lambda::Permission resource exists in the synthesized template.
class UnscopedLambdaDestination implements s3.IBucketNotificationDestination {
  constructor(private readonly fn: lambda.IFunction) {}
  bind(_scope: Construct, _bucket: s3.IBucket): s3.BucketNotificationDestinationConfig {
    return {
      type: s3.BucketNotificationDestinationType.LAMBDA,
      arn: this.fn.functionArn,
    };
  }
}

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

    // BUG: the hoist reaches the LAMBDA's own ARN, not the bucket's --
    // the awscdk twin of the hcl_raw fixture's `locals { media_bucket_arn =
    // aws_lambda_function.ingest.arn }`. The grant is scoped to the
    // function it is granting access to, which no S3 event ever matches.
    const mediaBucketArn = fn.functionArn;
    const auditTopicArn = auditTopic.topicArn;

    new lambda.CfnPermission(this, "AllowS3Invoke", {
      action: "lambda:InvokeFunction",
      functionName: fn.functionName,
      principal: "s3.amazonaws.com",
      sourceArn: mediaBucketArn,
    });

    // `auditTopicArn` is referenced so the hoist is real code, not an
    // unused binding the compiler would flag.
    new cdk.CfnOutput(this, "AuditTopicArn", { value: auditTopicArn });

    bucket.addEventNotification(
      s3.EventType.OBJECT_CREATED,
      new UnscopedLambdaDestination(fn),
    );

    bucket.addEventNotification(
      s3.EventType.OBJECT_REMOVED,
      new s3n.SnsDestination(auditTopic),
    );
  }
}
TS

bash tests/static_tiers.sh
