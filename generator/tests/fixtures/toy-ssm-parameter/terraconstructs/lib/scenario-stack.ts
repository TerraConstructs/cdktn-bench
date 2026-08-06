// Reference fixture for generator/check_reference_paths.py -- NOT a
// generated file, hand-authored to be oracle-CORRECT per
// specs/_toy/toy-ssm-parameter.yaml's oracle.intent. Dropped in place of
// the generated task's own lib/scenario-stack.ts (entry_file); main.ts
// (the App/provider bootstrap) and everything else comes from the real
// generated tasks/anchor/toy-ssm-parameter-terraconstructs/environment/.
//
// Uses the @cdktn/provider-aws L1 bindings directly (IamRole/
// IamRolePolicy/SsmParameter), not terraconstructs' own L2 iam.Role /
// Role.addToPolicy() -- verified (2026-08-06) that the L2 idiom compiles
// through an intermediate `data "aws_iam_policy_document"` resource
// (Role.addToPolicy() -> PolicyDocument -> a data source, not a literal
// jsonencode-equivalent), which is ALSO plan-time-resolvable but puts the
// graph edge to aws_ssm_parameter.* one hop further away
// (aws_iam_role_policy.expressions.policy.references points at the data
// source, not directly at the parameter) than hcl_raw's raw-jsonencode
// idiom. Using the L1 constructs directly here keeps this fixture's plan
// JSON shape identical (single-hop reference) to the hcl_raw fixture, so
// ONE tf_jsonpath (policy-resource-scoped-not-wildcard-tf) validates
// against both TF arms' reference fixtures unmodified -- the corrected,
// now-TRUE form of specs/SCHEMA.md §4.2's original claim. The one-hop-
// indirected L2 shape is still real and still needs handling by Slice D's
// hand-authored Rego (see the toy spec's own rego_hints) for an agent that
// legitimately chooses the idiomatic L2 API instead.
import { Construct } from "constructs";
import { AwsStack, AwsStackProps } from "terraconstructs/lib/aws";
import { iamRole, iamRolePolicy, ssmParameter } from "@cdktn/provider-aws";

export class ScenarioStack extends AwsStack {
  constructor(scope: Construct, id: string, props: AwsStackProps) {
    super(scope, id, props);

    const param = new ssmParameter.SsmParameter(this, "Greeting", {
      name: "/cdktn-bench-toy/greeting",
      type: "String",
      value: "hello-from-cdktn-bench",
      provider: this.provider,
    });

    const role = new iamRole.IamRole(this, "Reader", {
      provider: this.provider,
      name: "cdktn-bench-toy-ssm-reader",
      assumeRolePolicy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Principal: { Service: "ec2.amazonaws.com" },
            Action: "sts:AssumeRole",
          },
        ],
      }),
    });

    new iamRolePolicy.IamRolePolicy(this, "ReaderPolicy", {
      provider: this.provider,
      name: "read-greeting-parameter",
      role: role.id,
      policy: JSON.stringify({
        Version: "2012-10-17",
        Statement: [
          {
            Effect: "Allow",
            Action: ["ssm:GetParameter", "ssm:GetParameters"],
            Resource: `arn:*:ssm:*:*:parameter${param.name}`,
          },
        ],
      }),
    });
  }
}
