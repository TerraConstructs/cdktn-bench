#!/usr/bin/env bash
# Deliberately-BAD reference solution -- HAND-AUTHORED (SCHEMA.md §8.2
# point 8). Violates the s3-readonly-missing-on-one-role catch: the AWS
# managed policy AmazonS3ReadOnlyAccess is attached to `batch-runner`
# only -- `reportWriter.addManagedPolicy(s3ReadOnly)` is never called, so
# report-writer has no read access to the reporting data in S3 at all,
# which the ticket's second paragraph asks for on BOTH roles. Everything
# else is byte-identical to solution/solve.sh: both roles exist with the
# right trust principals, the team-defined metrics policy is still
# attached to both, and no exclusive-ownership surface is used anywhere.
# Every tier-0 assert therefore passes exactly as it does for the
# reference solution; reward must be 0.0 from tier-1 alone
# (policy.rego's AmazonS3ReadOnlyAccess deny rule, whose per-role set
# difference over role plan ADDRESSES REPAIR PASS 7 introduced -- before
# that tightening this fixture scored reward 1.0, which is the defect it
# exists to keep fixed; see specs/iam-managed-policy-exclusive-vs-
# attachment.yaml's header comment, defect 13).
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, iam } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const batchRunner = new iam.Role(this, "BatchRunnerRole", {
      roleName: "batch-runner",
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });

    const reportWriter = new iam.Role(this, "ReportWriterRole", {
      roleName: "report-writer",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
    });

    // AWS-managed policy: an imported reference (a literal ARN string,
    // never a resource this stack creates). This arm's own
    // fromAwsManagedPolicyName is a 3-arg static (scope, id, name),
    // unlike aws-cdk-lib's newer 1-arg form -- verified against the
    // installed package's own .js, see this file's own header comment.
    const s3ReadOnly = iam.ManagedPolicy.fromAwsManagedPolicyName(
      this,
      "S3ReadOnly",
      "AmazonS3ReadOnlyAccess",
    );
    // THE MISTAKE: only batch-runner gets it. The matching
    // reportWriter.addManagedPolicy(s3ReadOnly) call the reference
    // solution makes is absent, so report-writer never gets the read
    // access the ticket asks for on both roles.
    batchRunner.addManagedPolicy(s3ReadOnly);

    // Team-defined policy: a real aws_iam_policy resource, attached
    // additively (aws_iam_role_policy_attachment) to BOTH roles.
    // cloudwatch:PutMetricData has no resource-level ARN in IAM's policy
    // grammar, so resources: ["*"] is the correct, necessary form for
    // this specific action, not a "scoped, not broader" mistake.
    const teamMetricsPolicy = new iam.ManagedPolicy(this, "TeamMetricsPolicy", {
      statements: [
        new iam.PolicyStatement({
          actions: ["cloudwatch:PutMetricData"],
          resources: ["*"],
        }),
      ],
    });
    batchRunner.addManagedPolicy(teamMetricsPolicy);
    reportWriter.addManagedPolicy(teamMetricsPolicy);
  }
}
TS

bash tests/static_tiers.sh
