#!/usr/bin/env bash
# NEGATIVE FIXTURE -- HAND-AUTHORED (SCHEMA.md §8.2 point 8) for the catch
# `log-delivery-grant-not-migrated`, whose predicted_tier_caught on THIS arm is
# "1" (via `terraconstructs_override`) -- "0" on awscdk and "live" on hcl_raw.
# Three arms, three tiers, all three measured.
#
# THE MISTAKE, identical in substance on every arm: ACLs are turned off on the
# access-logs bucket exactly as the ticket asks, the logging configuration is
# left exactly where it was, and a bucket policy IS written -- it just carries
# the wrong grant. `delivery.logs.amazonaws.com` is the delivery principal
# CloudWatch Logs / VPC flow logs / Firehose use; S3 server access logging uses
# `logging.s3.amazonaws.com`, and nothing anywhere in the workspace says so.
# terraconstructs 0.2.13's `storage.Bucket` models neither ownership controls
# nor server access logging, so unlike aws-cdk-lib's `serverAccessLogsBucket`
# there is no L2 here that would have written the right statement for the agent.
#
# WHY THIS ARM IS TIER 1 WHERE hcl_raw IS live -- MEASURED, 2026-08-26, and
# genuinely surprising. The two arms express the identical logical
# configuration, and the hcl_raw one loses the policy document from the graded
# artifact completely: `policy = jsonencode({...})` interpolating the bucket's
# ARN is an HCL EXPRESSION, so `terraform show -json` records
# `expressions.policy` as `{"references": [...]}` and nothing else. cdktn does
# not emit HCL -- it emits `cdk.tf.json`, Terraform's JSON syntax, where the
# same document is a STRING; and terraform's configuration representation
# records that string as `expressions.policy.constant_value` VERBATIM, `${...}`
# markers and all. So the principal survives into the artifact on this arm and
# not on the other.
#
# WHAT THIS FIXTURE PROVES BEFORE IT LETS THE TIER CLAIM STAND. The probe below
# is the MIRROR of the hcl_raw fixture's live-only marker: it requires the
# graded artifact to CARRY the document, and to carry the wrong principal and
# not the right one. If a future cdktn or terraform release stops emitting
# `constant_value` for a JSON-syntax string, this fixture exits non-zero and
# `make falsifiability` turns red -- rather than the fixture quietly falling
# through to a tier that can no longer see it while the spec keeps claiming
# `terraconstructs_override: "1"`.
#
# Expected verdict: reward 0.0, caught at tier 1 by
# oracles/rego/s3-acl-vs-object-ownership-log-delivery/policy.rego's
# `readable_document` rule (verified directly against this exact artifact at
# authoring time: `deny` is EMPTY for the reference solution's document and
# non-empty for this one, on the same policy file that stays SILENT for both
# hcl_raw shapes).
set -euo pipefail

STACK_DIR="cdktf.out/stacks/application-storage"
REFERENCE_PRINCIPAL="logging.s3.amazonaws.com"
FIXTURE_PRINCIPAL="delivery.logs.amazonaws.com"

mkdir -p lib
cat > lib/scenario-stack.ts <<TS
import {
  s3BucketLogging,
  s3BucketOwnershipControls,
  s3BucketPolicy,
} from "@cdktn/provider-aws";
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { Bucket } from "terraconstructs/lib/aws/storage";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const accessLogs = new Bucket(this, "AccessLogs", {
      bucketName: "cdktn-bench-application-storage-access-logs",
      forceDestroy: true,
    });

    new s3BucketOwnershipControls.S3BucketOwnershipControls(
      this,
      "AccessLogsOwnership",
      {
        bucket: accessLogs.bucketName,
        rule: { objectOwnership: "BucketOwnerEnforced" },
      },
    );

    const appData = new Bucket(this, "AppData", {
      bucketName: "cdktn-bench-application-storage-app-data",
      forceDestroy: true,
    });

    new s3BucketPolicy.S3BucketPolicy(this, "AccessLogsPolicy", {
      bucket: accessLogs.bucketName,
      policy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Sid: "S3ServerAccessLogsPolicy",
            Effect: "Allow",
            Principal: { Service: "${FIXTURE_PRINCIPAL}" },
            Action: ["s3:PutObject"],
            Resource: \`\${accessLogs.bucketArn}/app-data/*\`,
            Condition: {
              ArnLike: { "aws:SourceArn": appData.bucketArn },
            },
          },
        ],
      }),
    });

    new s3BucketLogging.S3BucketLoggingA(this, "AppDataLogging", {
      bucket: appData.bucketName,
      targetBucket: accessLogs.bucketName,
      targetPrefix: "app-data/",
    });
  }
}
TS

# --- the tier probe --------------------------------------------------------
npx tsc -p tsconfig.json >/dev/null
npx cdktn synth >/dev/null 2>&1
PROBE_ARTIFACT="$(
  cd "$STACK_DIR" \
    && terraform init -input=false >/dev/null \
    && terraform plan -input=false -refresh=false -out=probe.tfplan >/dev/null \
    && terraform show -json probe.tfplan
)"
rm -f "$STACK_DIR/probe.tfplan"

POLICY_DOC="$(
  printf '%s' "$PROBE_ARTIFACT" \
    | jq -r '[.configuration.root_module.resources[]
              | select(.type == "aws_s3_bucket_policy")
              | .expressions.policy.constant_value // empty] | join("\n")'
)"

echo "== tier probe: does this arm's GRADED artifact carry the policy document? =="
if [ -z "$POLICY_DOC" ]; then
  echo "TIER PROBE FAILED: no aws_s3_bucket_policy in the graded artifact carries" >&2
  echo "an 'expressions.policy.constant_value'. This arm's tier for" >&2
  echo "log-delivery-grant-not-migrated is declared as \"1\"" >&2
  echo "(terraconstructs_override) precisely BECAUSE cdktn's JSON-syntax output" >&2
  echo "puts the whole document there. If that is no longer true, the Rego rule" >&2
  echo "cannot see this mistake and the catch must be re-tiered to \"live\" on" >&2
  echo "this arm, with the hcl_raw fixture's marker-proof shape." >&2
  exit 1
fi
case "$POLICY_DOC" in
  *"$FIXTURE_PRINCIPAL"*) ;;
  *)
    echo "TIER PROBE FAILED: the readable policy document does not contain the" >&2
    echo "wrong principal this fixture is supposed to plant ($FIXTURE_PRINCIPAL)." >&2
    echo "The fixture is not reproducing its own mistake." >&2
    exit 1
    ;;
esac
case "$POLICY_DOC" in
  *"$REFERENCE_PRINCIPAL"*)
    echo "TIER PROBE FAILED: the readable policy document DOES contain" >&2
    echo "$REFERENCE_PRINCIPAL -- this fixture would be graded as correct." >&2
    exit 1
    ;;
esac
echo "  the graded artifact carries expressions.policy.constant_value verbatim,"
echo "  it names $FIXTURE_PRINCIPAL and it does not name $REFERENCE_PRINCIPAL."
echo "  The tier-1 Rego rule can therefore see this mistake on this arm -- which"
echo "  is exactly what the spec's terraconstructs_override claims, and exactly"
echo "  what the hcl_raw arm's own fixture proves is NOT true there."

exec bash tests/static_tiers.sh
