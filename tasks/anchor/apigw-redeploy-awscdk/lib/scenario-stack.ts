import * as cdk from "aws-cdk-lib";
import { Construct } from "constructs";
import * as apigateway from "aws-cdk-lib/aws-apigateway";
import * as lambda from "aws-cdk-lib/aws-lambda";
import * as iam from "aws-cdk-lib/aws-iam";

export class ScenarioStack extends cdk.Stack {
  constructor(scope: Construct, id: string, props?: cdk.StackProps) {
    super(scope, id, props);

    const api = new apigateway.RestApi(this, "RedeployApi", {
      restApiName: "apigw-redeploy-api",
      deployOptions: { stageName: "prod" },
    });

    // Explicit, path-scoped execution role (Amendment 16's flagged gap):
    // QADeployApplicationRole's IamRoleLifecycleScoped/IamPassRoleScoped
    // statements only permit iam:CreateRole/PassRole under
    // arn:aws:iam::<account>:role/cdktn-bench-task/* -- letting Lambda's
    // default L2 behavior auto-create an unnamed role at IAM's default
    // path (`/`) would AccessDeny under that role. Shared by both
    // functions, matching the other arms' single `lambda_exec` role.
    const execRole = new iam.Role(this, "LambdaExecRole", {
      path: "/cdktn-bench-task/",
      assumedBy: new iam.ServicePrincipal("lambda.amazonaws.com"),
      managedPolicies: [
        iam.ManagedPolicy.fromAwsManagedPolicyName("service-role/AWSLambdaBasicExecutionRole"),
      ],
    });

    const helloFn = new lambda.Function(this, "HelloFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: 'hello' });",
      ),
    });
    const versionFn = new lambda.Function(this, "VersionFn", {
      runtime: lambda.Runtime.NODEJS_20_X,
      handler: "index.handler",
      role: execRole,
      code: lambda.Code.fromInline(
        "exports.handler = async () => ({ statusCode: 200, body: JSON.stringify({ version: '1.0.0' }) });",
      ),
    });

    api.root
      .addResource("hello")
      .addMethod("GET", new apigateway.LambdaIntegration(helloFn));
    api.root
      .addResource("version")
      .addMethod("GET", new apigateway.LambdaIntegration(versionFn));

    new cdk.CfnOutput(this, "ApiUrl", { value: api.url });
  }
}
