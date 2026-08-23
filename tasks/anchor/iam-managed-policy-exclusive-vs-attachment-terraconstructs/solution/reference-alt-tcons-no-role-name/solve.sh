#!/usr/bin/env bash
# Reference-ALT solution -- HAND-AUTHORED (SCHEMA.md §8.2 point 8). NOT a
# negative fixture and NOT a declared catch: a manually re-runnable proof
# that a DIFFERENT, equally correct authoring decision also scores 1.0.
#
# WHAT IT PROVES (binding operator ruling 1, 2026-08-22: a physical
# resource NAME is never load-bearing in this oracle -- identity is
# existence + type + properties, keyed on the plan ADDRESS here and the
# template LOGICAL ID on awscdk): this is solution/solve.sh with the two
# `roleName:` lines DELETED. On THIS arm that is not an exotic spelling
# but the DEFAULT one: terraconstructs 0.2.13 lib/aws/iam/role.js:220-221
# emits `name: props.roleName, namePrefix: !props.roleName ? namePrefix :
# undefined`, so omitting `roleName` yields a provider-computed name that
# Terraform strips from `.planned_values...values.name` entirely.
#
# WHY IT IS SHIPPED (REPAIR PASS 10, 2026-08-23): this exact authoring
# decision is the shape an adversarial verifier used to demonstrate an
# arm-parity break -- it scored 1.0 on awscdk and 0.0 here and on
# hcl_raw, with two deny messages the graded plan flatly contradicted
# ("found 0" roles for a plan holding two `aws_iam_role` resources).
# REPAIR PASSES 7-9 re-keyed role identity onto the plan ADDRESS and gave
# the attachment->role edge five resolution paths, which fixed it; until
# now that fix had no shipped, re-runnable proof on this arm. Its
# siblings are `reference-alt-cdk-no-role-name/` (awscdk) and
# `reference-alt-hcl-no-role-name/` (hcl_raw) -- the same authoring
# decision, three arms, so the parity claim is checkable by running three
# commands.
#
# Verified 2026-08-23, real toolchain (terraconstructs 0.2.13, cdktn
# 0.23.0, terraform 1.15.8 / hashicorp-aws 6.58.0, opa 1.19.0):
# tier0_pass=1, tier1_status=PASS, deny == [], reward 1.0 -- identical to
# solution/solve.sh and to the two sibling proofs on the other arms.
set -euo pipefail

mkdir -p lib
cat > lib/scenario-stack.ts <<'TS'
import { Construct } from "constructs";
import { AwsStack, AwsStackProps, iam } from "terraconstructs/lib/aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const batchRunner = new iam.Role(this, "BatchRunnerRole", {
      assumedBy: new iam.ServicePrincipal("ecs-tasks.amazonaws.com"),
    });

    const reportWriter = new iam.Role(this, "ReportWriterRole", {
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
    batchRunner.addManagedPolicy(s3ReadOnly);
    reportWriter.addManagedPolicy(s3ReadOnly);

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
