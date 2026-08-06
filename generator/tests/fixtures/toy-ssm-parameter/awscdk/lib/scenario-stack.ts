// Reference fixture for generator/check_reference_paths.py -- NOT a
// generated file, hand-authored to be oracle-CORRECT per
// specs/_toy/toy-ssm-parameter.yaml's oracle.intent. Dropped in place of
// the generated task's own lib/scenario-stack.ts (entry_file); bin/app.ts
// and everything else comes from the real generated
// tasks/anchor/toy-ssm-parameter-awscdk/environment/.
import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as ssm from "aws-cdk-lib/aws-ssm";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const param = new ssm.StringParameter(this, "Greeting", {
      parameterName: "/cdktn-bench-toy/greeting",
      stringValue: "hello-from-cdktn-bench",
    });

    const role = new iam.Role(this, "Reader", {
      assumedBy: new iam.ServicePrincipal("ec2.amazonaws.com"),
    });

    role.addToPolicy(
      new iam.PolicyStatement({
        actions: ["ssm:GetParameter", "ssm:GetParameters"],
        resources: [param.parameterArn],
      }),
    );
  }
}
